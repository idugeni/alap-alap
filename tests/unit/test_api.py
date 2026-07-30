"""Unit tests for the REST API.

Covers the guards added around ``/solve`` and ``/detect``: auth, rate limiting,
SSRF filtering and body validation. No test here starts a real browser; the
solve path is exercised with a patched :class:`~src.core.AlapAlap`.
"""

import dataclasses
from unittest.mock import patch

import pytest

from src.api.server import API_KEY_HEADER, create_app
from src.config import ApiConfig, AppConfig

VALID_SITEKEY = "0x4AAAAAAAQV1p8gT2jN3m4"


def build_config(**api_overrides) -> AppConfig:
    """An AppConfig with a generous rate limit unless a test says otherwise."""
    defaults = {"RATE_LIMIT_REQUESTS": 10_000}
    defaults.update(api_overrides)
    return dataclasses.replace(AppConfig(), api=dataclasses.replace(ApiConfig(), **defaults))


@pytest.fixture
def client():
    """Unauthenticated client."""
    return create_app(build_config()).test_client()


@pytest.fixture
def auth_client():
    """Client for an API that requires a key."""
    app = create_app(build_config(KEY="test-key"))
    return app.test_client()


class TestPublicEndpoints:
    """Endpoints that must stay reachable for probes."""

    def test_index(self, client):
        response = client.get("/")
        assert response.status_code == 200
        body = response.get_json()
        assert body["name"] == "Alap-Alap API"
        assert "/solve" in body["endpoints"]

    def test_index_reports_auth_state(self, client, auth_client):
        assert client.get("/").get_json()["auth_required"] is False
        assert auth_client.get("/").get_json()["auth_required"] is True

    def test_health(self, client):
        body = client.get("/health").get_json()
        assert body["status"] == "healthy"
        assert "dependencies" in body

    def test_health_needs_no_key(self, auth_client):
        assert auth_client.get("/health").status_code == 200

    def test_request_id_header(self, client):
        assert client.get("/health").headers.get("X-Request-ID")


class TestAuth:
    """API key enforcement."""

    def test_missing_key_is_rejected(self, auth_client):
        response = auth_client.get("/stats")
        assert response.status_code == 401
        assert response.get_json()["success"] is False

    def test_wrong_key_is_rejected(self, auth_client):
        response = auth_client.get("/stats", headers={API_KEY_HEADER: "wrong"})
        assert response.status_code == 401

    def test_correct_key_is_accepted(self, auth_client):
        assert auth_client.get("/stats", headers={API_KEY_HEADER: "test-key"}).status_code == 200

    def test_bearer_token_is_accepted(self, auth_client):
        response = auth_client.get("/stats", headers={"Authorization": "Bearer test-key"})
        assert response.status_code == 200

    def test_no_key_configured_means_open_access(self, client):
        assert client.get("/stats").status_code == 200


class TestRateLimit:
    """Sliding-window limiter."""

    def test_requests_over_the_limit_get_429(self):
        client = create_app(build_config(RATE_LIMIT_REQUESTS=3)).test_client()
        codes = [client.get("/stats").status_code for _ in range(5)]
        assert codes == [200, 200, 200, 429, 429]

    def test_429_carries_retry_after(self):
        client = create_app(build_config(RATE_LIMIT_REQUESTS=1)).test_client()
        client.get("/stats")
        response = client.get("/stats")
        assert response.status_code == 429
        assert response.headers.get("Retry-After")
        assert response.get_json()["retry_after"] > 0

    def test_public_endpoints_are_exempt(self):
        client = create_app(build_config(RATE_LIMIT_REQUESTS=1)).test_client()
        assert all(client.get("/health").status_code == 200 for _ in range(5))


