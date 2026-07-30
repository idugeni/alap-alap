"""
Alap-Alap Core Module

Main entry point for the Alap-Alap captcha solver.
"""

from __future__ import annotations

import contextlib
import random
import time
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from loguru import logger

from src.config import config
from src.errors import AlapAlapError, BrowserError
from src.models import SolveOutcome

from ..detector import SitekeyDetector
from ..solver import CaptchaSolver


def compute_backoff(
    attempt: int,
    error: str | None = None,
    *,
    base: float | None = None,
    maximum: float | None = None,
    jitter_pct: float | None = None,
) -> float:
    """
    Delay before the next retry, in seconds.

    Rate-limit errors get the flat ``RATE_LIMIT_DELAY``; everything else gets
    exponential backoff capped at ``RETRY_DELAY_MAX``. Jitter is applied so
    parallel workers do not retry in lockstep.

    Args:
        attempt: Zero-based index of the attempt that just failed.
        error: Error text, inspected for rate-limit and timeout markers.
        base: Override ``config.retry.RETRY_DELAY_BASE``.
        maximum: Override ``config.retry.RETRY_DELAY_MAX``.
        jitter_pct: Override ``config.retry.RETRY_JITTER_PCT``.
    """
    cfg = config.retry
    base = cfg.RETRY_DELAY_BASE if base is None else base
    maximum = cfg.RETRY_DELAY_MAX if maximum is None else maximum
    jitter_pct = cfg.RETRY_JITTER_PCT if jitter_pct is None else jitter_pct

    text = (error or "").lower()
    if "rate limit" in text or "429" in text or "too many requests" in text:
        delay = cfg.RATE_LIMIT_DELAY
    else:
        delay = min(base * (2 ** max(0, attempt)), maximum)

    if jitter_pct > 0:
        spread = delay * jitter_pct
        delay = max(0.0, delay + random.uniform(-spread, spread))

    return min(delay, maximum)


def classify_error(error: str | None) -> str:
    """Bucket an error string so callers can report a useful reason."""
    text = (error or "").lower()
    if not text:
        return "unknown"
    if "rate limit" in text or "429" in text or "too many requests" in text:
        return "rate_limit"
    if "timeout" in text or "timed out" in text:
        return "timeout"
    if "sitekey" in text:
        return "sitekey"
    if "proxy" in text:
        return "proxy"
    if "browser" in text or "camoufox" in text or "playwright" in text:
        return "browser"
    return "other"


