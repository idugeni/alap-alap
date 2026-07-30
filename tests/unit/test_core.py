"""Unit tests for the AlapAlap facade, retry policy and batch solving.

A fake solver stands in for Camoufox so none of these tests start a browser.
"""

from unittest.mock import Mock, patch

import pytest

from src.core import AlapAlap, classify_error, compute_backoff, solve_batch
from src.core.main import _partition

VALID_SITEKEY = "0x4AAAAAAAQV1p8gT2jN3m4"


class FakeSolver:
    """Stand-in for CaptchaSolver that never launches a browser."""

    #: Solves succeed when the URL contains this marker.
    SUCCESS_MARKER = "good"

    def __init__(self, proxy=None, headless=True, timeout=None):
        self.proxy = proxy
        self.headless = headless
        self.timeout = timeout
        self.is_running = False
        self.calls = 0

    def start(self):
        self.is_running = True

    def stop(self):
        self.is_running = False

    def solve(self, url, sitekey, invisible=True, timeout=None):
        self.calls += 1
        return f"token-{sitekey[-4:]}" if self.SUCCESS_MARKER in url else None


@pytest.fixture
def fake_solver():
    """Patch CaptchaSolver everywhere the core module uses it."""
    with patch("src.core.main.CaptchaSolver", FakeSolver):
        yield


@pytest.fixture
def no_sleep():
    """Skip retry backoff waits."""
    with patch("src.core.main.time.sleep", lambda _s: None):
        yield


class TestLifecycle:
    """Browser start and stop."""

    def test_context_manager_starts_the_solver(self, fake_solver):
        with AlapAlap() as alap:
            assert alap.solver is not None
            assert alap.solver.is_running is True

    def test_context_manager_stops_the_solver(self, fake_solver):
        with AlapAlap() as alap:
            solver = alap.solver
        assert solver.is_running is False
        assert alap.solver is None

    def test_solve_works_without_a_with_block(self, fake_solver):
        # The old implementation raised AttributeError on solver=None.
        alap = AlapAlap()
        alap.detector.detect = Mock(return_value=VALID_SITEKEY)
        try:
            result = alap.solve("https://good.example.com/login")
            assert result["success"] is True
        finally:
            alap.close()

    def test_start_is_idempotent(self, fake_solver):
        alap = AlapAlap()
        alap.start()
        first = alap.solver
        alap.start()
        assert alap.solver is first
        alap.close()

    def test_close_is_safe_to_call_twice(self, fake_solver):
        alap = AlapAlap()
        alap.start()
        alap.close()
        alap.close()

    def test_proxy_reaches_the_solver(self, fake_solver):
        alap = AlapAlap(proxy="1.2.3.4:8080")
        alap.start()
        assert alap.solver.proxy == "1.2.3.4:8080"
        assert alap.detector.proxy_info is not None
        alap.close()


class TestSolve:
    """The solve result contract."""

    def test_successful_solve(self, fake_solver):
        with AlapAlap() as alap:
            alap.detector.detect = Mock(return_value=VALID_SITEKEY)
            result = alap.solve("https://good.example.com/login")
        assert result["success"] is True
        assert result["token"].startswith("token-")
        assert result["sitekey"] == VALID_SITEKEY
        assert result["error"] is None
        assert result["time"] >= 0
        assert result["attempts"] == 1

    def test_missing_sitekey_is_reported(self, fake_solver):
        with AlapAlap() as alap:
            alap.detector.detect = Mock(return_value=None)
            result = alap.solve("https://example.com/login")
        assert result["success"] is False
        assert result["token"] is None
        assert result["sitekey"] is None
        assert "sitekey" in result["error"].lower()

    def test_result_keys_are_stable(self, fake_solver):
        with AlapAlap() as alap:
            alap.detector.detect = Mock(return_value=VALID_SITEKEY)
            result = alap.solve("https://good.example.com/")
        assert set(result) == {"success", "token", "sitekey", "error", "time", "attempts"}

    def test_solve_with_sitekey_skips_detection(self, fake_solver):
        with AlapAlap() as alap:
            alap.detector.detect = Mock(side_effect=AssertionError("should not detect"))
            result = alap.solve_with_sitekey("https://good.example.com/", VALID_SITEKEY)
        assert result["success"] is True

    def test_retries_are_attempted(self, fake_solver, no_sleep):
        with AlapAlap() as alap:
            result = alap.solve_with_sitekey("https://bad.example.com/", VALID_SITEKEY, retries=3)
        assert result["success"] is False
        assert result["attempts"] == 3

    @pytest.mark.parametrize("retries", [0, -1])
    def test_non_positive_retries_means_one_attempt(self, fake_solver, no_sleep, retries):
        with AlapAlap() as alap:
            result = alap.solve_with_sitekey(
                "https://bad.example.com/", VALID_SITEKEY, retries=retries
            )
        assert result["attempts"] == 1

    def test_solver_exception_becomes_a_failed_result(self, fake_solver, no_sleep):
        with AlapAlap() as alap:
            alap.solver.solve = Mock(side_effect=RuntimeError("browser exploded"))
            result = alap.solve_with_sitekey("https://x.example.com/", VALID_SITEKEY)
        assert result["success"] is False
        assert "browser exploded" in result["error"]


