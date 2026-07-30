"""
Alap-Alap Errors

Exception hierarchy for the captcha solver. Every failure mode that callers may
want to branch on has a dedicated type, and all of them derive from
:class:`AlapAlapError` so a single ``except`` clause can catch everything the
library raises on purpose.
"""


class AlapAlapError(Exception):
    """Base class for every Alap-Alap error."""


class ConfigError(AlapAlapError):
    """Raised when configuration cannot be loaded or is invalid."""


class ProxyError(AlapAlapError):
    """Raised when a proxy string cannot be parsed."""


class BrowserError(AlapAlapError):
    """Raised when the browser cannot be started or has crashed."""


class BrowserNotStartedError(BrowserError):
    """Raised when a solve is attempted before the browser is running."""


class DependencyMissingError(AlapAlapError):
    """Raised when a required optional dependency is not installed."""


class SitekeyNotFoundError(AlapAlapError):
    """Raised when no Turnstile sitekey could be detected for a URL."""


class SolveError(AlapAlapError):
    """Raised when the solver ran but could not produce a token."""


class SolveTimeoutError(SolveError):
    """Raised when solving exceeded its time budget."""


class UnsafeUrlError(AlapAlapError):
    """Raised when a URL is rejected by the SSRF guard."""