class TestSsrfGuard:
    """The URL filter on /solve and /detect."""

    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1:8080/",
            "http://10.0.0.1/",
            "http://192.168.0.1/",
            "http://169.254.169.254/latest/meta-data/",
            "file:///etc/passwd",
        ],
    )
    @pytest.mark.parametrize("endpoint", ["/solve", "/detect"])
    def test_unsafe_targets_are_refused(self, client, endpoint, url):
        response = client.post(endpoint, json={"url": url})
        assert response.status_code == 400
        assert response.get_json()["success"] is False

    def test_allow_private_hosts_disables_the_guard(self):
        # With the guard off the request gets past validation and into the
        # detector, so it no longer fails with a 400.
        client = create_app(build_config(ALLOW_PRIVATE_HOSTS=True)).test_client()
        with patch("src.detector.SitekeyDetector") as detector:
            detector.return_value.detect_with_method.return_value = (None, None)
            response = client.post("/detect", json={"url": "http://127.0.0.1:5000/"})
        assert response.status_code != 400


class TestBodyValidation:
    """Pydantic validation of request bodies."""

    def test_missing_body_is_rejected(self, client):
        response = client.post("/detect")
        assert response.status_code == 400
        assert "JSON body" in response.get_json()["error"]

    def test_non_object_body_is_rejected(self, client):
        response = client.post("/detect", json=["not", "an", "object"])
        assert response.status_code == 400

    def test_missing_url_is_rejected(self, client):
        assert client.post("/detect", json={}).status_code == 400

    def test_blank_url_is_rejected(self, client):
        response = client.post("/detect", json={"url": "   "})
        assert response.status_code == 400

    def test_unknown_field_is_rejected(self, client):
        response = client.post("/detect", json={"url": "https://a.com", "bogus": 1})
        assert response.status_code == 400
        assert "bogus" in response.get_json()["error"]

    def test_retries_out_of_range_is_rejected(self, client):
        response = client.post("/solve", json={"url": "https://a.com", "retries": 999})
        assert response.status_code == 400

    def test_negative_timeout_is_rejected(self, client):
        response = client.post("/solve", json={"url": "https://a.com", "timeout": -5})
        assert response.status_code == 400


class TestErrorHandlers:
    """Errors come back as JSON, never HTML."""

    def test_unknown_route_returns_json(self, client):
        response = client.get("/does-not-exist")
        assert response.status_code == 404
        assert response.get_json()["success"] is False

    def test_wrong_method_returns_json(self, client):
        response = client.get("/solve")
        assert response.status_code == 405
        assert response.get_json()["success"] is False


def make_pooled_client(result, **api_overrides):
    """
    Build a client whose pool returns a fixed result.

    The browser must be injected through the pool: patching ``src.core.AlapAlap``
    no longer intercepts anything, because the pool resolves its factory at
    construction time. Without injection these tests would attempt real solves.
    """
    from src.api.pool import SolverPool

    class FixedAlap:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

        def close(self):
            pass

        def solve(self, *args, **kwargs):
            return result

        def solve_with_sitekey(self, *args, **kwargs):
            return result

    overrides = {"CONCURRENCY_WAIT_S": 5.0, "SOLVE_TIMEOUT_S": 5.0}
    overrides.update(api_overrides)
    cfg = build_config(**overrides)
    pool = SolverPool(cfg.api, alap_factory=FixedAlap)
    return create_app(cfg, pool=pool).test_client(), pool


class TestSolveEndpoint:
    """The solve path, with the browser injected through the pool."""

    def test_successful_solve(self):
        client, pool = make_pooled_client(
            {
                "success": True,
                "token": "tok-123",
                "sitekey": VALID_SITEKEY,
                "error": None,
                "time": 1.5,
                "attempts": 1,
            }
        )
        try:
            response = client.post("/solve", json={"url": "https://example.com/login"})
            assert response.status_code == 200
            assert response.get_json()["token"] == "tok-123"
        finally:
            pool.shutdown(timeout=10)

    def test_failed_solve_reports_502(self):
        client, pool = make_pooled_client(
            {
                "success": False,
                "token": None,
                "sitekey": VALID_SITEKEY,
                "error": "Solver failed",
                "time": 2.0,
                "attempts": 1,
            }
        )
        try:
            response = client.post("/solve", json={"url": "https://example.com/login"})
            assert response.status_code == 502
            assert response.get_json()["success"] is False
        finally:
            pool.shutdown(timeout=10)

    def test_tokens_can_be_withheld(self):
        client, pool = make_pooled_client(
            {
                "success": True,
                "token": "tok-123",
                "sitekey": VALID_SITEKEY,
                "error": None,
                "time": 1.0,
                "attempts": 1,
            },
            RETURN_TOKENS=False,
        )
        try:
            body = client.post("/solve", json={"url": "https://example.com/login"}).get_json()
            assert body["token"] is None
            assert body["token_withheld"] is True
        finally:
            pool.shutdown(timeout=10)