class TestBackoff:
    """Retry delay policy."""

    def test_delay_grows_with_the_attempt(self):
        first = compute_backoff(0, "boom", jitter_pct=0)
        second = compute_backoff(2, "boom", jitter_pct=0)
        assert second > first

    def test_delay_is_capped(self):
        assert compute_backoff(99, "boom", jitter_pct=0) <= 30.0

    def test_rate_limit_uses_the_flat_delay(self):
        assert compute_backoff(0, "HTTP 429 rate limit", jitter_pct=0) == 5.0

    def test_jitter_varies_the_delay(self):
        values = {compute_backoff(1, "boom", jitter_pct=0.5) for _ in range(20)}
        assert len(values) > 1

    def test_never_negative(self):
        assert compute_backoff(0, "boom", jitter_pct=1.0) >= 0


class TestClassifyError:
    """Error bucketing."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("HTTP 429 too many requests", "rate_limit"),
            ("read timeout after 30s", "timeout"),
            ("Could not detect sitekey", "sitekey"),
            ("proxy refused the connection", "proxy"),
            ("camoufox failed to launch", "browser"),
            ("something else", "other"),
            (None, "unknown"),
            ("", "unknown"),
        ],
    )
    def test_buckets(self, text, expected):
        assert classify_error(text) == expected


class TestPartition:
    """URL distribution across workers."""

    def test_splits_round_robin(self):
        groups = _partition(["a", "b", "c", "d"], 2)
        assert groups == [["a", "c"], ["b", "d"]]

    def test_never_returns_empty_groups(self):
        groups = _partition(["a"], 5)
        assert groups == [["a"]]

    def test_single_bucket(self):
        assert _partition(["a", "b"], 1) == [["a", "b"]]


class TestSolveMany:
    """Sequential batch through one browser."""

    def test_results_have_urls(self, fake_solver, no_sleep):
        with AlapAlap() as alap:
            alap.detector.detect = Mock(return_value=VALID_SITEKEY)
            results = alap.solve_many(["https://good.a.com/", "https://bad.b.com/"])
        assert [r["url"] for r in results] == ["https://good.a.com/", "https://bad.b.com/"]
        assert results[0]["success"] is True
        assert results[1]["success"] is False

    def test_on_result_callback_fires(self, fake_solver, no_sleep):
        seen = []
        with AlapAlap() as alap:
            alap.detector.detect = Mock(return_value=VALID_SITEKEY)
            alap.solve_many(["https://good.a.com/", "https://good.b.com/"], on_result=seen.append)
        assert len(seen) == 2

    def test_browser_is_reused(self, fake_solver, no_sleep):
        with AlapAlap() as alap:
            alap.detector.detect = Mock(return_value=VALID_SITEKEY)
            solver = alap.solver
            alap.solve_many(["https://good.a.com/", "https://good.b.com/"])
            # Same solver object handled both URLs.
            assert alap.solver is solver
            assert solver.calls == 2


class TestSolveBatch:
    """Parallel batch across worker browsers."""

    def test_input_order_is_preserved(self, no_sleep):
        urls = [f"https://good.{i}.com/" for i in range(6)]

        def fake_solve(self, url, invisible=True, retries=1, timeout=None):
            return {
                "success": True,
                "token": "t",
                "sitekey": VALID_SITEKEY,
                "error": None,
                "time": 0.1,
                "attempts": 1,
            }

        with patch.object(AlapAlap, "solve", fake_solve), patch.object(AlapAlap, "close"):
            results = solve_batch(urls, workers=3)

        assert [r["url"] for r in results] == urls
        assert all(r["success"] for r in results)

    def test_empty_input_returns_empty(self):
        assert solve_batch([]) == []

    def test_blank_urls_are_dropped(self):
        assert solve_batch(["", "   "]) == []

    def test_worker_crash_does_not_lose_urls(self, no_sleep):
        urls = ["https://a.com/", "https://b.com/"]

        with patch.object(AlapAlap, "solve", side_effect=RuntimeError("worker died")):
            results = solve_batch(urls, workers=2)

        assert len(results) == 2
        assert all(r["success"] is False for r in results)
        assert [r["url"] for r in results] == urls
