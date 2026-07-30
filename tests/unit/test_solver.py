"""Unit tests for CaptchaSolver."""

import dataclasses
import time

import pytest

from src.errors import BrowserNotStartedError, ProxyError
from src.solver import CaptchaSolver


class TestCaptchaSolver:
    """Test CaptchaSolver class."""

    def test_init(self):
        """Test solver initialization."""
        solver = CaptchaSolver()
        assert solver.proxy is None
        assert solver.headless is True
        assert solver.browser is None

    def test_init_with_proxy(self):
        """Test solver initialization with proxy."""
        proxy = "user:pass@host.example:8080"
        solver = CaptchaSolver(proxy=proxy, headless=False)
        assert solver.proxy == proxy
        assert solver.headless is False
        # The proxy must actually reach Camoufox, not just be stored.
        kwargs = solver._camoufox_kwargs()
        assert kwargs["proxy"]["server"] == "http://host.example:8080"
        assert kwargs["proxy"]["username"] == "user"
        assert kwargs["proxy"]["password"] == "pass"

    def test_init_with_invalid_proxy_raises(self):
        """An unparseable proxy fails loudly instead of being ignored."""
        with pytest.raises(ProxyError):
            CaptchaSolver(proxy="user:pass@host:not-a-port")

    def test_get_mouse_path(self):
        """Test mouse path calculation."""
        solver = CaptchaSolver()

        path = solver._get_mouse_path(0, 0, 100, 100)

        assert isinstance(path, list)
        assert len(path) > 0
        assert path[-1] == (100, 100) or (
            abs(path[-1][0] - 100) <= 3 and abs(path[-1][1] - 100) <= 3
        )

    def test_get_mouse_path_same_point(self):
        """Test mouse path when start equals end."""
        solver = CaptchaSolver()

        path = solver._get_mouse_path(50, 50, 50, 50)

        assert isinstance(path, list)
        assert len(path) == 0

    def test_build_page_data(self):
        """Test page data building."""
        solver = CaptchaSolver()

        sitekey = "0x4AAAAAAAQV1p8gT2jN3m4"
        page_data = solver._build_page_data(sitekey)

        assert sitekey in page_data
        assert "cf-turnstile" in page_data


class TestUrlNormalization:
    """Regression tests for the URL handling bug.

    The old implementation appended "/" to the raw URL string, which corrupted
    query strings (``?next=1`` became ``?next=1/``) and changed the origin the
    widget was rendered against.
    """

    def test_bare_host_gets_a_path(self):
        assert CaptchaSolver._normalize_url("https://site.com") == "https://site.com/"

    def test_query_string_is_preserved(self):
        url = "https://site.com/login?next=1&a=2"
        assert CaptchaSolver._normalize_url(url) == url

    def test_query_string_does_not_get_a_trailing_slash(self):
        result = CaptchaSolver._normalize_url("https://site.com/login?next=1")
        assert not result.endswith("/")
        assert result.endswith("?next=1")

    def test_existing_trailing_slash_is_kept(self):
        url = "https://site.com/login/"
        assert CaptchaSolver._normalize_url(url) == url

    def test_fragment_is_preserved(self):
        url = "https://site.com/x?a=1#frag"
        assert CaptchaSolver._normalize_url(url) == url

    def test_whitespace_is_trimmed(self):
        assert CaptchaSolver._normalize_url("  https://site.com/a  ") == "https://site.com/a"


class TestMousePathGuards:
    """The path builder must always terminate."""

    def test_long_distance_stays_within_the_cap(self):
        solver = CaptchaSolver()
        path = solver._get_mouse_path(0, 0, 10_000_000, 10_000_000)
        assert len(path) <= solver._mouse.PATH_MAX_STEPS

    def test_capped_path_still_lands_on_the_target(self):
        solver = CaptchaSolver()
        solver._mouse = type(solver._mouse)(PATH_MAX_STEPS=5)
        path = solver._get_mouse_path(0, 0, 5000, 5000)
        assert path[-1] == (5000.0, 5000.0)

    def test_negative_direction_converges(self):
        solver = CaptchaSolver()
        path = solver._get_mouse_path(500, 500, 10, 10)
        assert abs(path[-1][0] - 10) <= solver._mouse.MOVE_THRESHOLD_PX
        assert abs(path[-1][1] - 10) <= solver._mouse.MOVE_THRESHOLD_PX


class TestSolverLifecycle:
    """Guards around using the solver before the browser is up."""

    def test_solve_without_start_raises(self):
        solver = CaptchaSolver()
        with pytest.raises(BrowserNotStartedError):
            solver.solve("https://example.com", "0x4AAAAAAAQV1p8gT2jN3m4")

    def test_is_running_is_false_before_start(self):
        assert CaptchaSolver().is_running is False

    def test_stop_without_start_is_safe(self):
        CaptchaSolver().stop()

    def test_timeout_defaults_to_config(self):
        from src.config import config

        assert CaptchaSolver().timeout == config.solver.SOLVE_TIMEOUT_S

    def test_timeout_can_be_overridden(self):
        assert CaptchaSolver(timeout=12.5).timeout == 12.5


