"""
Alap-Alap Proxy Support

Parses the documented ``user:pass@host:port`` proxy syntax (plus full URLs like
``http://host:port`` and ``socks5://user:pass@host:port``) into the two shapes
the rest of the codebase needs:

* a ``requests``-style mapping for :mod:`requests`
* a Playwright/Camoufox-style mapping for the browser

The CLI, the Python API and the REST API all accepted a ``proxy`` argument but
never forwarded it anywhere. This module is what makes that argument real.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import unquote, urlparse

from .errors import ProxyError

#: Schemes Playwright/Camoufox understands.
SUPPORTED_SCHEMES = ("http", "https", "socks4", "socks5", "socks5h")

#: Used when the user gives a bare ``host:port`` or ``user:pass@host:port``.
DEFAULT_SCHEME = "http"


@dataclass(frozen=True)
class ProxyInfo:
    """A parsed proxy definition."""

    scheme: str
    host: str
    port: int | None = None
    username: str | None = None
    password: str | None = None

    @property
    def server(self) -> str:
        """Proxy server URL without credentials (Playwright wants it split)."""
        if self.port is None:
            return f"{self.scheme}://{self.host}"
        return f"{self.scheme}://{self.host}:{self.port}"

    @property
    def url(self) -> str:
        """Full proxy URL including credentials, for :mod:`requests`."""
        if self.username:
            auth = self.username
            if self.password:
                auth = f"{auth}:{self.password}"
            netloc = f"{auth}@{self.host}"
        else:
            netloc = self.host
        if self.port is not None:
            netloc = f"{netloc}:{self.port}"
        return f"{self.scheme}://{netloc}"

    def as_requests_dict(self) -> dict[str, str]:
        """Return a mapping suitable for ``requests.get(proxies=...)``."""
        return {"http": self.url, "https": self.url}

    def as_playwright_dict(self) -> dict[str, str]:
        """Return a mapping suitable for Playwright/Camoufox ``proxy=``."""
        proxy: dict[str, str] = {"server": self.server}
        if self.username:
            proxy["username"] = self.username
        if self.password:
            proxy["password"] = self.password
        return proxy

    def masked(self) -> str:
        """Human-readable form with the password redacted, safe for logs."""
        if self.username:
            return f"{self.scheme}://{self.username}:***@{self.host}:{self.port}"
        return self.server


def parse_proxy(proxy: str | None) -> ProxyInfo | None:
    """
    Parse a proxy string into a :class:`ProxyInfo`.

    Accepted forms::

        host:port
        user:pass@host:port
        http://host:port
        socks5://user:pass@host:port

    Args:
        proxy: Proxy string, or ``None``/empty for "no proxy".

    Returns:
        A :class:`ProxyInfo`, or ``None`` when no proxy was supplied.

    Raises:
        ProxyError: If the string is present but cannot be parsed.
    """
    if proxy is None:
        return None

    raw = proxy.strip()
    if not raw:
        return None

    candidate = raw if "://" in raw else f"{DEFAULT_SCHEME}://{raw}"

    try:
        parsed = urlparse(candidate)
    except ValueError as exc:  # pragma: no cover - urlparse rarely raises
        raise ProxyError(f"Invalid proxy string: {proxy!r}") from exc

    scheme = (parsed.scheme or DEFAULT_SCHEME).lower()
    if scheme not in SUPPORTED_SCHEMES:
        raise ProxyError(
            f"Unsupported proxy scheme {scheme!r}. Supported: {', '.join(SUPPORTED_SCHEMES)}"
        )

    host = parsed.hostname
    if not host:
        raise ProxyError(f"Proxy is missing a host: {proxy!r}")

    try:
        port = parsed.port
    except ValueError as exc:
        raise ProxyError(f"Proxy has an invalid port: {proxy!r}") from exc

    username = unquote(parsed.username) if parsed.username else None
    password = unquote(parsed.password) if parsed.password else None

    return ProxyInfo(
        scheme=scheme,
        host=host,
        port=port,
        username=username,
        password=password,
    )


@dataclass
class ProxyRotator:
    """
    Round-robin over a pool of proxies.

    Useful for batch solving where reusing one exit IP for every request is the
    fastest way to get rate limited.
    """

    proxies: list[ProxyInfo] = field(default_factory=list)
    _index: int = 0

    @classmethod
    def from_strings(cls, values: list[str]) -> ProxyRotator:
        """Build a rotator from raw proxy strings, skipping blanks."""
        parsed = [p for p in (parse_proxy(v) for v in values) if p is not None]
        return cls(proxies=parsed)

    def __len__(self) -> int:
        return len(self.proxies)

    def next(self) -> ProxyInfo | None:
        """Return the next proxy in the pool, or ``None`` when empty."""
        if not self.proxies:
            return None
        proxy = self.proxies[self._index % len(self.proxies)]
        self._index += 1
        return proxy