class AlapAlap:
    """
    Alap-Alap - Cloudflare Turnstile Captcha Solver

    A high-performance captcha solver that automatically detects sitekeys
    and solves Cloudflare Turnstile challenges using Camoufox for
    fingerprint resistance.

    Usage:
        >>> from src.core import AlapAlap
        >>> with AlapAlap() as alap:
        ...     result = alap.solve("https://example.com/login")
        ...     print(result)

    The context manager is the recommended form because it guarantees the
    browser is closed, but the browser also starts on demand so a plain
    ``AlapAlap().solve(url)`` works; call :meth:`close` when done.
    """

    def __init__(
        self,
        proxy: str | None = None,
        headless: bool = True,
        *,
        timeout: float | None = None,
        allow_private_hosts: bool = True,
    ):
        """
        Initialize Alap-Alap solver.

        Args:
            proxy: Optional proxy string (format: user:pass@host:port)
            headless: Run browser in headless mode (default: True)
            timeout: Wall-clock budget per solve in seconds. Defaults to
                ``config.solver.SOLVE_TIMEOUT_S``; zero disables it.
            allow_private_hosts: Allow solving loopback/private addresses.
                The REST API sets this to ``False`` to block SSRF.
        """
        self.proxy = proxy
        self.headless = headless
        self.timeout = config.solver.SOLVE_TIMEOUT_S if timeout is None else float(timeout)
        self.allow_private_hosts = allow_private_hosts
        self.detector = SitekeyDetector(proxy=proxy, allow_private_hosts=allow_private_hosts)
        self.solver: CaptchaSolver | None = None
        self._auto_started = False

    # ----------------------------------------------------------------- #
    # Lifecycle
    # ----------------------------------------------------------------- #

    def __enter__(self) -> AlapAlap:
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def start(self) -> AlapAlap:
        """Start the browser. Idempotent."""
        if self.solver is None:
            self.solver = CaptchaSolver(
                proxy=self.proxy,
                headless=self.headless,
                timeout=self.timeout,
            )
        if not self.solver.is_running:
            self.solver.start()
        return self

    def close(self) -> None:
        """Stop the browser and release the HTTP session."""
        if self.solver:
            self.solver.stop()
            self.solver = None
        self._auto_started = False
        self.detector.close()

    def _ensure_started(self) -> CaptchaSolver:
        """Start the browser on first use so ``with`` stays optional."""
        if self.solver is None or not self.solver.is_running:
            self.start()
            self._auto_started = True
        assert self.solver is not None
        return self.solver

    def __del__(self):  # pragma: no cover - interpreter teardown
        try:
            if self._auto_started and self.solver is not None:
                self.solver.stop()
        except Exception:
            pass

    # ----------------------------------------------------------------- #
    # Solving
    # ----------------------------------------------------------------- #

    def solve(
        self,
        url: str,
        invisible: bool = True,
        *,
        retries: int = 1,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """
        Solve Turnstile captcha for a given URL.

        Args:
            url: Target URL to solve captcha on
            invisible: Use invisible mode (default: True)
            retries: Total solve attempts (values below 1 are treated as 1)
            timeout: Per-attempt wall-clock budget in seconds

        Returns:
            dict with 'success', 'token', 'sitekey', 'error', 'time', 'attempts'
        """
        start_time = time.time()

        sitekey = self.detector.detect(url)
        if not sitekey:
            logger.warning(f"No sitekey found for {url}")
            return SolveOutcome.fail(
                "Could not detect sitekey",
                sitekey=None,
                elapsed=time.time() - start_time,
                attempts=0,
            ).to_dict()

        logger.info(f"Solving captcha for {url}")
        return self._run(
            url,
            sitekey,
            invisible,
            retries=retries,
            timeout=timeout,
            start_time=start_time,
        )

    def solve_with_sitekey(
        self,
        url: str,
        sitekey: str,
        invisible: bool = True,
        *,
        retries: int = 1,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """
        Solve Turnstile captcha with known sitekey.

        Args:
            url: Target URL
            sitekey: Known sitekey
            invisible: Use invisible mode (default: True)
            retries: Total solve attempts (values below 1 are treated as 1)
            timeout: Per-attempt wall-clock budget in seconds

        Returns:
            dict with 'success', 'token', 'sitekey', 'error', 'time', 'attempts'
        """
        logger.info(f"Solving captcha for {url} with sitekey {sitekey[:20]}...")
        return self._run(url, sitekey, invisible, retries=retries, timeout=timeout)

    def _run(
        self,
        url: str,
        sitekey: str,
        invisible: bool,
        *,
        retries: int,
        timeout: float | None,
        start_time: float | None = None,
    ) -> dict[str, Any]:
        """Attempt a solve up to ``retries`` times and build the outcome dict."""
        start_time = time.time() if start_time is None else start_time
        total_attempts = self._clamp_attempts(retries)
        last_error = "Solver failed"

        for attempt in range(total_attempts):
            try:
                solver = self._ensure_started()
                token = solver.solve(url, sitekey, invisible, timeout=timeout)
            except AlapAlapError as exc:
                token, last_error = None, str(exc)
                logger.error(f"Attempt {attempt + 1}/{total_attempts} failed: {exc}")
                # A dead browser cannot be reused; drop it so the next attempt
                # starts a fresh one instead of failing the same way.
                if isinstance(exc, BrowserError):
                    self._reset_solver()
            except Exception as exc:  # noqa: BLE001 - surfaced in the result dict
                token, last_error = None, str(exc)
                logger.error(f"Attempt {attempt + 1}/{total_attempts} failed: {exc}")
                self._reset_solver()
            else:
                if token:
                    elapsed = time.time() - start_time
                    logger.success(f"Solved in {elapsed:.1f}s")
                    return SolveOutcome.ok(token, sitekey, elapsed, attempts=attempt + 1).to_dict()
                last_error = "Solver failed"

            if attempt < total_attempts - 1:
                delay = compute_backoff(attempt, last_error)
                logger.info(f"Retrying in {delay:.1f}s...")
                time.sleep(delay)

        elapsed = time.time() - start_time
        logger.error(f"Solver failed for {url}")
        return SolveOutcome.fail(
            last_error,
            sitekey=sitekey,
            elapsed=elapsed,
            attempts=total_attempts,
        ).to_dict()

    @staticmethod
    def _clamp_attempts(retries: int) -> int:
        """
        Normalise a requested attempt count.

        Values below 1 become 1 (they used to leave the result unset and crash),
        and anything above ``config.retry.MAX_RETRIES`` is capped so a stray
        ``--retries 9999`` cannot tie up a browser indefinitely.
        """
        requested = max(1, int(retries))
        ceiling = max(1, config.retry.MAX_RETRIES)
        if requested > ceiling:
            logger.warning(f"Capping {requested} attempts at retry.MAX_RETRIES={ceiling}")
            return ceiling
        return requested

    def _reset_solver(self) -> None:
        """Discard the current browser so the next attempt starts clean."""
        if self.solver is not None:
            # Teardown is best effort: the browser may already be gone.
            with contextlib.suppress(Exception):  # pragma: no cover
                self.solver.stop()
            self.solver = None

    def solve_many(
        self,
        urls: Iterable[str],
        invisible: bool = True,
        *,
        retries: int = 1,
        timeout: float | None = None,
        on_result: Callable[[dict[str, Any]], None] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Solve several URLs sequentially, reusing one browser.

        Reusing the browser is the point: starting Camoufox is by far the most
        expensive step, so a batch through one instance is much faster than one
        instance per URL.

        Args:
            urls: URLs to solve.
            invisible: Use invisible mode.
            retries: Attempts per URL.
            timeout: Per-attempt budget in seconds.
            on_result: Called with each result as it completes, for progress
                reporting.

        Returns:
            One result dict per URL, each with an added ``url`` key.
        """
        results: list[dict[str, Any]] = []
        stagger = max(0.0, config.batch.STAGGER_S)

        for index, url in enumerate(urls):
            if index and stagger:
                time.sleep(stagger)

            try:
                result = self.solve(url, invisible, retries=retries, timeout=timeout)
            except Exception as exc:  # noqa: BLE001 - one bad URL must not stop the batch
                logger.error(f"Unexpected error solving {url}: {exc}")
                result = SolveOutcome.fail(str(exc)).to_dict()
                self._reset_solver()

            result["url"] = url
            results.append(result)

            if on_result:
                on_result(result)

            if not result["success"] and not config.batch.CONTINUE_ON_ERROR:
                logger.warning("Stopping batch after a failure (batch.CONTINUE_ON_ERROR is off)")
                break

        return results


def _partition(items: Sequence[str], buckets: int) -> list[list[str]]:
    """Split ``items`` round-robin into at most ``buckets`` non-empty lists."""
    buckets = max(1, min(buckets, len(items) or 1))
    groups: list[list[str]] = [[] for _ in range(buckets)]
    for index, item in enumerate(items):
        groups[index % buckets].append(item)
    return [group for group in groups if group]


def solve_batch(
    urls: Sequence[str],
    *,
    proxy: str | None = None,
    proxies: Sequence[str] | None = None,
    headless: bool = True,
    invisible: bool = True,
    retries: int = 1,
    timeout: float | None = None,
    workers: int | None = None,
    allow_private_hosts: bool = True,
    on_result: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """
    Solve many URLs in parallel, one browser per worker.

    Playwright's sync API is not thread safe, so each worker gets its own
    :class:`AlapAlap` (and therefore its own browser) and handles a slice of the
    URL list. Results come back in input order.

    Args:
        urls: URLs to solve.
        proxy: Single proxy for every worker.
        proxies: Proxy pool; workers are assigned round-robin. Overrides
            ``proxy`` when provided.
        headless: Run browsers headless.
        invisible: Use invisible mode.
        retries: Attempts per URL.
        timeout: Per-attempt budget in seconds.
        workers: Parallel browsers. Defaults to ``config.batch.MAX_WORKERS``
            and is clamped to ``config.batch.WORKER_LIMIT``.
        allow_private_hosts: Allow loopback/private targets.
        on_result: Called with each result as it completes. Must be thread safe.

    Returns:
        One result dict per URL, in the order the URLs were given.
    """
    url_list = [u for u in urls if u and u.strip()]
    if not url_list:
        return []

    requested = config.batch.MAX_WORKERS if workers is None else int(workers)
    worker_count = max(1, min(requested, config.batch.WORKER_LIMIT, len(url_list)))
    groups = _partition(url_list, worker_count)
    pool = list(proxies) if proxies else []

    logger.info(f"Batch solving {len(url_list)} URL(s) across {len(groups)} worker(s)")

    ordered: dict[str, dict[str, Any]] = {}

    def run_group(index: int, group: list[str]) -> list[dict[str, Any]]:
        worker_proxy = pool[index % len(pool)] if pool else proxy
        alap = AlapAlap(
            proxy=worker_proxy,
            headless=headless,
            timeout=timeout,
            allow_private_hosts=allow_private_hosts,
        )
        try:
            return alap.solve_many(
                group,
                invisible,
                retries=retries,
                timeout=timeout,
                on_result=on_result,
            )
        finally:
            alap.close()

    if len(groups) == 1:
        for result in run_group(0, groups[0]):
            ordered[result["url"]] = result
    else:
        with ThreadPoolExecutor(max_workers=len(groups)) as executor:
            futures = {
                executor.submit(run_group, index, group): group
                for index, group in enumerate(groups)
            }
            for future in as_completed(futures):
                try:
                    for result in future.result():
                        ordered[result["url"]] = result
                except Exception as exc:  # noqa: BLE001 - record, do not abort
                    logger.error(f"Batch worker crashed: {exc}")
                    for url in futures[future]:
                        ordered.setdefault(
                            url, {**SolveOutcome.fail(str(exc)).to_dict(), "url": url}
                        )

    return [
        ordered.get(url, {**SolveOutcome.fail("Not processed").to_dict(), "url": url})
        for url in url_list
    ]
