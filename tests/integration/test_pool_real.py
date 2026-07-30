"""
End-to-end tests for the solver pool against a real browser.

The pool exists so the REST API stops paying Camoufox's startup cost on every
request. Proving that needs a real browser: a fake cannot show that one Camoufox
process genuinely serves several HTTP requests, nor that Playwright's sync API
tolerates the thread-affinity scheme the pool relies on.

Deselected by default. Run with::

    pytest -m integration tests/integration/test_pool_real.py -v
"""

import dataclasses
import time

import pytest

from src.api import create_app
from src.api.pool import SolverPool
from src.config import ApiConfig, AppConfig
from src.models import SolveRequest

#: Cloudflare's documented "always passes" Turnstile testing sitekey.
SITEKEY_ALWAYS_PASSES = "1x00000000000000000000AA"

TARGET = "https://example.com/login?next=1"


def build_app(**api_overrides):
    """A real-browser app plus its pool, so tests can shut the pool down."""
    defaults = {
        "MAX_CONCURRENT_SOLVES": 1,
        "RATE_LIMIT_REQUESTS": 1000,
        "SOLVE_TIMEOUT_S": 120.0,
        "CONCURRENCY_WAIT_S": 120.0,
        # example.com is public, so the SSRF guard is happy; the solver serves
        # the page itself through request interception.
        "ALLOW_PRIVATE_HOSTS": False,
    }
    defaults.update(api_overrides)
    api_cfg = dataclasses.replace(ApiConfig(), **defaults)
    pool = SolverPool(api_cfg)
    app = create_app(dataclasses.replace(AppConfig(), api=api_cfg), pool=pool)
    return app.test_client(), pool


@pytest.mark.integration
class TestPoolWithRealBrowser:
    """One warm browser, several requests."""

    def test_repeated_solves_launch_one_browser(self):
        client, pool = build_app()
        try:
            for _ in range(3):
                response = client.post(
                    "/solve", json={"url": TARGET, "sitekey": SITEKEY_ALWAYS_PASSES}
                )
                assert response.status_code == 200, response.get_json()
                assert response.get_json()["token"]

            stats = pool.stats()
            # Three solves, one worker, one Camoufox launch.
            assert stats["browser_launches"] == 1
            assert stats["completed"] == 3
        finally:
            pool.shutdown(timeout=60)

    def test_second_solve_is_faster_than_the_first(self):
        client, pool = build_app()
        try:
            started = time.time()
            first = client.post("/solve", json={"url": TARGET, "sitekey": SITEKEY_ALWAYS_PASSES})
            cold = time.time() - started
            assert first.status_code == 200

            started = time.time()
            second = client.post("/solve", json={"url": TARGET, "sitekey": SITEKEY_ALWAYS_PASSES})
            warm = time.time() - started
            assert second.status_code == 200

            # The warm request skips browser startup entirely.
            assert warm < cold, f"warm {warm:.1f}s was not faster than cold {cold:.1f}s"
        finally:
            pool.shutdown(timeout=60)

    def test_async_job_flow(self):
        client, pool = build_app()
        try:
            created = client.post("/jobs", json={"url": TARGET, "sitekey": SITEKEY_ALWAYS_PASSES})
            assert created.status_code == 202
            job_id = created.get_json()["job_id"]

            deadline = time.time() + 150
            body = None
            while time.time() < deadline:
                body = client.get(f"/jobs/{job_id}").get_json()
                if body["status"] in ("done", "error"):
                    break
                time.sleep(0.5)

            assert body is not None
            assert body["status"] == "done", body
            assert body["token"]
        finally:
            pool.shutdown(timeout=60)

    def test_two_workers_solve_concurrently(self):
        pool = SolverPool(
            dataclasses.replace(
                ApiConfig(),
                MAX_CONCURRENT_SOLVES=2,
                SOLVE_TIMEOUT_S=120.0,
                CONCURRENCY_WAIT_S=120.0,
            )
        )
        try:
            jobs = [
                pool.submit(SolveRequest(url=TARGET, sitekey=SITEKEY_ALWAYS_PASSES))
                for _ in range(2)
            ]
            for job in jobs:
                assert job.wait(180) is True
                assert job.status == "done", job.error
                assert job.result["success"] is True

            # Each worker owns its own browser.
            assert pool.stats()["browser_launches"] == 2
        finally:
            pool.shutdown(timeout=60)

    def test_recycling_relaunches_the_browser(self):
        pool = SolverPool(
            dataclasses.replace(
                ApiConfig(),
                MAX_CONCURRENT_SOLVES=1,
                POOL_MAX_SOLVES_PER_BROWSER=1,
                SOLVE_TIMEOUT_S=120.0,
                CONCURRENCY_WAIT_S=120.0,
            )
        )
        try:
            for _ in range(2):
                job = pool.solve(
                    SolveRequest(url=TARGET, sitekey=SITEKEY_ALWAYS_PASSES), timeout=180
                )
                assert job.status == "done", job.error

            assert pool.stats()["browser_launches"] == 2
        finally:
            pool.shutdown(timeout=60)
