"""
End-to-end tests against a real browser and a real Turnstile widget.

These use Cloudflare's officially documented Turnstile testing sitekeys, so they
verify the whole solve path without depending on any third-party site: the page
itself is served by the solver's own request interception.

Deselected by default because they launch Camoufox. Run them with::

    pytest -m integration tests/integration/test_real_solve.py -v
"""

import time

import pytest

from src.solver import CaptchaSolver

#: https://developers.cloudflare.com/turnstile/troubleshooting/testing/
SITEKEY_ALWAYS_PASSES = "1x00000000000000000000AA"
SITEKEY_ALWAYS_BLOCKS = "2x00000000000000000000AB"

#: Deliberately carries a query string: the previous implementation appended a
#: slash to the raw URL, which corrupted it and broke route interception.
TARGET_WITH_QUERY = "https://example.com/login?next=1&a=2"


@pytest.mark.integration
class TestRealSolve:
    """The full solve path, with a real browser."""

    def test_invisible_solve_returns_a_token(self):
        with CaptchaSolver(headless=True, timeout=120) as solver:
            token = solver.solve(TARGET_WITH_QUERY, SITEKEY_ALWAYS_PASSES, invisible=True)

        assert token, "the always-passes sitekey must yield a token"

    def test_route_interception_survives_a_query_string(self):
        # A token proves interception matched: without it, page.goto would have
        # loaded the real example.com and no widget would ever render.
        with CaptchaSolver(headless=True, timeout=120) as solver:
            token = solver.solve(TARGET_WITH_QUERY, SITEKEY_ALWAYS_PASSES, invisible=True)

        assert token
        assert CaptchaSolver._normalize_url(TARGET_WITH_QUERY) == TARGET_WITH_QUERY

    def test_blocking_sitekey_fails_without_hanging(self):
        budget = 30.0
        started = time.time()

        with CaptchaSolver(headless=True, timeout=budget) as solver:
            token = solver.solve(TARGET_WITH_QUERY, SITEKEY_ALWAYS_BLOCKS, invisible=True)

        elapsed = time.time() - started
        assert token is None
        # The deadline must actually bound the attempt, with room for teardown.
        assert elapsed < budget * 2, f"solve overran its budget: {elapsed:.1f}s"

    def test_browser_lifecycle_is_reusable(self):
        # One browser, two solves: this is what solve_many() relies on.
        with CaptchaSolver(headless=True, timeout=120) as solver:
            first = solver.solve(TARGET_WITH_QUERY, SITEKEY_ALWAYS_PASSES, invisible=True)
            second = solver.solve(
                "https://example.org/signup", SITEKEY_ALWAYS_PASSES, invisible=True
            )

        assert first
        assert second


@pytest.mark.integration
class TestRealBrowserLifecycle:
    """Start and stop semantics against real Camoufox."""

    def test_start_then_stop(self):
        solver = CaptchaSolver(headless=True)
        solver.start()
        try:
            assert solver.is_running is True
        finally:
            solver.stop()
        assert solver.is_running is False

    def test_start_is_idempotent(self):
        solver = CaptchaSolver(headless=True)
        solver.start()
        try:
            browser = solver.browser
            solver.start()
            assert solver.browser is browser
        finally:
            solver.stop()

    def test_stop_is_safe_twice(self):
        solver = CaptchaSolver(headless=True)
        solver.start()
        solver.stop()
        solver.stop()