class TestDetectEndpoint:
    """The detect path, with the browser patched out."""

    def test_sitekey_found(self, client):
        with patch("src.detector.SitekeyDetector") as detector:
            detector.return_value.detect_with_method.return_value = (VALID_SITEKEY, "html")
            response = client.post("/detect", json={"url": "https://example.com"})
        assert response.status_code == 200
        body = response.get_json()
        assert body["sitekey"] == VALID_SITEKEY
        assert body["method"] == "html"

    def test_sitekey_not_found_returns_404(self, client):
        with patch("src.detector.SitekeyDetector") as detector:
            detector.return_value.detect_with_method.return_value = (None, None)
            response = client.post("/detect", json={"url": "https://example.com"})
        assert response.status_code == 404
        assert response.get_json()["success"] is False


class TestSitekeysEndpoint:
    """Listing and filtering."""

    def test_response_shape(self, client):
        body = client.get("/sitekeys").get_json()
        assert set(body) == {"count", "total", "sitekeys"}

    def test_invalid_limit_is_rejected(self, client):
        response = client.get("/sitekeys?limit=abc")
        assert response.status_code == 400

    def test_limit_is_clamped(self, client):
        assert client.get("/sitekeys?limit=99999").status_code == 200

    def test_stats_shape(self, client):
        body = client.get("/stats").get_json()
        assert body["success"] is True
        for key in ("total_sitekeys", "active_sitekeys", "success_rate"):
            assert key in body


class PooledFakeAlap:
    """Fake browser for pool-backed API tests."""

    launches: list = []

    def __init__(self, proxy=None, headless=True, timeout=None, allow_private_hosts=True):
        self.proxy = proxy

    def start(self):
        PooledFakeAlap.launches.append(self.proxy)

    def close(self):
        pass

    def solve(self, url, invisible=True, retries=1, timeout=None):
        return {
            "success": "fail" not in url,
            "token": None if "fail" in url else "tok-pooled",
            "sitekey": VALID_SITEKEY,
            "error": "Solver failed" if "fail" in url else None,
            "time": 0.01,
            "attempts": retries,
        }

    def solve_with_sitekey(self, url, sitekey, invisible=True, retries=1, timeout=None):
        return self.solve(url, invisible=invisible, retries=retries, timeout=timeout)


@pytest.fixture
def pooled_client():
    """A client whose pool is backed by a fake browser."""
    from src.api.pool import SolverPool

    PooledFakeAlap.launches = []
    cfg = build_config(MAX_CONCURRENT_SOLVES=2, CONCURRENCY_WAIT_S=5.0, SOLVE_TIMEOUT_S=5.0)
    pool = SolverPool(cfg.api, alap_factory=PooledFakeAlap)
    try:
        yield create_app(cfg, pool=pool).test_client()
    finally:
        pool.shutdown(timeout=10)


