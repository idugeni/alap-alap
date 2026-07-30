"""
Alap-Alap Sitekey Detector

Intelligent sitekey detection using multiple methods:
1. URL parameter extraction
2. Static HTML parsing
3. Camoufox browser + JS bundle analysis

Every layer honours the ``proxy`` argument, and the HTTP layer retries
transient failures (connection resets, 429/5xx) with exponential backoff.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from loguru import logger
from tenacity import (
    RetryError,
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    wait_random,
)

from src.config import config
from src.errors import UnsafeUrlError
from src.proxy import ProxyInfo, parse_proxy
from src.security import validate_url

#: Detection layer names reported by :meth:`SitekeyDetector.detect_with_method`.
METHOD_URL = "url"
METHOD_HTML = "html"
METHOD_DOM = "dom"
METHOD_JS_BUNDLE = "js_bundle"


class _RetryableStatus(requests.RequestException):
    """Internal marker for HTTP status codes worth retrying."""

    def __init__(self, status_code: int, url: str):
        super().__init__(f"HTTP {status_code} from {url}")
        self.status_code = status_code


class SitekeyDetector:
    """
    Detect Cloudflare Turnstile sitekeys from URLs.

    Uses a multi-layered approach:
    - Fast: URL params, static HTML
    - Thorough: Camoufox browser + JavaScript bundle analysis

    Args:
        proxy: Proxy string (``user:pass@host:port`` or a full proxy URL).
            Applied to both the HTTP requests and the browser.
        allow_private_hosts: Permit loopback/private targets. Defaults to
            ``True`` for direct CLI/library use; the REST API passes ``False``
            so untrusted callers cannot probe the host's internal network.
        verify_ssl: Verify TLS certificates on the static-HTML layer.
    """

    SITEKEY_PATTERNS = [
        re.compile(r'data-sitekey=["\']([^"\']+)["\']', re.IGNORECASE),
        re.compile(r'sitekey\s*[:=]\s*["\']([^"\']+)["\']', re.IGNORECASE),
        re.compile(r'turnstile.*?sitekey\s*[:=]\s*["\']([^"\']+)["\']', re.IGNORECASE | re.DOTALL),
        re.compile(r'"sitekey"\s*:\s*"([^"]+)"', re.IGNORECASE),
        # Turnstile iframes and explicit-render calls embed the key in a URL.
        re.compile(r'challenges\.cloudflare\.com/[^"\']*?[?&]sitekey=([A-Za-z0-9_-]+)', re.I),
        # Bare Cloudflare-format key anywhere in the markup, as a last resort.
        re.compile(r"(0x4[A-Za-z0-9_-]{18,})"),
    ]

    JS_BUNDLE_PATTERNS = [
        (r'sitekey\s*[:=]\s*["\']([0-9a-zA-Z_-]{20,})["\']', "sitekey assignment"),
        (r'data-sitekey\s*=\s*["\']([0-9a-zA-Z_-]{20,})["\']', "data-sitekey"),
        (r'["\']?(0x4[A-Za-z0-9_-]{20,})["\']?', "Cloudflare sitekey format"),
    ]

    #: Substrings that make a JS bundle more likely to hold the sitekey.
    JS_PRIORITY_KEYWORDS = ("turnstile", "captcha", "challenge", "auth", "login", "signup")

    #: Shape of a Cloudflare Turnstile sitekey: a digit, an "x", then base62
    #: with dashes and underscores. Production keys look like ``0x4AAAAAAA...``
    #: and Cloudflare's documented testing keys like ``1x0000...AA``,
    #: ``2x0000...AB`` and ``3x0000...FF``.
    #:
    #: The previous check accepted only the ``0x4`` prefix or anything longer
    #: than 25 characters containing a digit, which rejected every one of the
    #: official 24-character test keys.
    TURNSTILE_KEY_RE = re.compile(r"^[0-9]x[0-9A-Za-z_-]{18,}$")

    def __init__(
        self,
        proxy: str | None = None,
        *,
        allow_private_hosts: bool = True,
        verify_ssl: bool = True,
    ):
        self.proxy = proxy
        self.proxy_info: ProxyInfo | None = parse_proxy(proxy)
        self.allow_private_hosts = allow_private_hosts
        self.verify_ssl = verify_ssl
        self._browser = config.browser
        self._sitekey = config.sitekey
        self._cf = config.cloudflare
        self._retry = config.retry
        self.headers = {
            "User-Agent": self._browser.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        self.last_method: str | None = None
        self._session: requests.Session | None = None

        if self.proxy_info:
            logger.debug(f"Detector using proxy {self.proxy_info.masked()}")

    # ----------------------------------------------------------------- #
    # Lifecycle
    # ----------------------------------------------------------------- #

    @property
    def session(self) -> requests.Session:
        """Lazily created HTTP session with proxy and headers applied."""
        if self._session is None:
            session = requests.Session()
            session.headers.update(self.headers)
            if self.proxy_info:
                session.proxies.update(self.proxy_info.as_requests_dict())
            self._session = session
        return self._session

    def close(self) -> None:
        """Release the pooled HTTP connections."""
        if self._session is not None:
            self._session.close()
            self._session = None

    def __enter__(self) -> SitekeyDetector:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    # ----------------------------------------------------------------- #
    # Public API
    # ----------------------------------------------------------------- #

    def detect(self, url: str) -> str | None:
        """
        Detect sitekey from URL using multiple methods.

        Args:
            url: Target URL to detect sitekey from

        Returns:
            Detected sitekey or None
        """
        sitekey, _method = self.detect_with_method(url)
        return sitekey

    def detect_with_method(self, url: str) -> tuple[str | None, str | None]:
        """
        Detect a sitekey and report which layer found it.

        Returns:
            ``(sitekey, method)`` where method is one of ``url``, ``html``,
            ``dom``, ``js_bundle``, or ``(None, None)`` when nothing was found.
        """
        self.last_method = None

        try:
            validate_url(url, allow_private=self.allow_private_hosts)
        except UnsafeUrlError as exc:
            logger.warning(f"Refusing to fetch {url}: {exc}")
            return None, None

        sitekey = self._extract_from_url(url)
        if sitekey:
            logger.info(f"Sitekey found in URL: {sitekey}")
            self.last_method = METHOD_URL
            return sitekey, METHOD_URL

        sitekey = self._extract_from_html(url)
        if sitekey:
            logger.info(f"Sitekey found in HTML: {sitekey}")
            self.last_method = METHOD_HTML
            return sitekey, METHOD_HTML

        logger.info("Using Camoufox for detection...")
        sitekey = self._extract_with_browser(url)
        if sitekey:
            logger.info(f"Sitekey detected: {sitekey}")
            return sitekey, self.last_method

        logger.warning(f"No sitekey found for {url}")
        return None, None

    # ----------------------------------------------------------------- #
    # Layer 1: URL parameters
    # ----------------------------------------------------------------- #

    def _extract_from_url(self, url: str) -> str | None:
        """Extract sitekey from URL parameters."""
        try:
            parsed = urlparse(url)
            for query in (parsed.query, parsed.fragment):
                if not query:
                    continue
                params = parse_qs(query)
                for name in ("sitekey", "data-sitekey", "site_key"):
                    values = params.get(name)
                    if values and values[0]:
                        return values[0]
        except Exception:
            pass
        return None

    # ----------------------------------------------------------------- #
    # Layer 2: static HTML
    # ----------------------------------------------------------------- #

    def _extract_from_html(self, url: str) -> str | None:
        """Extract sitekey from static HTML."""
        html = self._fetch_text(url)
        if not html:
            return None

        sitekey = self._search_patterns(html)
        if sitekey:
            return sitekey

        # The widget is often injected by a same-origin script that the plain
        # HTML only references, so follow a small number of local scripts.
        return self._scan_linked_scripts(url, html)

    def _search_patterns(self, html: str) -> str | None:
        """Run every sitekey pattern over a blob of text."""
        for pattern in self.SITEKEY_PATTERNS:
            for match in pattern.finditer(html):
                candidate = match.group(1)
                if self._is_valid_sitekey(candidate):
                    return candidate
        return None

    def _scan_linked_scripts(self, base_url: str, html: str) -> str | None:
        """Fetch same-origin scripts referenced by the page and scan them."""
        base_host = urlparse(base_url).netloc
        script_srcs = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', html, re.IGNORECASE)

        candidates: list[str] = []
        for src in script_srcs:
            absolute = urljoin(base_url, src)
            parsed = urlparse(absolute)
            if parsed.scheme not in ("http", "https"):
                continue
            if parsed.netloc != base_host:
                continue
            candidates.append(absolute)

        max_scanned = max(1, self._browser.JS_BUNDLE_MAX_SCANNED)
        for script_url in self._prioritize_bundles(candidates)[:max_scanned]:
            content = self._fetch_text(script_url, validate=False)
            if not content or "turnstile" not in content.lower():
                continue
            sitekey = self._search_bundle_patterns(content)
            if sitekey:
                self.last_method = METHOD_JS_BUNDLE
                return sitekey

        return None

    def _fetch_text(self, url: str, *, validate: bool = True) -> str | None:
        """
        GET ``url`` and return the body, retrying transient failures.

        Returns ``None`` instead of raising: detection is best-effort and the
        caller falls through to the next layer.
        """
        if validate:
            try:
                validate_url(url, allow_private=self.allow_private_hosts)
            except UnsafeUrlError as exc:
                logger.debug(f"Skipping unsafe URL {url}: {exc}")
                return None

        retryer = Retrying(
            stop=stop_after_attempt(max(1, self._browser.HTTP_MAX_ATTEMPTS)),
            wait=wait_exponential(
                multiplier=self._browser.HTTP_RETRY_BACKOFF_S,
                max=self._browser.HTTP_RETRY_BACKOFF_MAX_S,
            )
            + wait_random(0, max(0.0, self._browser.HTTP_RETRY_BACKOFF_S)),
            retry=retry_if_exception_type(
                (
                    _RetryableStatus,
                    requests.ConnectionError,
                    requests.Timeout,
                    requests.TooManyRedirects,
                )
            ),
            reraise=True,
        )

        try:
            return retryer(self._get_text, url)
        except _RetryableStatus as exc:
            logger.warning(f"Giving up on {url}: {exc}")
        except requests.RequestException as exc:
            logger.debug(f"Request failed for {url}: {exc}")
        except RetryError as exc:  # pragma: no cover - reraise=True avoids this
            logger.debug(f"Retries exhausted for {url}: {exc}")
        return None

    def _get_text(self, url: str) -> str:
        """Single HTTP GET, raising :class:`_RetryableStatus` on transient codes."""
        response = self.session.get(
            url,
            timeout=self._browser.HTTP_TIMEOUT,
            verify=self.verify_ssl,
            stream=True,
            allow_redirects=True,
        )

        try:
            if response.status_code in self._retry.TIMEOUT_RETRY_CODES:
                if response.status_code == 429:
                    logger.warning(f"Rate limited on {url}")
                raise _RetryableStatus(response.status_code, url)

            response.raise_for_status()
            return self._read_capped(response)
        finally:
            response.close()

    def _read_capped(self, response: requests.Response) -> str:
        """Read at most ``HTTP_MAX_RESPONSE_BYTES`` and decode to text."""
        limit = self._browser.HTTP_MAX_RESPONSE_BYTES
        chunks: list[bytes] = []
        total = 0

        for chunk in response.iter_content(chunk_size=65536):
            if not chunk:
                continue
            chunks.append(chunk)
            total += len(chunk)
            if total >= limit:
                logger.debug(f"Truncated {response.url} at {limit} bytes")
                break

        raw = b"".join(chunks)[:limit]
        encoding = response.encoding or "utf-8"
        try:
            return raw.decode(encoding, errors="replace")
        except LookupError:
            return raw.decode("utf-8", errors="replace")

    # ----------------------------------------------------------------- #
    # Layer 3: browser
    # ----------------------------------------------------------------- #

    def _camoufox_kwargs(self) -> dict:
        """Build Camoufox constructor arguments, including the proxy."""
        kwargs: dict = {"headless": True}
        if self.proxy_info:
            kwargs["proxy"] = self.proxy_info.as_playwright_dict()
            # Without this Camoufox may leak the real IP via WebRTC/DNS.
            kwargs["geoip"] = True
        return kwargs

    def _extract_with_browser(self, url: str) -> str | None:
        """Extract sitekey using Camoufox browser."""
        try:
            from camoufox.sync_api import Camoufox

            with Camoufox(**self._camoufox_kwargs()) as browser:
                page = browser.new_page()
                try:
                    return self._analyze_page(page, url)
                finally:
                    page.close()
        except ImportError:
            logger.warning("Camoufox not available")
            return None
        except Exception as e:
            logger.error(f"Browser error: {e}")
            return None

    def _analyze_page(self, page, url: str) -> str | None:
        """Analyze page for sitekey."""
        js_bundles: list[str] = []
        seen: set[str] = set()

        def handle_request(request):
            is_script = request.url.endswith(".js") or ".js?" in request.url
            if is_script and request.url not in seen:
                seen.add(request.url)
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
                self.last_method = METHOD_DOM
                return sitekey

            page.wait_for_timeout(self._browser.DOM_RETRY_WAIT_MS)

        return self._analyze_js_bundles(page, js_bundles)

    def _prioritize_bundles(self, js_bundles: list[str]) -> list[str]:
        """Order bundle URLs so likely candidates are scanned first."""

        def get_priority(url: str) -> int:
            url_lower = url.lower()
            for i, keyword in enumerate(self.JS_PRIORITY_KEYWORDS):
                if keyword in url_lower:
                    return i
            return len(self.JS_PRIORITY_KEYWORDS)

        # dict.fromkeys preserves order while removing duplicates.
        return sorted(dict.fromkeys(js_bundles), key=get_priority)

    def _search_bundle_patterns(self, content: str) -> str | None:
        """Run the bundle-specific patterns over JavaScript source."""
        for pattern, _desc in self.JS_BUNDLE_PATTERNS:
            for match in re.finditer(pattern, content, re.IGNORECASE):
                candidate = match.group(1)
                if self._is_valid_sitekey(candidate):
                    return candidate
        return None

    def _analyze_js_bundles(self, page, js_bundles: list[str]) -> str | None:
        """Analyze JavaScript bundles for sitekey."""
        sorted_bundles = self._prioritize_bundles(js_bundles)
        max_scanned = max(1, self._browser.JS_BUNDLE_MAX_SCANNED)

        for bundle_url in sorted_bundles[:max_scanned]:
            try:
                content = page.evaluate(
                    """async (bundleUrl) => {
                        try {
                            const response = await fetch(bundleUrl);
                            return await response.text();
                        } catch (e) {
                            return "";
                        }
                    }""",
                    bundle_url,
                )

                if not content or "turnstile" not in content.lower():
                    continue

                sitekey = self._search_bundle_patterns(content)
                if sitekey:
                    self.last_method = METHOD_JS_BUNDLE
                    return sitekey

            except Exception:
                continue

        return None

    # ----------------------------------------------------------------- #
    # Validation
    # ----------------------------------------------------------------- #

    def _is_valid_sitekey(self, key: str | None) -> bool:
        """Validate sitekey format."""
        if not key or not isinstance(key, str):
            return False

        key = key.strip()
        if len(key) < self._sitekey.MIN_LENGTH or len(key) > self._sitekey.MAX_LENGTH:
            return False
        if key.lower() in self._sitekey.FALSE_POSITIVES:
            return False
        # Templating leftovers such as {{ sitekey }} or ${SITEKEY}.
        if any(ch in key for ch in "{}$<>\"' \t\n"):
            return False
        if not re.fullmatch(r"[A-Za-z0-9_-]+", key):
            return False

        # The configured prefix stays authoritative for anyone overriding it.
        if key.startswith(self._cf.SITEKEY_PREFIX):
            return True

        # Any key in the Turnstile family, including the official test keys.
        if self.TURNSTILE_KEY_RE.match(key):
            return True

        # Generic fallback for keys that are long enough to be meaningful.
        return len(key) > self._sitekey.CF_FORMAT_MIN_LENGTH and any(c.isdigit() for c in key)