class TestDeadline:
    """The wall-clock budget that stops solve loops from running forever."""

    def test_zero_budget_never_expires(self):
        from src.solver.captcha_solver import _Deadline

        deadline = _Deadline(0)
        assert deadline.unlimited is True
        assert deadline.expired is False

    def test_elapsed_budget_expires(self):
        import time

        from src.solver.captcha_solver import _Deadline

        deadline = _Deadline(0.01)
        time.sleep(0.05)
        assert deadline.expired is True

    def test_safe_randint_tolerates_a_reversed_range(self):
        from src.solver.captcha_solver import _safe_randint

        assert 2 <= _safe_randint(8, 2) <= 8
        assert _safe_randint(5, 5) == 5


class FakeElement:
    """Stand-in for a Playwright element handle."""

    def __init__(self, *, value=None, box=None, frame=None, tag="input"):
        self._value = value
        self._box = box or {"x": 10.0, "y": 20.0, "width": 30.0, "height": 30.0}
        self._frame = frame
        self.tag = tag

    def get_attribute(self, name):
        return self._value if name == "value" else None

    def bounding_box(self):
        return self._box

    def content_frame(self):
        return self._frame


class FakeMouse:
    """Records mouse activity."""

    def __init__(self):
        self.moves = 0
        self.clicks = []

    def move(self, x, y):
        self.moves += 1

    def click(self, x, y):
        self.clicks.append((x, y))


class FakeFrame:
    """Stand-in for an iframe content frame."""

    def __init__(self, checkbox=None):
        self.checkbox = checkbox

    def query_selector(self, _selector):
        return self.checkbox


class FakePage:
    """
    Stand-in for a Playwright page.

    ``selectors`` maps a CSS selector to the element returned for it, which is
    what lets these tests assert *which* selector the solver reaches for.
    """

    def __init__(self, selectors=None, token_after=None, window=(800, 600)):
        self.selectors = selectors or {}
        self.token_after = token_after
        self.window = window
        self.mouse = FakeMouse()
        self.queried = []
        self.token_checks = 0

    def query_selector(self, selector):
        self.queried.append(selector)
        if selector == "[name=cf-turnstile-response]":
            self.token_checks += 1
            if self.token_after is not None and self.token_checks >= self.token_after:
                return FakeElement(value="solved-token")
            return None
        return self.selectors.get(selector)

    def evaluate(self, script, *_args):
        if "innerWidth" in script:
            return self.window[0]
        if "innerHeight" in script:
            return self.window[1]
        return None


def instant_solver(**overrides):
    """A solver whose delays and attempt counts keep tests fast."""
    solver = CaptchaSolver()
    solver._solver = dataclasses.replace(
        solver._solver,
        INVISIBLE_SOLVE_MAX_ATTEMPTS=overrides.pop("INVISIBLE_SOLVE_MAX_ATTEMPTS", 3),
        TOKEN_WAIT_MAX_ATTEMPTS=overrides.pop("TOKEN_WAIT_MAX_ATTEMPTS", 3),
        IFRAME_WAIT_MAX_ATTEMPTS=overrides.pop("IFRAME_WAIT_MAX_ATTEMPTS", 2),
        IFRAME_POLL_INTERVAL=0.0,
        CHECKBOX_WAIT_MAX_ATTEMPTS=overrides.pop("CHECKBOX_WAIT_MAX_ATTEMPTS", 2),
        CHECKBOX_POLL_INTERVAL=0.0,
        **overrides,
    )
    # Keep the mouse path tiny so the loops finish immediately.
    solver._mouse = dataclasses.replace(solver._mouse, MOVE_THRESHOLD_PX=10_000)
    return solver


class TestInvisibleSolve:
    """The invisible-mode loop."""

    def test_token_available_immediately(self):
        solver = instant_solver()
        page = FakePage(token_after=1)
        assert solver._solve_invisible(page, 800, 600) == "solved-token"

    def test_token_appears_after_some_polling(self):
        solver = instant_solver()
        page = FakePage(token_after=3)
        assert solver._solve_invisible(page, 800, 600) == "solved-token"
        # The loop kept checking until the widget produced a token.
        assert page.token_checks == 3

    def test_mouse_actually_moves(self):
        # instant_solver() suppresses movement for speed, so use real settings.
        solver = CaptchaSolver()
        solver._solver = dataclasses.replace(solver._solver, INVISIBLE_SOLVE_MAX_ATTEMPTS=1)
        page = FakePage(token_after=None)
        solver._solve_invisible(page, 200, 200)
        assert page.mouse.moves > 0

    def test_returns_none_when_attempts_run_out(self):
        solver = instant_solver()
        page = FakePage(token_after=None)
        assert solver._solve_invisible(page, 800, 600) is None

    def test_expired_deadline_stops_the_loop(self):
        from src.solver.captcha_solver import _Deadline

        solver = instant_solver(INVISIBLE_SOLVE_MAX_ATTEMPTS=10_000)
        page = FakePage(token_after=None)
        deadline = _Deadline(0.001)
        time.sleep(0.01)
        assert solver._solve_invisible(page, 800, 600, deadline) is None
        # Only the pre-loop check ran, not thousands of attempts.
        assert page.token_checks == 1

    def test_zero_window_does_not_raise(self):
        solver = instant_solver()
        assert solver._solve_invisible(FakePage(token_after=None), 0, 0) is None


