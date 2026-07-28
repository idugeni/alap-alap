"""
Alap-Alap Sitekey Detector

Intelligent sitekey detection using multiple methods:
1. URL parameter extraction
2. Static HTML parsing
3. Camoufox browser + JS bundle analysis
"""

import re
from urllib.parse import parse_qs, urlparse

import requests
from loguru import logger

from src.config import config


class SitekeyDetector:
    """
    Detect Cloudflare Turnstile sitekeys from URLs.

    Uses a multi-layered approach:
    - Fast: URL params, static HTML
    - Thorough: Camoufox browser + JavaScript bundle analysis
    """

    SITEKEY_PATTERNS = [
        re.compile(r'data-sitekey=["\']([^"\']+)["\']', re.IGNORECASE),
        re.compile(r'sitekey\s*[:=]\s*["\']([^"\']+)["\']', re.IGNORECASE),
        re.compile(r'turnstile.*?sitekey\s*[:=]\s*["\']([^"\']+)["\']', re.IGNORECASE | re.DOTALL),
        re.compile(r'"sitekey"\s*:\s*"([^"]+)"', re.IGNORECASE),
    ]

    JS_BUNDLE_PATTERNS = [
        (r'sitekey\s*[:=]\s*["\']([0-9a-zA-Z_-]{20,})["\']', "sitekey assignment"),
        (r'data-sitekey\s*=\s*["\']([0-9a-zA-Z_-]{20,})["\']', "data-sitekey"),
        (r'["\']?(0x4[A-Za-z0-9_-]{20,})["\']?', "Cloudflare sitekey format"),
    ]

    def __init__(self, proxy: str | None = None):
        self.proxy = proxy
        self._browser = config.browser
        self._sitekey = config.sitekey
        self._cf = config.cloudflare
        self.headers = {"User-Agent": self._browser.USER_AGENT}

    def detect(self, url: str) -> str | None:
        """
        Detect sitekey from URL using multiple methods.

        Args:
            url: Target URL to detect sitekey from

        Returns:
            Detected sitekey or None
        """
        sitekey = self._extract_from_url(url)
        if sitekey:
            logger.info(f"Sitekey found in URL: {sitekey}")
            return sitekey

        sitekey = self._extract_from_html(url)
        if sitekey:
            logger.info(f"Sitekey found in HTML: {sitekey}")
            return sitekey

        logger.info("Using Camoufox for detection...")
        sitekey = self._extract_with_browser(url)
        if sitekey:
            logger.info(f"Sitekey detected: {sitekey}")
            return sitekey

        return None

    def _extract_from_url(self, url: str) -> str | None:
        """Extract sitekey from URL parameters."""
        try:
            parsed = urlparse(url)
            params = parse_qs(parsed.query)
            if "sitekey" in params:
                return params["sitekey"][0]
            if "#" in url:
                fragment = url.split("#")[1]
                fragment_params = parse_qs(fragment)
                if "sitekey" in fragment_params:
                    return fragment_params["sitekey"][0]
        except Exception:
            pass
        return None

    def _extract_from_html(self, url: str) -> str | None:
        """Extract sitekey from static HTML."""
        try:
            response = requests.get(url, headers=self.headers, timeout=self._browser.HTTP_TIMEOUT)
            response.raise_for_status()
            html = response.text

            for pattern in self.SITEKEY_PATTERNS:
                match = pattern.search(html)
                if match:
                    sitekey = match.group(1)
                    if self._is_valid_sitekey(sitekey):
                        return sitekey
        except requests.RequestException:
            pass
        return None

    def _extract_with_browser(self, url: str) -> str | None:
        """Extract sitekey using Camoufox browser."""
        try:
            from camoufox.sync_api import Camoufox

            with Camoufox(headless=True) as browser:
                page = browser.new_page()
                return self._analyze_page(page, url)
        except ImportError:
            logger.warning("Camoufox not available")
            return None
        except Exception as e:
            logger.error(f"Browser error: {e}")
            return None

    def _analyze_page(self, page, url: str) -> str | None:
        """Analyze page for sitekey."""
        js_bundles = []

        def handle_request(request):
            if request.url.endswith(".js") or ".js?" in request.url:
                js_bundles.append(request.url)

        page.on("request", handle_request)

        page.goto(url, wait_until="domcontentloaded", timeout=self._browser.PAGE_GOTO_TIMEOUT_MS)
        page.wait_for_timeout(self._browser.PAGE_SETTLE_WAIT_MS)

        for _attempt in range(self._browser.DOM_EXTRACTION_MAX_ATTEMPTS):
            sitekey = page.evaluate(f"""() => {{
                const cfDiv = document.querySelector('{self._cf.SITEKEY_ATTR_SELECTOR}');
                if (cfDiv) return cfDiv.getAttribute('data-sitekey');

                const iframes = document.querySelectorAll(
                    'iframe[src*="{self._cf.CHALLENGE_DOMAIN}"]'
                );
                for (const iframe of iframes) {{
                    const match = iframe.src.match(/sitekey=([a-zA-Z0-9_-]+)/);
                    if (match) return match[1];
                }}

                return null;
            }}""")

            if sitekey and self._is_valid_sitekey(sitekey):
                return sitekey

            page.wait_for_timeout(self._browser.DOM_RETRY_WAIT_MS)

        return self._analyze_js_bundles(page, js_bundles)

    def _analyze_js_bundles(self, page, js_bundles: list[str]) -> str | None:
        """Analyze JavaScript bundles for sitekey."""
        priority_keywords = ["turnstile", "auth", "login", "signup", "challenge"]

        def get_priority(url):
            url_lower = url.lower()
            for i, keyword in enumerate(priority_keywords):
                if keyword in url_lower:
                    return i
            return len(priority_keywords)

        sorted_bundles = sorted(js_bundles, key=get_priority)

        for bundle_url in sorted_bundles:
            try:
                content = page.evaluate(f"""async () => {{
                    try {{
                        const response = await fetch("{bundle_url}");
                        return await response.text();
                    }} catch (e) {{
                        return "";
                    }}
                }}""")

                if not content or "turnstile" not in content.lower():
                    continue

                for pattern, _desc in self.JS_BUNDLE_PATTERNS:
                    matches = re.findall(pattern, content, re.IGNORECASE)
                    for match in matches:
                        if self._is_valid_sitekey(match):
                            return match

            except Exception:
                continue

        return None

    def _is_valid_sitekey(self, key: str) -> bool:
        """Validate sitekey format."""
        if not key or len(key) < self._sitekey.MIN_LENGTH:
            return False
        if key.lower() in self._sitekey.FALSE_POSITIVES:
            return False
        is_cf_format = len(key) > self._sitekey.CF_FORMAT_MIN_LENGTH and any(
            c.isdigit() for c in key
        )
        return key.startswith(self._cf.SITEKEY_PREFIX) or is_cf_format
