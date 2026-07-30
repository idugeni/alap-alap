"""Unit tests for the solver pool.

The pool exists so the API stops launching a browser per request, and because
Playwright's sync API pins a browser to the thread that created it. These tests
assert both properties with a fake browser, so nothing here starts Camoufox.
"""

import dataclasses
import threading
import time

import pytest

from src.api.pool import QueueFullError, SolveJob, SolverPool
from src.config import ApiConfig
from src.models import SolveRequest

VALID_SITEKEY = "0x4AAAAAAAQV1p8gT2jN3m4"


class FakeAlap:
    """Records launches and threads so tests can assert on pooling."""

    launches: list[str | None] = []
    threads: set[int] = set()

    def __init__(self, proxy=None, headless=True, timeout=None, allow_private_hosts=True):
        self.proxy = proxy
        self.headless = headless
        self.timeout = timeout
        self.closed = False
        self.solves = 0

    def start(self):
        FakeAlap.launches.append(self.proxy)
        FakeAlap.threads.add(threading.get_ident())

    def close(self):
        self.closed = True

    def solve(self, url, invisible=True, retries=1, timeout=None):
        self.solves += 1
        return {
            "success": "fail" not in url,
            "token": None if "fail" in url else "tok-123",
            "sitekey": VALID_SITEKEY,
            "error": "Solver failed" if "fail" in url else None,
            "time": 0.01,
            "attempts": retries,
        }

    def solve_with_sitekey(self, url, sitekey, invisible=True, retries=1, timeout=None):
        return self.solve(url, invisible=invisible, retries=retries, timeout=timeout)


class ExplodingAlap(FakeAlap):
    """Fails inside solve, to exercise error handling."""

    def solve(self, url, **kwargs):
        raise RuntimeError("browser exploded")


@pytest.fixture(autouse=True)
def _reset_fake():
    FakeAlap.launches = []
    FakeAlap.threads = set()
    yield


def build_pool(alap_factory=FakeAlap, **api_overrides) -> SolverPool:
    """A pool with short waits so tests stay fast."""
    defaults = {
        "MAX_CONCURRENT_SOLVES": 2,
        "QUEUE_MAX_SIZE": 16,
        "CONCURRENCY_WAIT_S": 5.0,
        "SOLVE_TIMEOUT_S": 5.0,
        "JOB_TTL_S": 600.0,
    }
    defaults.update(api_overrides)
    return SolverPool(
        dataclasses.replace(ApiConfig(), **defaults),
        alap_factory=alap_factory,
    )


@pytest.fixture
def pool():
    instance = build_pool()
    yield instance
    instance.shutdown(timeout=5)


class TestLazyStart:
    """Constructing a pool must not start browsers."""

    def test_no_threads_before_first_submit(self):
        instance = build_pool()
        try:
            assert instance.stats()["started"] is False
            assert FakeAlap.launches == []
        finally:
            instance.shutdown(timeout=5)

    def test_threads_start_on_first_submit(self, pool):
        pool.solve(SolveRequest(url="https://a.com/1"))
        assert pool.stats()["started"] is True