class TestVisibleSolve:
    """The visible-mode loop."""

    def _page_with_widget(self, token_after=2):
        checkbox = FakeElement(box={"x": 5.0, "y": 5.0, "width": 20.0, "height": 20.0})
        iframe = FakeElement(
            box={"x": 100.0, "y": 100.0, "width": 300.0, "height": 65.0},
            frame=FakeFrame(checkbox),
        )
        return FakePage(
            selectors={'iframe[src*="challenges.cloudflare.com"]': iframe},
            token_after=token_after,
        )

    def test_cloudflare_selector_is_tried_first(self):
        # The old code polled the generic "iframe" selector and could grab an
        # unrelated embed that happened to appear earlier in the document.
        solver = instant_solver()
        page = self._page_with_widget()
        solver._solve_visible(page, 800, 600)
        assert page.queried[0] == 'iframe[src*="challenges.cloudflare.com"]'

    def test_generic_selector_is_the_fallback(self):
        solver = instant_solver()
        checkbox = FakeElement(box={"x": 5.0, "y": 5.0, "width": 20.0, "height": 20.0})
        iframe = FakeElement(
            box={"x": 0.0, "y": 0.0, "width": 300.0, "height": 65.0},
            frame=FakeFrame(checkbox),
        )
        page = FakePage(selectors={"iframe": iframe}, token_after=2)
        assert solver._solve_visible(page, 800, 600) == "solved-token"
        assert 'iframe[src*="challenges.cloudflare.com"]' in page.queried

    def test_successful_solve_clicks_the_checkbox(self):
        solver = instant_solver()
        page = self._page_with_widget()
        assert solver._solve_visible(page, 800, 600) == "solved-token"
        assert len(page.mouse.clicks) == 1

    def test_missing_iframe_returns_none(self):
        solver = instant_solver()
        assert solver._solve_visible(FakePage(), 800, 600) is None

    def test_missing_content_frame_returns_none(self):
        solver = instant_solver()
        iframe = FakeElement(box={"x": 0.0, "y": 0.0, "width": 300.0, "height": 65.0}, frame=None)
        page = FakePage(selectors={'iframe[src*="challenges.cloudflare.com"]': iframe})
        assert solver._solve_visible(page, 800, 600) is None

    def test_missing_checkbox_returns_none(self):
        solver = instant_solver()
        iframe = FakeElement(
            box={"x": 0.0, "y": 0.0, "width": 300.0, "height": 65.0},
            frame=FakeFrame(checkbox=None),
        )
        page = FakePage(selectors={'iframe[src*="challenges.cloudflare.com"]': iframe})
        assert solver._solve_visible(page, 800, 600) is None

    def test_tiny_checkbox_does_not_raise(self):
        # A degenerate bounding box used to be able to blow up randint.
        solver = instant_solver()
        checkbox = FakeElement(box={"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0})
        iframe = FakeElement(
            box={"x": 0.0, "y": 0.0, "width": 300.0, "height": 65.0},
            frame=FakeFrame(checkbox),
        )
        page = FakePage(
            selectors={'iframe[src*="challenges.cloudflare.com"]': iframe}, token_after=2
        )
        assert solver._solve_visible(page, 800, 600) == "solved-token"

    def test_no_token_returns_none(self):
        solver = instant_solver()
        assert self._page_with_widget(token_after=None) is not None
        assert solver._solve_visible(self._page_with_widget(token_after=None), 800, 600) is None


class TestTokenExtraction:
    """_get_token reads the hidden input, then the widget API."""

    def test_hidden_input_value_is_used(self):
        solver = CaptchaSolver()
        page = FakePage(token_after=1)
        assert solver._get_token(page) == "solved-token"

    def test_falls_back_to_the_turnstile_api(self):
        solver = CaptchaSolver()

        class ApiPage(FakePage):
            def evaluate(self, script, *_args):
                if "getResponse" in script:
                    return "api-token"
                return super().evaluate(script, *_args)

        assert solver._get_token(ApiPage()) == "api-token"

    def test_returns_none_when_nothing_is_available(self):
        assert CaptchaSolver()._get_token(FakePage()) is None

    def test_evaluate_failure_is_swallowed(self):
        solver = CaptchaSolver()

        class BrokenPage(FakePage):
            def evaluate(self, script, *_args):
                raise RuntimeError("page is gone")

        assert solver._get_token(BrokenPage()) is None
