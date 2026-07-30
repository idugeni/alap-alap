"""
Alap-Alap Captcha Solver

Solves Cloudflare Turnstile captchas using Camoufox for fingerprint resistance.

The solver serves its own minimal page for the target URL so the widget is
rendered against the right origin, then drives the mouse in a human-like path
until Turnstile writes a token into the response input.
"""

from __future__ import annotations

import random
import time
from typing import Any
from urllib.parse import urlparse, urlunparse

from loguru import logger

from src.config import config
from src.errors import BrowserNotStartedError, DependencyMissingError
from src.proxy import ProxyInfo, parse_proxy


class _Deadline:
    """A wall-clock budget. A budget of zero or less never expires."""

    __slots__ = ("_budget", "_start")

    def __init__(self, budget: float | None):
        self._budget = float(budget or 0.0)
        self._start = time.monotonic()

    @property
    def unlimited(self) -> bool:
        return self._budget <= 0

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self._start

    @property
    def remaining(self) -> float:
        if self.unlimited:
            return float("inf")
        return self._budget - self.elapsed

    @property
    def expired(self) -> bool:
        return not self.unlimited and self.remaining <= 0


def _safe_randint(low: int, high: int) -> int:
    """``random.randint`` that tolerates a reversed or degenerate range."""
    low, high = int(low), int(high)
    if low > high:
        low, high = high, low
    return random.randint(low, high)