class TestBrowserReuse:
    """The whole point of the pool."""

    def test_many_solves_share_few_browsers(self, pool):
        for index in range(8):
            pool.solve(SolveRequest(url=f"https://a.com/{index}"))
        # At most one browser per worker, not one per solve.
        assert len(FakeAlap.launches) <= 2

    def test_each_browser_stays_on_one_thread(self, pool):
        # Playwright's sync API requires this; a browser shared across threads
        # would fail at runtime in ways unit tests would not catch.
        for index in range(6):
            pool.solve(SolveRequest(url=f"https://a.com/{index}"))
        assert len(FakeAlap.threads) <= 2

    def test_changing_proxy_relaunches(self, pool):
        pool.solve(SolveRequest(url="https://a.com/1"))
        first = len(FakeAlap.launches)
        pool.solve(SolveRequest(url="https://a.com/2", proxy="1.2.3.4:8080"))
        assert len(FakeAlap.launches) > first
        assert "1.2.3.4:8080" in FakeAlap.launches

    def test_same_proxy_does_not_relaunch(self):
        instance = build_pool(MAX_CONCURRENT_SOLVES=1)
        try:
            instance.solve(SolveRequest(url="https://a.com/1", proxy="1.2.3.4:8080"))
            after_first = len(FakeAlap.launches)
            instance.solve(SolveRequest(url="https://a.com/2", proxy="1.2.3.4:8080"))
            assert len(FakeAlap.launches) == after_first
        finally:
            instance.shutdown(timeout=5)

    def test_pool_disabled_relaunches_every_time(self):
        instance = build_pool(MAX_CONCURRENT_SOLVES=1, POOL_ENABLED=False)
        try:
            for index in range(3):
                instance.solve(SolveRequest(url=f"https://a.com/{index}"))
            assert len(FakeAlap.launches) == 3
        finally:
            instance.shutdown(timeout=5)

    def test_recycling_after_n_solves(self):
        instance = build_pool(MAX_CONCURRENT_SOLVES=1, POOL_MAX_SOLVES_PER_BROWSER=2)
        try:
            for index in range(5):
                instance.solve(SolveRequest(url=f"https://a.com/{index}"))
            # Recycled at least twice across five solves.
            assert len(FakeAlap.launches) >= 2
        finally:
            instance.shutdown(timeout=5)


class TestJobLifecycle:
    """Submit, poll, complete."""

    def test_submit_returns_immediately_as_queued(self, pool):
        job = pool.submit(SolveRequest(url="https://a.com/1"))
        assert isinstance(job, SolveJob)
        assert job.id
        assert job.status in ("queued", "running", "done")

    def test_job_reaches_done(self, pool):
        job = pool.submit(SolveRequest(url="https://a.com/1"))
        assert job.wait(10) is True
        assert job.status == "done"
        assert job.result["success"] is True

    def test_solve_waits_for_the_result(self, pool):
        job = pool.solve(SolveRequest(url="https://a.com/1"))
        assert job.finished is True
        assert job.result["token"] == "tok-123"

    def test_failed_solve_is_done_not_error(self, pool):
        # A solver that ran and produced no token is a result, not a crash.
        job = pool.solve(SolveRequest(url="https://a.com/fail"))
        assert job.status == "done"
        assert job.result["success"] is False

    def test_crashing_browser_marks_the_job_error(self):
        instance = build_pool(alap_factory=ExplodingAlap)
        try:
            job = instance.solve(SolveRequest(url="https://a.com/1"))
            assert job.status == "error"
            assert "exploded" in job.error
        finally:
            instance.shutdown(timeout=5)

    def test_pool_survives_a_crash_and_serves_the_next_job(self):
        calls = {"n": 0}

        class FlakyAlap(FakeAlap):
            def solve(self, url, **kwargs):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise RuntimeError("first one dies")
                return super().solve(url, **kwargs)

        instance = build_pool(alap_factory=FlakyAlap, MAX_CONCURRENT_SOLVES=1)
        try:
            first = instance.solve(SolveRequest(url="https://a.com/1"))
            second = instance.solve(SolveRequest(url="https://a.com/2"))
            assert first.status == "error"
            assert second.status == "done"
        finally:
            instance.shutdown(timeout=5)

    def test_sitekey_is_forwarded(self, pool):
        job = pool.solve(SolveRequest(url="https://a.com/1", sitekey=VALID_SITEKEY))
        assert job.result["sitekey"] == VALID_SITEKEY

    def test_get_by_id(self, pool):
        job = pool.solve(SolveRequest(url="https://a.com/1"))
        assert pool.get(job.id) is job

    def test_get_unknown_id(self, pool):
        assert pool.get("nope") is None

    def test_list_is_newest_first(self, pool):
        first = pool.solve(SolveRequest(url="https://a.com/1"))
        time.sleep(0.01)
        second = pool.solve(SolveRequest(url="https://a.com/2"))
        listed = pool.list_jobs()
        assert listed[0].id == second.id
        assert first.id in {job.id for job in listed}

    def test_timings_are_recorded(self, pool):
        job = pool.solve(SolveRequest(url="https://a.com/1"))
        assert job.queue_time >= 0
        assert job.run_time >= 0
        assert job.finished_at is not None


