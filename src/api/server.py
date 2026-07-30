"""
Alap-Alap REST API Server

Flask-based REST API for the captcha solver.

Security posture
----------------
``/solve`` and ``/detect`` take a URL from the caller and fetch it with both
:mod:`requests` and a real browser, so an unguarded deployment is an SSRF
primitive and a free browser farm. This module therefore applies, in order:

1. **Rate limiting** per client address (``api.RATE_LIMIT_REQUESTS`` per
   ``api.RATE_LIMIT_WINDOW_S``).
2. **API key auth** when ``api.KEY`` / ``ALAP_API_KEY`` is set. Unset means open
   access, which keeps local development frictionless; :func:`create_app` logs a
   loud warning when the service is both open and bound off-loopback.
3. **SSRF filtering** through :func:`src.security.validate_url`, rejecting
   loopback, private, link-local and cloud-metadata targets unless
   ``api.ALLOW_PRIVATE_HOSTS`` is enabled.
4. **Concurrency capping** via a semaphore, because every solve starts a
   browser.

The bundled server is Flask's development server. Put a real WSGI server and TLS
in front of it before exposing it to anything untrusted.
"""

from __future__ import annotations

import atexit
import importlib.util
import time
import uuid
from collections.abc import Callable
from functools import lru_cache, wraps
from typing import Any

from flask import Flask, g, jsonify, request
from loguru import logger
from pydantic import ValidationError
from werkzeug.exceptions import HTTPException

from src.api.pool import QueueFullError, SolverPool
from src.config import AppConfig, config
from src.errors import UnsafeUrlError
from src.models import DetectRequest, SolveRequest
from src.security import RateLimiter, check_api_key, validate_url

#: Header carrying the API key.
API_KEY_HEADER = "X-API-Key"

#: Endpoints reachable without a key so health probes keep working.
PUBLIC_ENDPOINTS = frozenset({"index", "health"})


def _client_key() -> str:
    """
    Identify the caller for rate limiting.

    Uses the socket peer address only. ``X-Forwarded-For`` is deliberately
    ignored: it is caller-controlled, so trusting it would let anyone bypass the
    limiter by rotating a header value.
    """
    return request.remote_addr or "unknown"


def _error(message: str, status: int, **extra: Any):
    """Uniform JSON error envelope."""
    payload: dict[str, Any] = {"success": False, "error": message}
    payload.update(extra)
    return jsonify(payload), status


def _validation_message(exc: ValidationError) -> str:
    """Flatten a pydantic error into one readable line."""
    parts = []
    for err in exc.errors():
        location = ".".join(str(item) for item in err.get("loc", ())) or "body"
        parts.append(f"{location}: {err.get('msg', 'invalid')}")
    return "; ".join(parts)