class CaptchaSolver:
    """
    Solve Cloudflare Turnstile captchas.

    Uses Camoufox for anti-fingerprint browsing and intelligent
    mouse movement to bypass bot detection.

    Args:
        proxy: Proxy string (``user:pass@host:port`` or a full proxy URL),
            forwarded to the browser so solving happens from that exit IP.
        headless: Run the browser without a visible window.
        timeout: Wall-clock budget per solve in seconds. Defaults to
            ``config.solver.SOLVE_TIMEOUT_S``; zero disables the deadline.
    """

    def __init__(
        self,
        proxy: str | None = None,
        headless: bool = True,
        timeout: float | None = None,
    ):
        self.proxy = proxy
        self.proxy_info: ProxyInfo | None = parse_proxy(proxy)
        self.headless = headless
        # Camoufox hands back a Playwright browser handle whose concrete type
        # depends on how it was launched, so it stays untyped here.
        self.browser: Any = None
        self._camoufox_context: Any = None
        self._cf = config.cloudflare
        self._mouse = config.mouse
        self._solver = config.solver
        self.timeout = self._solver.SOLVE_TIMEOUT_S if timeout is None else float(timeout)

        if self.proxy_info:
            logger.debug(f"Solver using proxy {self.proxy_info.masked()}")

    # ----------------------------------------------------------------- #
    # Lifecycle
    # ----------------------------------------------------------------- #

    @property
    def is_running(self) -> bool:
        """Whether the browser is started and ready to solve."""
        return self.browser is not None

    def _camoufox_kwargs(self) -> dict:
        """Build Camoufox constructor arguments, including the proxy."""
        kwargs: dict = {"headless": self.headless}
        if self.proxy_info:
            kwargs["proxy"] = self.proxy_info.as_playwright_dict()
            # Align the spoofed locale/timezone with the proxy exit node,
            # otherwise the mismatch is itself a detection signal.
            kwargs["geoip"] = True
        return kwargs

    def start(self):
        """Start the browser."""
        if self.browser is not None:
            return self.browser

        try:
            from camoufox.sync_api import Camoufox
        except ImportError as e:
            raise DependencyMissingError(
                "Camoufox is required. Install with: pip install camoufox"
            ) from e

        self._camoufox_context = Camoufox(**self._camoufox_kwargs())
        self.browser = self._camoufox_context.__enter__()
        logger.debug("Browser started")
        return self.browser

    def stop(self):
        """Stop the browser."""
        if self._camoufox_context:
            try:
                self._camoufox_context.__exit__(None, None, None)
                logger.debug("Browser stopped")
            except Exception as e:  # pragma: no cover - teardown best effort
                logger.debug(f"Error while stopping browser: {e}")
            finally:
                self._camoufox_context = None
                self.browser = None

    def __enter__(self) -> CaptchaSolver:
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop()

    # ----------------------------------------------------------------- #
    # Solving
    # ----------------------------------------------------------------- #

    @staticmethod
    def _normalize_url(url: str) -> str:
        """
        Make sure the URL has a path, without corrupting the query string.

        The previous implementation appended ``/`` to the raw string, which
        turned ``https://site/login?next=1`` into ``...?next=1/`` and changed
        the origin the widget was rendered against.
        """
        parsed = urlparse(url.strip())
        path = parsed.path or "/"
        return urlunparse(
            (parsed.scheme, parsed.netloc, path, parsed.params, parsed.query, parsed.fragment)
        )

    def solve(
        self,
        url: str,
        sitekey: str,
        invisible: bool = True,
        timeout: float | None = None,
    ) -> str | None:
        """
        Solve Turnstile captcha.

        Args:
            url: Target URL
            sitekey: Turnstile sitekey
            invisible: Use invisible mode (default: True)
            timeout: Override the per-solve wall-clock budget in seconds.

        Returns:
            Token string or None if failed

        Raises:
            BrowserNotStartedError: If :meth:`start` has not been called.
        """
        if not self.is_running:
            raise BrowserNotStartedError(
                "Browser is not running. Call start() or use CaptchaSolver as a context manager."
            )

        target = self._normalize_url(url)
        deadline = _Deadline(self.timeout if timeout is None else timeout)

        context = self.browser.new_context()
        try:
            page = context.new_page()
            page_data = self._build_page_data(sitekey)

            # Match on the exact target URL via a predicate rather than a glob
            # string: query strings contain characters that glob matching treats
            # as wildcards, and only the top-level document must be replaced.
            def matches(candidate: str) -> bool:
                return candidate.split("#")[0] == target.split("#")[0]

            page.route(matches, lambda route: route.fulfill(body=page_data, status=200))
            page.goto(target, timeout=self._solver.PAGE_LOAD_TIMEOUT_MS)

            window_width = page.evaluate("window.innerWidth") or 0
            window_height = page.evaluate("window.innerHeight") or 0

            if invisible:
                token = self._solve_invisible(page, window_width, window_height, deadline)
            else:
                token = self._solve_visible(page, window_width, window_height, deadline)

            if token is None and deadline.expired:
                logger.warning(f"Solve timed out after {deadline.elapsed:.1f}s")

            return token
        finally:
            # Always tear the context down, even when the solve raised, so a
            # long-lived browser does not accumulate orphaned contexts.
            try:
                context.close()
            except Exception as e:  # pragma: no cover - teardown best effort
                logger.debug(f"Error closing context: {e}")

    def _build_page_data(self, sitekey: str) -> str:
        """Build HTML page with Turnstile widget."""
        return f"""<!DOCTYPE html>
<html>
<head>
    <script src="{self._cf.API_URL}" async defer></script>
</head>
<body>
    <div class="cf-turnstile" data-sitekey="{sitekey}"></div>
</body>
</html>"""

    def _get_mouse_path(self, x1: int, y1: int, x2: int, y2: int) -> list:
        """
        Calculate natural mouse movement path.

        Capped at ``config.mouse.PATH_MAX_STEPS`` points. Without the cap a
        combination of small speeds and a large distance can spin here long
        enough to look like a hang, and the final approach is snapped to the
        target so the caller always ends up where it asked to go.
        """
        path: list[tuple[float, float]] = []
        x, y = float(x1), float(y1)
        m = self._mouse
        threshold = m.MOVE_THRESHOLD_PX
        max_steps = max(1, m.PATH_MAX_STEPS)

        while abs(x - x2) > threshold or abs(y - y2) > threshold:
            if len(path) >= max_steps:
                logger.debug(f"Mouse path hit the {max_steps}-step cap; snapping to target")
                path.append((float(x2), float(y2)))
                break

            diff = abs(x - x2) + abs(y - y2)
            speed = random.randint(m.BASE_SPEED_MIN, m.BASE_SPEED_MAX)

            if diff < m.CLOSE_THRESHOLD_PX:
                speed = random.randint(m.CLOSE_SPEED_MIN, m.CLOSE_SPEED_MAX)
            else:
                speed *= diff / m.SPEED_FACTOR

            # A zero step would never converge; keep at least one pixel of travel.
            speed = max(float(speed), 1.0)

            if abs(x - x2) > threshold:
                x += speed if x < x2 else -speed
            if abs(y - y2) > threshold:
                y += speed if y < y2 else -speed

            path.append((x, y))

        return path

    def _get_delay(self) -> float:
        """Calculate random delay for human-like behavior."""
        m = self._mouse
        return random.randint(m.DELAY_NUM_MIN, m.DELAY_NUM_MAX) / random.randint(
            m.DELAY_DENOM_MIN, m.DELAY_DENOM_MAX
        )

    def _token_check_delay(self) -> float:
        """
        Pause between token polls.

        Slightly longer than :meth:`_get_delay` so the solver is not hammering
        the DOM while waiting for Turnstile to finish its own work.
        """
        s = self._solver
        m = self._mouse
        return random.randint(s.TOKEN_CHECK_DELAY_NUM_MIN, s.TOKEN_CHECK_DELAY_NUM_MAX) / (
            random.randint(m.DELAY_DENOM_MIN, m.DELAY_DENOM_MAX)
        )

    def _should_delay(self) -> bool:
        """Check if mouse should delay (human-like probability)."""
        return random.randint(0, 100) > self._mouse.DELAY_PROBABILITY_PCT

    def _move_to(self, page, current_x: int, current_y: int, x: int, y: int) -> tuple:
        """Move mouse to position with natural movement."""
        path = self._get_mouse_path(current_x, current_y, x, y)

        for point in path:
            page.mouse.move(point[0], point[1])
            if self._should_delay():
                time.sleep(self._get_delay())

        return x, y

    def _get_token(self, page) -> str | None:
        """Get token from page."""
        elem = page.query_selector(self._cf.RESPONSE_SELECTOR)
        if elem:
            value = elem.get_attribute("value")
            if value:
                return value

        # The hidden input is the documented location, but querying the widget
        # directly catches tokens produced by an explicit-render setup.
        try:
            value = page.evaluate(
                "() => (window.turnstile && window.turnstile.getResponse) "
                "? (window.turnstile.getResponse() || null) : null"
            )
        except Exception:
            return None
        return value or None

    def _solve_invisible(
        self,
        page,
        window_width: int,
        window_height: int,
        deadline: _Deadline | None = None,
    ) -> str | None:
        """Solve invisible Turnstile captcha."""
        deadline = deadline or _Deadline(self.timeout)
        current_x, current_y = 0, 0

        # Check once before moving: an invisible widget can resolve during load.
        token = self._get_token(page)
        if token:
            return token

        for attempt in range(self._solver.INVISIBLE_SOLVE_MAX_ATTEMPTS):
            if deadline.expired:
                logger.debug(f"Invisible solve out of time after {attempt} attempts")
                return None

            random_x = _safe_randint(0, window_width)
            random_y = _safe_randint(0, window_height)

            current_x, current_y = self._move_to(page, current_x, current_y, random_x, random_y)

            token = self._get_token(page)
            if token:
                return token

            time.sleep(self._token_check_delay())

        return None

    def _find_turnstile_iframe(self, page, deadline: _Deadline):
        """
        Wait for the Turnstile iframe.

        Prefers the Cloudflare-specific selector so an unrelated iframe earlier
        in the document (ads, embeds, analytics) is not mistaken for the widget.
        """
        selectors = [self._cf.IFRAME_SRC_SELECTOR, self._cf.IFRAME_SELECTOR]

        for _ in range(self._solver.IFRAME_WAIT_MAX_ATTEMPTS):
            if deadline.expired:
                return None
            for selector in selectors:
                iframe = page.query_selector(selector)
                if iframe and iframe.bounding_box():
                    return iframe
            time.sleep(self._solver.IFRAME_POLL_INTERVAL)

        return None

    def _solve_visible(
        self,
        page,
        window_width: int,
        window_height: int,
        deadline: _Deadline | None = None,
    ) -> str | None:
        """Solve visible Turnstile captcha."""
        deadline = deadline or _Deadline(self.timeout)
        current_x, current_y = 0, 0

        iframe = self._find_turnstile_iframe(page, deadline)
        if not iframe:
            logger.warning("No iframe found")
            return None

        box = iframe.bounding_box()
        x = box["x"] + _safe_randint(self._solver.CLICK_OFFSET_MIN, self._solver.CLICK_OFFSET_MAX)
        y = box["y"] + _safe_randint(self._solver.CLICK_OFFSET_MIN, self._solver.CLICK_OFFSET_MAX)

        current_x, current_y = self._move_to(page, current_x, current_y, x, y)

        framepage = iframe.content_frame()
        if framepage is None:
            logger.warning("Turnstile iframe has no reachable content frame")
            return None

        checkbox = None
        for _ in range(self._solver.CHECKBOX_WAIT_MAX_ATTEMPTS):
            if deadline.expired:
                logger.warning("Ran out of time waiting for the checkbox")
                return None
            checkbox = framepage.query_selector("input")
            if checkbox:
                break
            time.sleep(self._solver.CHECKBOX_POLL_INTERVAL)

        if not checkbox:
            logger.warning("No checkbox found")
            return None

        cb_box = checkbox.bounding_box()
        if not cb_box:
            logger.warning("Checkbox has no bounding box")
            return None

        divisor = max(1, self._solver.CHECKBOX_CLICK_ZONE_DIVISOR)
        x = (
            cb_box["x"]
            + cb_box["width"] / divisor
            + _safe_randint(
                int(cb_box["width"] / divisor), int(cb_box["width"] - cb_box["width"] / divisor)
            )
        )
        y = (
            cb_box["y"]
            + cb_box["height"] / divisor
            + _safe_randint(
                int(cb_box["height"] / divisor), int(cb_box["height"] - cb_box["height"] / divisor)
            )
        )

        current_x, current_y = self._move_to(page, current_x, current_y, x, y)
        time.sleep(self._get_delay())
        page.mouse.click(x, y)

        for _ in range(self._solver.TOKEN_WAIT_MAX_ATTEMPTS):
            if deadline.expired:
                logger.debug("Visible solve out of time while waiting for the token")
                return None

            token = self._get_token(page)
            if token:
                return token

            random_x = _safe_randint(0, window_width)
            random_y = _safe_randint(0, window_height)

            current_x, current_y = self._move_to(page, current_x, current_y, random_x, random_y)

            token = self._get_token(page)
            if token:
                return token

            time.sleep(self._token_check_delay())

        return None