class TestJobSerialization:
    """to_dict shapes the API response."""

    def test_done_job_includes_the_result(self, pool):
        job = pool.solve(SolveRequest(url="https://a.com/1"))
        payload = job.to_dict()
        assert payload["job_id"] == job.id
        assert payload["status"] == "done"
        assert payload["token"] == "tok-123"
        assert payload["url"] == "https://a.com/1"

    def test_token_can_be_withheld(self, pool):
        job = pool.solve(SolveRequest(url="https://a.com/1"))
        payload = job.to_dict(include_token=False)
        assert payload["token"] is None
        assert payload["token_withheld"] is True

    def test_queued_job_reports_unknown_success(self, pool):
        job = SolveJob(id="x", request=SolveRequest(url="https://a.com/1"))
        assert job.to_dict()["success"] is None

    def test_error_job_reports_the_message(self):
        job = SolveJob(id="x", request=SolveRequest(url="https://a.com/1"))
        job.status = "error"
        job.error = "boom"
        payload = job.to_dict()
        assert payload["success"] is False
        assert payload["error"] == "boom"


class TestQueueLimits:
    """Backpressure instead of an unbounded backlog."""

    def test_full_queue_raises(self):
        class SlowAlap(FakeAlap):
            def solve(self, url, **kwargs):
                time.sleep(1.0)
                return super().solve(url, **kwargs)

        instance = build_pool(alap_factory=SlowAlap, MAX_CONCURRENT_SOLVES=1, QUEUE_MAX_SIZE=2)
        try:
            with pytest.raises(QueueFullError):
                for index in range(30):
                    instance.submit(SolveRequest(url=f"https://a.com/{index}"))
        finally:
            instance.shutdown(timeout=10)

    def test_submit_after_shutdown_raises(self):
        instance = build_pool()
        instance.shutdown(timeout=5)
        with pytest.raises(QueueFullError):
            instance.submit(SolveRequest(url="https://a.com/1"))


class TestJobEviction:
    """Finished jobs must not accumulate forever."""

    def test_expired_jobs_are_dropped(self):
        instance = build_pool(JOB_TTL_S=0.05, MAX_CONCURRENT_SOLVES=1)
        try:
            old = instance.solve(SolveRequest(url="https://a.com/1"))
            time.sleep(0.1)
            # Any submission triggers a sweep.
            instance.solve(SolveRequest(url="https://a.com/2"))
            assert instance.get(old.id) is None
        finally:
            instance.shutdown(timeout=5)

    def test_hard_cap_is_enforced(self):
        instance = build_pool(JOB_MAX_RETAINED=3, MAX_CONCURRENT_SOLVES=1)
        try:
            for index in range(8):
                instance.solve(SolveRequest(url=f"https://a.com/{index}"))
            assert instance.stats()["retained_jobs"] <= 3
        finally:
            instance.shutdown(timeout=5)


class TestStats:
    """Reported pool state."""

    def test_counts_successes_and_failures(self, pool):
        pool.solve(SolveRequest(url="https://a.com/ok"))
        pool.solve(SolveRequest(url="https://a.com/fail"))
        stats = pool.stats()
        assert stats["completed"] == 1
        assert stats["failed"] == 1

    def test_reports_worker_count(self, pool):
        assert pool.stats()["workers"] == 2

    def test_reports_launches(self, pool):
        pool.solve(SolveRequest(url="https://a.com/1"))
        assert pool.stats()["browser_launches"] >= 1


class TestShutdown:
    """Teardown."""

    def test_shutdown_stops_workers(
        self,
    ):
        instance = build_pool()
        instance.solve(SolveRequest(url="https://a.com/1"))
        instance.shutdown(timeout=10)
        assert instance.stats()["started"] is False

    def test_shutdown_is_idempotent(self):
        instance = build_pool()
        instance.shutdown(timeout=5)
        instance.shutdown(timeout=5)

    def test_context_manager_shuts_down(self):
        with build_pool() as instance:
            instance.solve(SolveRequest(url="https://a.com/1"))
        assert instance.stats()["started"] is False