class TestPooledSolve:
    """/solve now runs on a pooled browser."""

    def test_sync_solve_still_returns_the_token(self, pooled_client):
        response = pooled_client.post("/solve", json={"url": "https://example.com/login"})
        assert response.status_code == 200
        assert response.get_json()["token"] == "tok-pooled"

    def test_browsers_are_reused_across_requests(self, pooled_client):
        # This is the point of the pool: 8 requests must not mean 8 launches.
        for index in range(8):
            pooled_client.post("/solve", json={"url": f"https://example.com/{index}"})
        assert len(PooledFakeAlap.launches) <= 2

    def test_failed_solve_still_reports_502(self, pooled_client):
        response = pooled_client.post("/solve", json={"url": "https://example.com/fail"})
        assert response.status_code == 502

    def test_queue_full_returns_503(self):
        import time

        from src.api.pool import SolverPool

        class SlowAlap(PooledFakeAlap):
            def solve(self, url, **kwargs):
                time.sleep(1.0)
                return super().solve(url, **kwargs)

        cfg = build_config(MAX_CONCURRENT_SOLVES=1, QUEUE_MAX_SIZE=1, CONCURRENCY_WAIT_S=0.1)
        pool = SolverPool(cfg.api, alap_factory=SlowAlap)
        client = create_app(cfg, pool=pool).test_client()
        try:
            codes = [
                client.post("/jobs", json={"url": f"https://example.com/{i}"}).status_code
                for i in range(8)
            ]
            assert 503 in codes
        finally:
            pool.shutdown(timeout=10)


class TestJobEndpoints:
    """Async submit and poll."""

    def test_post_jobs_returns_202_with_an_id(self, pooled_client):
        response = pooled_client.post("/jobs", json={"url": "https://example.com/login"})
        assert response.status_code == 202
        body = response.get_json()
        assert body["job_id"]
        assert body["poll"] == f"/jobs/{body['job_id']}"

    def test_post_jobs_sets_a_location_header(self, pooled_client):
        response = pooled_client.post("/jobs", json={"url": "https://example.com/login"})
        assert response.headers["Location"].startswith("/jobs/")

    def test_polling_reaches_a_result(self, pooled_client):
        import time

        job_id = pooled_client.post("/jobs", json={"url": "https://example.com/login"}).get_json()[
            "job_id"
        ]

        for _ in range(100):
            body = pooled_client.get(f"/jobs/{job_id}").get_json()
            if body["status"] in ("done", "error"):
                break
            time.sleep(0.02)

        assert body["status"] == "done"
        assert body["token"] == "tok-pooled"

    def test_unknown_job_returns_404(self, pooled_client):
        assert pooled_client.get("/jobs/deadbeef").status_code == 404

    def test_job_list(self, pooled_client):
        pooled_client.post("/solve", json={"url": "https://example.com/login"})
        body = pooled_client.get("/jobs").get_json()
        assert body["count"] >= 1
        assert "pool" in body

    def test_job_list_invalid_limit(self, pooled_client):
        assert pooled_client.get("/jobs?limit=abc").status_code == 400

    def test_jobs_are_ssrf_guarded(self, pooled_client):
        response = pooled_client.post("/jobs", json={"url": "http://127.0.0.1:8080/"})
        assert response.status_code == 400

    def test_jobs_require_auth_when_configured(self):
        from src.api.pool import SolverPool

        cfg = build_config(KEY="k")
        pool = SolverPool(cfg.api, alap_factory=PooledFakeAlap)
        client = create_app(cfg, pool=pool).test_client()
        try:
            assert client.post("/jobs", json={"url": "https://a.com"}).status_code == 401
            assert client.get("/jobs").status_code == 401
        finally:
            pool.shutdown(timeout=10)

    def test_jobs_validate_the_body(self, pooled_client):
        assert pooled_client.post("/jobs", json={"url": "  "}).status_code == 400
        assert pooled_client.post("/jobs", json={"bogus": 1}).status_code == 400


class TestPoolReporting:
    """Pool state is observable."""

    def test_health_includes_pool(self, pooled_client):
        assert "pool" in pooled_client.get("/health").get_json()

    def test_stats_includes_pool(self, pooled_client):
        assert "pool" in pooled_client.get("/stats").get_json()

    def test_index_advertises_job_endpoints(self, pooled_client):
        endpoints = pooled_client.get("/").get_json()["endpoints"]
        assert "/jobs" in endpoints
        assert "/jobs/<id>" in endpoints
