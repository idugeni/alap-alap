"""
Alap-Alap Captcha Solver

Solves Cloudflare Turnstile captchas using Camoufox for fingerprint resistance.
"""

import random
import time
from typing import Optional

from loguru import logger

from src.config import config


class CaptchaSolver:
    """
    Solve Cloudflare Turnstile captchas.

    Uses Camoufox for anti-fingerprint browsing and intelligent
    mouse movement to bypass bot detection.
    """

    def __init__(self, proxy: Optional[str] = None, headless: bool = True):
        self.proxy = proxy
        self.headless = headless
        self.browser = None
        self._camoufox_context = None
        self._cf = config.cloudflare
        self._mouse = config.mouse
        self._solver = config.solver

    def start(self):
        """Start the browser."""
        try:
            from camoufox.sync_api import Camoufox

            self._camoufox_context = Camoufox(headless=self.headless)
            self.browser = self._camoufox_context.__enter__()
            logger.debug("Browser started")
        except ImportError as e:
            raise ImportError("Camoufox is required. Install with: pip install camoufox") from e

    def stop(self):
        """Stop the browser."""
        if self._camoufox_context:
            self._camoufox_context.__exit__(None, None, None)
            logger.debug("Browser stopped")

    def solve(self, url: str, sitekey: str, invisible: bool = True) -> str:
        """
        Solve Turnstile captcha.

        Args:
            url: Target URL
            sitekey: Turnstile sitekey
            invisible: Use invisible mode (default: True)

        Returns:
            Token string or None if failed
        """
        url = url + "/" if not url.endswith("/") else url

        context = self.browser.new_context()
        page = context.new_page()

        page_data = self._build_page_data(sitekey)
        page.route(url, lambda route: route.fulfill(body=page_data, status=200))
        page.goto(url)

        window_width = page.evaluate("window.innerWidth")
        window_height = page.evaluate("window.innerHeight")

        if invisible:
            token = self._solve_invisible(page, window_width, window_height)
        else:
            token = self._solve_visible(page, window_width, window_height)

        context.close()
        return token

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
        """Calculate natural mouse movement path."""
        path = []
        x, y = x1, y1
        m = self._mouse

        while abs(x - x2) > m.MOVE_THRESHOLD_PX or abs(y - y2) > m.MOVE_THRESHOLD_PX:
            diff = abs(x - x2) + abs(y - y2)
            speed = random.randint(m.BASE_SPEED_MIN, m.BASE_SPEED_MAX)

            if diff < m.CLOSE_THRESHOLD_PX:
                speed = random.randint(m.CLOSE_SPEED_MIN, m.CLOSE_SPEED_MAX)
            else:
                speed *= diff / m.SPEED_FACTOR

            if abs(x - x2) > m.MOVE_THRESHOLD_PX:
                x += speed if x < x2 else -speed
            if abs(y - y2) > m.MOVE_THRESHOLD_PX:
                y += speed if y < y2 else -speed

            path.append((x, y))

        return path

    def _get_delay(self) -> float:
        """Calculate random delay for human-like behavior."""
        m = self._mouse
        return random.randint(m.DELAY_NUM_MIN, m.DELAY_NUM_MAX) / random.randint(
            m.DELAY_DENOM_MIN, m.DELAY_DENOM_MAX
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

    def _get_token(self, page) -> Optional[str]:
        """Get token from page."""
        elem = page.query_selector(self._cf.RESPONSE_SELECTOR)
        if elem and elem.get_attribute("value"):
            return elem.get_attribute("value")
        return None

    def _solve_invisible(self, page, window_width: int, window_height: int) -> Optional[str]:
        """Solve invisible Turnstile captcha."""
        current_x, current_y = 0, 0

        for _ in range(self._solver.INVISIBLE_SOLVE_MAX_ATTEMPTS):
            random_x = random.randint(0, window_width)
            random_y = random.randint(0, window_height)

            current_x, current_y = self._move_to(page, current_x, current_y, random_x, random_y)

            token = self._get_token(page)
            if token:
                return token

            time.sleep(self._get_delay())

        return None

    def _solve_visible(self, page, window_width: int, window_height: int) -> Optional[str]:
        """Solve visible Turnstile captcha."""
        current_x, current_y = 0, 0

        iframe = None
        for _ in range(self._solver.IFRAME_WAIT_MAX_ATTEMPTS):
            iframe = page.query_selector(self._cf.IFRAME_SELECTOR)
            if iframe and iframe.bounding_box():
                break
            time.sleep(self._solver.IFRAME_POLL_INTERVAL)

        if not iframe:
            logger.warning("No iframe found")
            return None

        box = iframe.bounding_box()
        x = box["x"] + random.randint(self._solver.CLICK_OFFSET_MIN, self._solver.CLICK_OFFSET_MAX)
        y = box["y"] + random.randint(self._solver.CLICK_OFFSET_MIN, self._solver.CLICK_OFFSET_MAX)

        current_x, current_y = self._move_to(page, current_x, current_y, x, y)

        framepage = iframe.content_frame()
        checkbox = None
        for _ in range(self._solver.CHECKBOX_WAIT_MAX_ATTEMPTS):
            checkbox = framepage.query_selector("input")
            if checkbox:
                break
            time.sleep(self._solver.CHECKBOX_POLL_INTERVAL)

        if not checkbox:
            logger.warning("No checkbox found")
            return None

        cb_box = checkbox.bounding_box()
        divisor = self._solver.CHECKBOX_CLICK_ZONE_DIVISOR
        x = (
            cb_box["x"]
            + cb_box["width"] / divisor
            + random.randint(
                int(cb_box["width"] / divisor), int(cb_box["width"] - cb_box["width"] / divisor)
            )
        )
        y = (
            cb_box["y"]
            + cb_box["height"] / divisor
            + random.randint(
                int(cb_box["height"] / divisor), int(cb_box["height"] - cb_box["height"] / divisor)
            )
        )

        current_x, current_y = self._move_to(page, current_x, current_y, x, y)
        time.sleep(self._get_delay())
        page.mouse.click(x, y)

        for _ in range(self._solver.TOKEN_WAIT_MAX_ATTEMPTS):
            random_x = random.randint(0, window_width)
            random_y = random.randint(0, window_height)

            current_x, current_y = self._move_to(page, current_x, current_y, random_x, random_y)

            token = self._get_token(page)
            if token:
                return token

            time.sleep(self._get_delay())

        return None
