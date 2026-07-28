"""
Alap-Alap Configuration

Centralized configuration for all constants and settings.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CloudflareConfig:
    """Cloudflare Turnstile configuration."""

    API_URL: str = "https://challenges.cloudflare.com/turnstile/v0/api.js"
    CHALLENGE_DOMAIN: str = "challenges.cloudflare.com"
    SITEKEY_PREFIX: str = "0x4"
    RESPONSE_SELECTOR: str = "[name=cf-turnstile-response]"
    SITEKEY_ATTR_SELECTOR: str = "[data-sitekey]"
    IFRAME_SELECTOR: str = "iframe"
    IFRAME_SRC_SELECTOR: str = 'iframe[src*="challenges.cloudflare.com"]'


@dataclass(frozen=True)
class BrowserConfig:
    """Browser and network configuration."""

    HTTP_TIMEOUT: int = 10
    PAGE_GOTO_TIMEOUT_MS: int = 30000
    PAGE_SETTLE_WAIT_MS: int = 3000
    DOM_RETRY_WAIT_MS: int = 5000
    DOM_EXTRACTION_MAX_ATTEMPTS: int = 10
    USER_AGENT: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )


@dataclass(frozen=True)
class MouseConfig:
    """Mouse movement configuration for human-like behavior."""

    MOVE_THRESHOLD_PX: int = 3
    BASE_SPEED_MIN: int = 1
    BASE_SPEED_MAX: int = 2
    CLOSE_THRESHOLD_PX: int = 20
    CLOSE_SPEED_MIN: int = 1
    CLOSE_SPEED_MAX: int = 3
    SPEED_FACTOR: int = 45
    DELAY_PROBABILITY_PCT: int = 15
    DELAY_NUM_MIN: int = 1
    DELAY_NUM_MAX: int = 5
    DELAY_DENOM_MIN: int = 400
    DELAY_DENOM_MAX: int = 600


@dataclass(frozen=True)
class SolverConfig:
    """Captcha solver configuration."""

    INVISIBLE_SOLVE_MAX_ATTEMPTS: int = 15
    TOKEN_WAIT_MAX_ATTEMPTS: int = 15
    IFRAME_WAIT_MAX_ATTEMPTS: int = 50
    IFRAME_POLL_INTERVAL: float = 0.2
    CHECKBOX_WAIT_MAX_ATTEMPTS: int = 50
    CHECKBOX_POLL_INTERVAL: float = 0.1
    CLICK_OFFSET_MIN: int = 5
    CLICK_OFFSET_MAX: int = 12
    CHECKBOX_CLICK_ZONE_DIVISOR: int = 5
    TOKEN_CHECK_DELAY_NUM_MIN: int = 2
    TOKEN_CHECK_DELAY_NUM_MAX: int = 5


@dataclass(frozen=True)
class SitekeyConfig:
    """Sitekey detection configuration."""

    MIN_LENGTH: int = 20
    CF_FORMAT_MIN_LENGTH: int = 25
    FALSE_POSITIVES: list[str] = field(
        default_factory=lambda: [
            "invalidsitekey",
            "test",
            "example",
            "placeholder",
            "dummy",
            "fake",
            "mock",
            "sample",
            "default",
            "undefined",
            "null",
            "none",
            "empty",
            "missing",
        ]
    )


@dataclass(frozen=True)
class RetryConfig:
    """Retry and rate limiting configuration."""

    MAX_RETRIES: int = 3
    RETRY_DELAY_BASE: float = 2.0
    RETRY_DELAY_MAX: float = 30.0
    RATE_LIMIT_DELAY: float = 5.0
    TIMEOUT_RETRY_CODES: list[int] = field(default_factory=lambda: [408, 429, 500, 502, 503, 504])


@dataclass(frozen=True)
class LoggingConfig:
    """Logging configuration."""

    LOG_DIR: str = "logs"
    LOG_FILE: str = "alap-alap.log"
    LOG_MAX_SIZE_MB: int = 10
    LOG_BACKUP_COUNT: int = 5
    LOG_RETENTION_DAYS: int = 7
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "{time:YYYY-MM-DD HH:mm:ss} | {level:8} | {message}"
    LOG_ROTATION: str = "10 MB"
    LOG_COMPRESSION: str = "zip"


@dataclass(frozen=True)
class StorageConfig:
    """Storage configuration."""

    DATABASE_FILE: str = "captcha_database.json"
    RESULTS_FILE: str = "results.txt"


@dataclass(frozen=True)
class AppConfig:
    """Main application configuration."""

    cloudflare: CloudflareConfig = field(default_factory=CloudflareConfig)
    browser: BrowserConfig = field(default_factory=BrowserConfig)
    mouse: MouseConfig = field(default_factory=MouseConfig)
    solver: SolverConfig = field(default_factory=SolverConfig)
    sitekey: SitekeyConfig = field(default_factory=SitekeyConfig)
    retry: RetryConfig = field(default_factory=RetryConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)


# Global config instance
config = AppConfig()