def create_app(app_config: AppConfig | None = None, pool: SolverPool | None = None) -> Flask:
    """
    Create and configure the Flask application.

    Args:
        app_config: Configuration to use. Defaults to the global
            :data:`src.config.config`; tests inject their own.
        pool: Solver pool to use. Defaults to a fresh :class:`SolverPool`; tests
            inject one backed by a fake browser.

    Returns:
        A configured :class:`flask.Flask` instance.
    """
    cfg = app_config or config
    api_cfg = cfg.api

    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.config["ALAP_CONFIG"] = cfg

    limiter = RateLimiter(api_cfg.RATE_LIMIT_REQUESTS, api_cfg.RATE_LIMIT_WINDOW_S)

    # Browsers are heavy and slow to start, so they are pooled rather than
    # created per request. The pool's bounded queue also provides the
    # concurrency cap that a semaphore used to give us.
    solver_pool = pool if pool is not None else SolverPool(api_cfg)
    app.extensions["alap_pool"] = solver_pool

    if pool is None:
        # Worker threads are daemons, but closing the browsers on the way out
        # avoids leaving orphaned Camoufox processes behind. Only pools this
        # function owns are registered: an injected pool belongs to the caller,
        # and registering it would fire after the caller's streams are gone.
        atexit.register(solver_pool.shutdown)

    auth_enabled = bool(api_cfg.KEY)
    exposed = api_cfg.HOST not in ("127.0.0.1", "localhost", "::1")

    if not auth_enabled and exposed:
        logger.warning(
            f"API is bound to {api_cfg.HOST} with no API key set. "
            f"Anyone who can reach this port can drive the solver and make the "
            f"host fetch arbitrary URLs. Set ALAP_API_KEY to require auth."
        )
    if api_cfg.ALLOW_PRIVATE_HOSTS:
        logger.warning(
            "api.ALLOW_PRIVATE_HOSTS is enabled: the SSRF guard is off and "
            "callers can target loopback and private addresses."
        )

    # ------------------------------------------------------------------ #
    # Cross-cutting concerns
    # ------------------------------------------------------------------ #

    @app.before_request
    def _before():
        g.request_id = uuid.uuid4().hex[:12]
        g.started_at = time.monotonic()

        if request.endpoint in PUBLIC_ENDPOINTS or request.endpoint is None:
            return None

        client = _client_key()

        if not limiter.allow(client):
            retry_after = limiter.retry_after(client)
            logger.warning(f"Rate limited {client} on {request.path}")
            response, status = _error(
                "Rate limit exceeded",
                429,
                retry_after=round(retry_after, 1),
            )
            response.headers["Retry-After"] = str(max(1, int(retry_after) + 1))
            return response, status

        if auth_enabled:
            provided = request.headers.get(API_KEY_HEADER)
            if not provided:
                authorization = request.headers.get("Authorization", "")
                if authorization.lower().startswith("bearer "):
                    provided = authorization[7:].strip()

            if not check_api_key(provided, api_cfg.KEY):
                logger.warning(f"Rejected unauthenticated request from {client}")
                return _error("Invalid or missing API key", 401)

        return None

    @app.after_request
    def _after(response):
        request_id = getattr(g, "request_id", None)
        if request_id:
            response.headers["X-Request-ID"] = request_id
        started = getattr(g, "started_at", None)
        if started is not None:
            elapsed = time.monotonic() - started
            logger.debug(
                f"[{request_id}] {request.method} {request.path} "
                f"-> {response.status_code} in {elapsed:.2f}s"
            )
        return response

    @app.errorhandler(400)
    def _bad_request(_e):
        return _error("Malformed request", 400)

    @app.errorhandler(404)
    def _not_found(_e):
        return _error("Endpoint not found", 404)

    @app.errorhandler(405)
    def _method_not_allowed(_e):
        return _error("Method not allowed", 405)

    @app.errorhandler(413)
    def _too_large(_e):
        return _error("Request body too large", 413)

    @app.errorhandler(500)
    def _server_error(_e):  # pragma: no cover - Flask re-raises in testing mode
        return _error("Internal server error", 500)

    @app.errorhandler(Exception)
    def _unhandled(exc: Exception):
        # Keep other HTTP errors (415, 414, ...) as themselves rather than
        # flattening every one of them into a 500.
        if isinstance(exc, HTTPException):
            return _error(exc.description or exc.name, exc.code or 500)
        # Log the detail, return a generic message: exception text can leak
        # internal paths, hostnames and proxy credentials.
        logger.exception(f"[{getattr(g, 'request_id', '-')}] Unhandled error: {exc}")
        return _error("Internal server error", 500)

    def parse_body(model):
        """Decorator validating the JSON body against a pydantic model."""

        def decorator(view: Callable):
            @wraps(view)
            def wrapper(*args, **kwargs):
                raw = request.get_json(silent=True)
                if raw is None:
                    return _error("A JSON body is required", 400)
                if not isinstance(raw, dict):
                    return _error("The JSON body must be an object", 400)
                try:
                    payload = model(**raw)
                except ValidationError as exc:
                    return _error(_validation_message(exc), 400)
                return view(payload, *args, **kwargs)

            return wrapper

        return decorator

    def guard_url(url: str) -> str | None:
        """Return an error message when ``url`` must not be fetched."""
        try:
            validate_url(url, allow_private=api_cfg.ALLOW_PRIVATE_HOSTS)
        except UnsafeUrlError as exc:
            logger.warning(f"Blocked URL from {_client_key()}: {exc}")
            return str(exc)
        return None

    # ------------------------------------------------------------------ #
    # Routes
    # ------------------------------------------------------------------ #

    @app.route("/")
    def index():
        """API info."""
        return jsonify(
            {
                "name": "Alap-Alap API",
                "version": _package_version(),
                "auth_required": auth_enabled,
                "endpoints": {
                    "/solve": "POST - Solve captcha (waits for the result)",
                    "/jobs": "POST - Queue a solve, GET - list recent jobs",
                    "/jobs/<id>": "GET - Poll a queued solve",
                    "/detect": "POST - Detect sitekey",
                    "/health": "GET - Health check",
                    "/sitekeys": "GET - List sitekeys",
                    "/stats": "GET - Database statistics",
                },
            }
        )

    @app.route("/health")
    def health():
        """Health check endpoint."""
        return jsonify(
            {
                "status": "healthy",
                "service": "alap-alap",
                "version": _package_version(),
                "dependencies": dict(_dependency_status()),
                "pool": solver_pool.stats(),
            }
        )

    @app.route("/detect", methods=["POST"])
    @parse_body(DetectRequest)
    def detect(payload: DetectRequest):
        """
        Detect sitekey from URL.

        Request body:
            {"url": "https://example.com", "proxy": "user:pass@host:port"}

        Response:
            {"success": true, "sitekey": "0x4AAAAAAA...", "method": "html"}
        """
        blocked = guard_url(payload.url)
        if blocked:
            return _error(blocked, 400)

        try:
            from src.detector import SitekeyDetector

            detector = SitekeyDetector(
                proxy=payload.proxy,
                allow_private_hosts=api_cfg.ALLOW_PRIVATE_HOSTS,
            )
            try:
                sitekey, method = detector.detect_with_method(payload.url)
            finally:
                detector.close()

            if sitekey:
                return jsonify({"success": True, "sitekey": sitekey, "method": method})
            return jsonify({"success": False, "error": "Sitekey not found"}), 404

        except Exception as e:
            logger.error(f"Detection error: {e}")
            return _error(str(e), 500)

    @app.route("/solve", methods=["POST"])
    @parse_body(SolveRequest)
    def solve(payload: SolveRequest):
        """
        Solve Turnstile captcha.

        Request body:
            {
                "url": "https://example.com/login",
                "sitekey": "0x4AAAAAAA...",     // optional
                "proxy": "user:pass@host:port",  // optional
                "invisible": true,               // optional
                "retries": 1,                    // optional
                "timeout": 180                   // optional, seconds
            }

        Response:
            {
                "success": true,
                "token": "0...",
                "sitekey": "0x4AAAAAAA...",
                "time": 1.23
            }
        """
        blocked = guard_url(payload.url)
        if blocked:
            return _error(blocked, 400)

        # Total patience: the solve's own budget plus time spent queueing.
        solve_budget = payload.timeout or api_cfg.SOLVE_TIMEOUT_S
        wait_budget = solve_budget + api_cfg.CONCURRENCY_WAIT_S

        try:
            job = solver_pool.solve(payload, timeout=wait_budget)
        except QueueFullError as e:
            logger.warning(f"Rejected solve: {e}")
            return _error(str(e), 503, retry_after=5)
        except Exception as e:
            logger.error(f"Solve error: {e}")
            return _error(str(e), 500)

        if not job.finished:
            # Rather than hold the connection open indefinitely, hand back a
            # job id so the caller can poll GET /jobs/<id>.
            response = jsonify(
                {
                    **job.to_dict(include_token=api_cfg.RETURN_TOKENS),
                    "message": "Still working; poll the job endpoint for the result.",
                    "poll": f"/jobs/{job.id}",
                }
            )
            response.headers["Location"] = f"/jobs/{job.id}"
            return response, 202

        if job.status == "error":
            return _error(job.error or "Solve failed", 500, job_id=job.id)

        result = job.result or {}
        if not job.recorded:
            job.recorded = True
            _record(payload.url, result)

        if not api_cfg.RETURN_TOKENS:
            result = {**result, "token": None, "token_withheld": True}

        return jsonify(result), (200 if result.get("success") else 502)

    @app.route("/jobs", methods=["POST"])
    @parse_body(SolveRequest)
    def create_job(payload: SolveRequest):
        """
        Queue a solve and return immediately.

        A solve takes tens of seconds, which is a long time to hold an HTTP
        connection open. This accepts the work and hands back an id:

            {"job_id": "ab12...", "status": "queued", "poll": "/jobs/ab12..."}
        """
        blocked = guard_url(payload.url)
        if blocked:
            return _error(blocked, 400)

        try:
            job = solver_pool.submit(payload)
        except QueueFullError as e:
            logger.warning(f"Rejected job: {e}")
            return _error(str(e), 503, retry_after=5)

        response = jsonify(
            {
                "success": True,
                **job.to_dict(include_token=api_cfg.RETURN_TOKENS),
                "poll": f"/jobs/{job.id}",
            }
        )
        response.headers["Location"] = f"/jobs/{job.id}"
        return response, 202

    @app.route("/jobs/<job_id>")
    def get_job(job_id: str):
        """
        Read a queued, running or finished job.

        Finished jobs are retained for ``api.JOB_TTL_S`` seconds.
        """
        job = solver_pool.get(job_id)
        if job is None:
            return _error("Job not found or expired", 404)

        payload = job.to_dict(include_token=api_cfg.RETURN_TOKENS)
        result = job.result or {}

        # Mirror into the database once, not on every poll.
        if job.status == "done" and result and not job.recorded:
            job.recorded = True
            _record(job.request.url, result)

        status = 200
        if job.status == "error":
            status = 500
        elif job.status == "done" and not result.get("success"):
            status = 502

        return jsonify(payload), status

    @app.route("/jobs")
    def list_jobs():
        """Recent jobs, newest first."""
        try:
            limit = min(max(int(request.args.get("limit", 50)), 1), 500)
        except ValueError:
            return _error("limit must be an integer", 400)

        jobs = solver_pool.list_jobs(limit)
        return jsonify(
            {
                "count": len(jobs),
                "jobs": [job.to_dict(include_token=api_cfg.RETURN_TOKENS) for job in jobs],
                "pool": solver_pool.stats(),
            }
        )

    @app.route("/sitekeys")
    def sitekeys():
        """
        List sitekeys in the database.

        Query parameters:
            status: filter by active/inactive/unknown
            domain: exact domain match
            q:      free-text search
            limit:  maximum entries to return (default 100, max 1000)
        """
        from src.sitekeys_db import sitekeys_db

        status = request.args.get("status")
        domain = request.args.get("domain")
        query = request.args.get("q")

        try:
            limit = min(max(int(request.args.get("limit", 100)), 1), 1000)
        except ValueError:
            return _error("limit must be an integer", 400)

        if query:
            entries = sitekeys_db.search(query)
        elif domain:
            entries = sitekeys_db.get_by_domain(domain)
        else:
            entries = sitekeys_db.get_all()

        if status:
            entries = [e for e in entries if e.status == status]

        total = len(entries)
        entries = entries[:limit]

        return jsonify(
            {
                "count": len(entries),
                "total": total,
                "sitekeys": [
                    {
                        "sitekey": e.sitekey,
                        "platform": e.platform_name,
                        "domain": e.domain,
                        "status": e.status,
                        "solve_count": e.solve_count,
                        "success_count": e.success_count,
                        "success_rate": round(e.success_rate, 3),
                        "last_seen": e.last_seen,
                        "token_fresh": e.token_is_fresh,
                        "token_expires_in": (
                            round(e.token_expires_in, 1) if e.token_expires_in is not None else None
                        ),
                        "tags": e.tags or [],
                    }
                    for e in entries
                ],
            }
        )

    @app.route("/stats")
    def stats():
        """Aggregate database and pool statistics."""
        from src.sitekeys_db import sitekeys_db

        return jsonify({"success": True, **sitekeys_db.stats(), "pool": solver_pool.stats()})

    return app


def _record(url: str, result: dict[str, Any]) -> None:
    """Mirror a solve into the sitekeys database, never failing the request."""
    try:
        from src.sitekeys_db import sitekeys_db

        sitekeys_db.record_result(url, result, tags=["api"])
    except Exception as e:  # pragma: no cover - bookkeeping must not 500
        logger.warning(f"Could not record solve for {url}: {e}")


def _package_version() -> str:
    """Installed package version, or ``unknown`` when running from source."""
    try:
        from importlib.metadata import version

        return version("alap-alap")
    except Exception:
        return "unknown"


@lru_cache(maxsize=1)
def _dependency_status() -> tuple[tuple[str, bool], ...]:
    """
    Report whether the browser stack is installed.

    Uses :func:`importlib.util.find_spec` rather than importing: a health probe
    must stay cheap, and importing camoufox pulls in the whole browser stack.
    """
    names = ("camoufox", "playwright", "requests")
    status: list[tuple[str, bool]] = []
    for name in names:
        try:
            found = importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):
            found = False
        status.append((name, found))
    return tuple(status)
