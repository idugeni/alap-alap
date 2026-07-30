"""
Alap-Alap Security Helpers

The REST API accepts a URL from the caller and then fetches it with both
:mod:`requests` and a real browser. Without a guard that is a server-side
request forgery (SSRF) primitive: anyone who can reach the API can make the
host request ``http://127.0.0.1:8080/`` or a cloud metadata endpoint and read
the outcome.

This module provides:

* :func:`validate_url` - scheme allow-list plus private/loopback/metadata IP
  blocking, applied to every resolved address of the hostname.
* :func:`check_api_key` - constant-time API key comparison.
* :class:`RateLimiter` - a small in-process sliding-window limiter.
"""

from __future__ import annotations

import ipaddress
import secrets
import socket
import threading
import time
from collections import defaultdict, deque
from urllib.parse import urlparse

from .errors import UnsafeUrlError

#: Only these schemes are ever fetched.
ALLOWED_SCHEMES = ("http", "https")

#: Cloud instance metadata services, blocked regardless of IP classification.
METADATA_HOSTS = frozenset(
    {
        "169.254.169.254",
        "metadata.google.internal",
        "metadata.goog",
        "instance-data",
    }
)


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return ``True`` for addresses that must never be fetched server-side."""
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def resolve_host(host: str) -> list[str]:
    """
    Resolve a hostname to every address it maps to.

    Returns an empty list when resolution fails; callers decide whether that is
    fatal. Checking *all* addresses matters because a name can resolve to one
    public and one private address (DNS rebinding).
    """
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError, ValueError):
        return []
    # sockaddr[0] is the address for both IPv4 (host, port) and IPv6
    # (host, port, flowinfo, scopeid); str() keeps the return type honest.
    return sorted({str(info[4][0]) for info in infos})


def validate_url(url: str, *, allow_private: bool = False) -> str:
    """
    Validate a user-supplied URL before fetching it.

    Args:
        url: The URL to check.
        allow_private: Permit loopback/private/link-local targets. Only enable
            this for trusted local usage such as testing against a dev server.

    Returns:
        The URL unchanged, so this can be used inline.

    Raises:
        UnsafeUrlError: If the URL is malformed, uses a non-HTTP scheme, or
            resolves to a blocked address while ``allow_private`` is false.
    """
    if not url or not url.strip():
        raise UnsafeUrlError("URL is empty")

    parsed = urlparse(url.strip())

    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise UnsafeUrlError(
            f"Unsupported URL scheme {parsed.scheme!r}. Allowed: {', '.join(ALLOWED_SCHEMES)}"
        )

    host = parsed.hostname
    if not host:
        raise UnsafeUrlError(f"URL is missing a host: {url!r}")

    if allow_private:
        return url

    if host.lower() in METADATA_HOSTS:
        raise UnsafeUrlError(f"Blocked metadata host: {host}")

    # A literal IP is checked directly; a name is checked via every A/AAAA record.
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None

    if literal is not None:
        if _is_blocked_ip(literal):
            raise UnsafeUrlError(f"Blocked non-public address: {host}")
        return url

    addresses = resolve_host(host)
    if not addresses:
        raise UnsafeUrlError(f"Could not resolve host: {host}")

    for address in addresses:
        if address in METADATA_HOSTS:
            raise UnsafeUrlError(f"Blocked metadata address: {address}")
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:  # pragma: no cover - getaddrinfo returns valid IPs
            continue
        if _is_blocked_ip(ip):
            raise UnsafeUrlError(f"Host {host} resolves to a non-public address: {address}")

    return url


def is_safe_url(url: str, *, allow_private: bool = False) -> bool:
    """Boolean form of :func:`validate_url`."""
    try:
        validate_url(url, allow_private=allow_private)
    except UnsafeUrlError:
        return False
    return True


def check_api_key(provided: str | None, expected: str | None) -> bool:
    """
    Compare an incoming API key against the configured one.

    When ``expected`` is unset every request is allowed, which keeps the API
    usable out of the box for local development. Comparison is constant time so
    a valid key cannot be recovered by timing the endpoint.
    """
    if not expected:
        return True
    if not provided:
        return False
    return secrets.compare_digest(str(provided), str(expected))


class RateLimiter:
    """
    Sliding-window rate limiter keyed by an arbitrary string (usually client IP).

    In-process and therefore per-worker; it is a guard against accidental
    hammering and casual abuse, not a distributed quota system.
    """

    def __init__(self, max_requests: int, window_seconds: float):
        self.max_requests = max(0, int(max_requests))
        self.window_seconds = float(window_seconds)
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        """A limit of zero (or less) disables the limiter entirely."""
        return self.max_requests > 0

    def allow(self, key: str) -> bool:
        """Record a hit for ``key`` and report whether it is within the limit."""
        if not self.enabled:
            return True

        now = time.monotonic()
        cutoff = now - self.window_seconds

        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] < cutoff:
                hits.popleft()
            if len(hits) >= self.max_requests:
                return False
            hits.append(now)
            return True

    def retry_after(self, key: str) -> float:
        """Seconds until ``key`` gets another slot. Zero when one is free now."""
        if not self.enabled:
            return 0.0
        with self._lock:
            hits = self._hits.get(key)
            if not hits or len(hits) < self.max_requests:
                return 0.0
            return max(0.0, self.window_seconds - (time.monotonic() - hits[0]))

    def reset(self, key: str | None = None) -> None:
        """Clear state for one key, or all keys when ``key`` is ``None``."""
        with self._lock:
            if key is None:
                self._hits.clear()
            else:
                self._hits.pop(key, None)
