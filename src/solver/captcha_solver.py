"""
Alap-Alap Captcha Solver

Solves Cloudflare Turnstile captchas using Camoufox for fingerprint resistance.
"""

import time
import random
from typing import Optional


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

    def start(self):
        """Start the browser."""
        try:
            from camoufox.sync_api import Camoufox
            self._camoufox_context = Camoufox(headless=self.headless)
            self.browser = self._camoufox_context.__enter__()
        except ImportError:
            raise ImportError("Camoufox is required. Install with: pip install camoufox")

    def stop(self):
        """Stop the browser."""
        if self._camoufox_context:
            self._camoufox_context.__exit__(None, None, None)

    def solve(self, url: str, sitekey: str, invisible: bool = True) -> str:
        """
        Solve Turnstile captcha.

        Args:
            url: Target URL
            sitekey: Turnstile sitekey
            invisible: Use invisible mode (default: True)

        Returns:
            Token string or "failed"
        """
        url = url + "/" if not url.endswith("/") else url

        context = self.browser.new_context()
        page = context.new_page()

        # Build custom page with sitekey
        page_data = self._build_page_data(sitekey)

        # Intercept URL to serve custom page
        page.route(url, lambda route: route.fulfill(body=page_data, status=200))
        page.goto(url)

        # Get window dimensions
        window_width = page.evaluate("window.innerWidth")
        window_height = page.evaluate("window.innerHeight")

        # Solve
        if invisible:
            token = self._solve_invisible(page, window_width, window_height)
        else:
            token = self._solve_visible(page, window_width, window_height)

        context.close()
        return token

    def _build_page_data(self, sitekey: str) -> str:
        """Build HTML page with Turnstile widget."""
        import os

        page_html_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'utils', 'page.html')

        # Try to load from utils directory
        try:
            with open(page_html_path) as f:
                page_data = f.read()
        except FileNotFoundError:
            # Fallback to minimal page
            page_data = """<!DOCTYPE html>
<html>
<head>
    <script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script>
</head>
<body>
    <!-- cf turnstile -->
</body>
</html>"""

        stub = f'<div class="cf-turnstile" data-sitekey="{sitekey}"></div>'
        return page_data.replace("<!-- cf turnstile -->", stub)

    def _get_mouse_path(self, x1: int, y1: int, x2: int, y2: int) -> list:
        """Calculate natural mouse movement path."""
        path = []
        x, y = x1, y1

        while abs(x - x2) > 3 or abs(y - y2) > 3:
            diff = abs(x - x2) + abs(y - y2)
            speed = random.randint(1, 2)

            if diff < 20:
                speed = random.randint(1, 3)
            else:
                speed *= diff / 45

            if abs(x - x2) > 3:
                x += speed if x < x2 else -speed
            if abs(y - y2) > 3:
                y += speed if y < y2 else -speed

            path.append((x, y))

        return path

    def _move_to(self, page, current_x: int, current_y: int, x: int, y: int) -> tuple:
        """Move mouse to position with natural movement."""
        path = self._get_mouse_path(current_x, current_y, x, y)

        for point in path:
            page.mouse.move(point[0], point[1])
            if random.randint(0, 100) > 15:
                time.sleep(random.randint(1, 5) / random.randint(400, 600))

        return x, y

    def _solve_invisible(self, page, window_width: int, window_height: int) -> str:
        """Solve invisible Turnstile captcha."""
        current_x, current_y = 0, 0

        for _ in range(15):
            # Random mouse movement
            random_x = random.randint(0, window_width)
            random_y = random.randint(0, window_height)

            current_x, current_y = self._move_to(page, current_x, current_y, random_x, random_y)

            # Check for token
            elem = page.query_selector("[name=cf-turnstile-response]")
            if elem and elem.get_attribute("value"):
                return elem.get_attribute("value")

            time.sleep(random.randint(2, 5) / random.randint(400, 600))

        return "failed"

    def _solve_visible(self, page, window_width: int, window_height: int) -> str:
        """Solve visible Turnstile captcha."""
        current_x, current_y = 0, 0

        # Wait for iframe
        iframe = None
        for _ in range(50):
            iframe = page.query_selector("iframe")
            if iframe and iframe.bounding_box():
                break
            time.sleep(0.2)

        if not iframe:
            return "failed"

        # Click checkbox
        box = iframe.bounding_box()
        x = box["x"] + random.randint(5, 12)
        y = box["y"] + random.randint(5, 12)

        current_x, current_y = self._move_to(page, current_x, current_y, x, y)

        framepage = iframe.content_frame()
        checkbox = None
        for _ in range(50):
            checkbox = framepage.query_selector("input")
            if checkbox:
                break
            time.sleep(0.1)

        if not checkbox:
            return "failed"

        # Click checkbox
        cb_box = checkbox.bounding_box()
        x = cb_box["x"] + cb_box["width"] / 5 + random.randint(int(cb_box["width"] / 5), int(cb_box["width"] - cb_box["width"] / 5))
        y = cb_box["y"] + cb_box["height"] / 5 + random.randint(int(cb_box["height"] / 5), int(cb_box["height"] - cb_box["height"] / 5))

        current_x, current_y = self._move_to(page, current_x, current_y, x, y)
        time.sleep(random.randint(1, 5) / random.randint(400, 600))
        page.mouse.click(x, y)

        # Wait for token
        for _ in range(15):
            random_x = random.randint(0, window_width)
            random_y = random.randint(0, window_height)

            current_x, current_y = self._move_to(page, current_x, current_y, random_x, random_y)

            elem = page.query_selector("[name=cf-turnstile-response]")
            if elem and elem.get_attribute("value"):
                return elem.get_attribute("value")

            time.sleep(random.randint(2, 5) / random.randint(400, 600))

        return "failed"
