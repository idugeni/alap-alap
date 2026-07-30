"""
Alap-Alap Configuration

Centralized configuration for all constants and settings.

Values are resolved in three layers, later layers winning:

1. the dataclass defaults below
2. an optional YAML file (``alap-alap.yml`` in the working directory, or the
   path in ``ALAP_CONFIG_FILE``)
3. environment variables named ``ALAP_<SECTION>_<FIELD>``

Examples::

    ALAP_BROWSER_HTTP_TIMEOUT=20
    ALAP_SOLVER_SOLVE_TIMEOUT_S=90
    ALAP_API_KEY=super-secret
    ALAP_SITEKEY_FALSE_POSITIVES=test,example,foo

The sections stay plain frozen dataclasses, so ``config.browser.HTTP_TIMEOUT``
and friends keep working exactly as before.
"""

import os
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any, get_args, get_origin

from .errors import ConfigError

# NOTE: this module deliberately does *not* use `from __future__ import
# annotations`. The override machinery reads `dataclasses.fields(...)[i].type`
# to coerce YAML/env strings into the declared type, and postponed evaluation
# would turn those into plain strings like "int" or "list[str]".

#: Prefix for every environment override.
ENV_PREFIX = "ALAP"

#: Environment variable holding an explicit config file path.
ENV_CONFIG_FILE = "ALAP_CONFIG_FILE"

#: File names searched in the working directory when no path is given.
DEFAULT_CONFIG_FILENAMES = ("alap-alap.yml", "alap-alap.yaml", ".alap-alap.yml")

_TRUE_VALUES = frozenset({"1", "true", "yes", "y", "on", "enable", "enabled"})
_FALSE_VALUES = frozenset({"0", "false", "no", "n", "off", "disable", "disabled", ""})


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
    HTTP_MAX_ATTEMPTS: int = 3
    HTTP_RETRY_BACKOFF_S: float = 1.0
    HTTP_RETRY_BACKOFF_MAX_S: float = 8.0
    HTTP_MAX_RESPONSE_BYTES: int = 5 * 1024 * 1024
    PAGE_GOTO_TIMEOUT_MS: int = 30000
    PAGE_SETTLE_WAIT_MS: int = 3000
    DOM_RETRY_WAIT_MS: int = 5000
    DOM_EXTRACTION_MAX_ATTEMPTS: int = 10
    JS_BUNDLE_MAX_SCANNED: int = 25
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
    #: Hard cap on generated path points. Guards against a pathological
    #: start/end combination spinning forever inside the movement loop.
    PATH_MAX_STEPS: int = 2000


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
    #: Wall-clock budget for a single solve. Zero disables the deadline.
    SOLVE_TIMEOUT_S: float = 180.0
    #: Timeout for loading the generated widget page.
    PAGE_LOAD_TIMEOUT_MS: int = 45000


@dataclass(frozen=True)
class SitekeyConfig:
    """Sitekey detection configuration."""

    MIN_LENGTH: int = 20
    CF_FORMAT_MIN_LENGTH: int = 25
    MAX_LENGTH: int = 128
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
            "your-sitekey",
            "yoursitekey",
            "sitekey",
            "changeme",
            "xxxxxxxx",
        ]
    )


@dataclass(frozen=True)
class RetryConfig:
    """Retry and rate limiting configuration."""

    #: Ceiling on solve attempts, guarding against a stray --retries 9999.
    #: Matches the upper bound accepted by the REST API's `retries` field.
    MAX_RETRIES: int = 10
    RETRY_DELAY_BASE: float = 2.0
    RETRY_DELAY_MAX: float = 30.0
    RATE_LIMIT_DELAY: float = 5.0
    #: Random jitter fraction applied to backoff delays (0 disables jitter).
    RETRY_JITTER_PCT: float = 0.2
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
    LOG_FILE_LEVEL: str = "DEBUG"
    LOG_FORMAT: str = "{time:YYYY-MM-DD HH:mm:ss} | {level:8} | {message}"
    LOG_ROTATION: str = "10 MB"
    LOG_COMPRESSION: str = "zip"
    #: Emit newline-delimited JSON to the log file instead of the text format.
    LOG_JSON: bool = False


@dataclass(frozen=True)
class StorageConfig:
    """Storage configuration."""

    DATABASE_FILE: str = "captcha_database.json"
    RESULTS_FILE: str = "results.txt"
    #: Store only a truncated fingerprint of solved tokens on disk. Tokens are
    #: credentials; the markdown export already redacts them.
    REDACT_STORED_TOKENS: bool = True
    #: Characters of the token kept when redaction is on.
    TOKEN_PREVIEW_CHARS: int = 12
    #: How long a Turnstile token stays usable. Cloudflare expires them after
    #: roughly five minutes, which is what makes a stored token worth dating.
    TOKEN_TTL_S: float = 300.0


@dataclass(frozen=True)
class ApiConfig:
    """REST API configuration."""

    #: Loopback by default. Set to 0.0.0.0 explicitly to expose the service.
    HOST: str = "127.0.0.1"
    PORT: int = 5000
    #: When set, every request must send ``X-API-Key`` (or a Bearer token).
    KEY: str = ""
    RATE_LIMIT_REQUESTS: int = 60
    RATE_LIMIT_WINDOW_S: float = 60.0
    #: Allow solving loopback/private URLs. Off by default (SSRF guard).
    ALLOW_PRIVATE_HOSTS: bool = False
    #: Browsers are heavy; this is both the concurrency cap and the number of
    #: pooled browsers, since each pool worker owns exactly one.
    MAX_CONCURRENT_SOLVES: int = 2
    #: Seconds a synchronous request waits for its job to finish.
    CONCURRENCY_WAIT_S: float = 30.0
    SOLVE_TIMEOUT_S: float = 180.0
    #: Include tokens in API responses (the whole point of the API, but
    #: switchable for shared deployments).
    RETURN_TOKENS: bool = True
    #: Jobs accepted but not yet started. Beyond this the API returns 503
    #: instead of letting an unbounded backlog build up.
    QUEUE_MAX_SIZE: int = 32
    #: How long a finished job stays readable through GET /jobs/<id>.
    JOB_TTL_S: float = 600.0
    #: Hard cap on retained jobs, so a busy server cannot grow without bound.
    JOB_MAX_RETAINED: int = 500
    #: Keep pooled browsers alive between requests. Turning this off restores
    #: the old launch-per-request behaviour.
    POOL_ENABLED: bool = True
    #: Recycle a pooled browser after this many solves; 0 disables recycling.
    #: Long-lived browsers accumulate memory and state.
    POOL_MAX_SOLVES_PER_BROWSER: int = 50


@dataclass(frozen=True)
class BatchConfig:
    """Batch solving configuration."""

    MAX_WORKERS: int = 3
    WORKER_LIMIT: int = 16
    #: Delay between dispatches inside a worker, smoothing request bursts.
    STAGGER_S: float = 0.5
    CONTINUE_ON_ERROR: bool = True


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
    api: ApiConfig = field(default_factory=ApiConfig)
    batch: BatchConfig = field(default_factory=BatchConfig)

    def to_dict(self) -> dict[str, dict[str, Any]]:
        """Serialize the effective configuration, section by section."""
        out: dict[str, dict[str, Any]] = {}
        for section in fields(self):
            value = getattr(self, section.name)
            out[section.name] = {f.name: getattr(value, f.name) for f in fields(value)}
        return out


# --------------------------------------------------------------------------- #
# Override plumbing
# --------------------------------------------------------------------------- #


def _coerce_bool(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    if text in _TRUE_VALUES:
        return True
    if text in _FALSE_VALUES:
        return False
    raise ConfigError(f"Cannot read {raw!r} as a boolean")


def _coerce_list(raw: Any, item_type: type) -> list[Any]:
    if isinstance(raw, (list, tuple)):
        items: list[Any] = list(raw)
    else:
        items = [part.strip() for part in str(raw).split(",") if part.strip()]
    if item_type is int:
        return [int(item) for item in items]
    if item_type is float:
        return [float(item) for item in items]
    return [str(item) for item in items]


def _coerce(raw: Any, target: Any, label: str) -> Any:
    """Convert a YAML/env value to the type declared on the dataclass field."""
    origin = get_origin(target)

    try:
        if origin is list:
            args = get_args(target)
            return _coerce_list(raw, args[0] if args else str)
        if target is bool:
            return _coerce_bool(raw)
        if target is int:
            return int(str(raw).strip())
        if target is float:
            return float(str(raw).strip())
        if target is str:
            return str(raw)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"Invalid value for {label}: {raw!r} ({exc})") from exc

    return raw


def _section_overrides_from_env(section_name: str, section: Any) -> dict[str, Any]:
    """Collect ``ALAP_<SECTION>_<FIELD>`` overrides for one section."""
    overrides: dict[str, Any] = {}
    prefix = f"{ENV_PREFIX}_{section_name.upper()}_"

    for f in fields(section):
        env_name = f"{prefix}{f.name}"
        if env_name in os.environ:
            overrides[f.name] = _coerce(os.environ[env_name], f.type, env_name)

    return overrides


def _normalize_keys(raw: dict[Any, Any], section: Any, label: str) -> dict[str, Any]:
    """Map YAML keys (any case) onto real field names, rejecting unknown ones."""
    valid = {f.name: f for f in fields(section)}
    lookup = {name.lower(): name for name in valid}
    out: dict[str, Any] = {}

    for key, value in raw.items():
        field_name = lookup.get(str(key).strip().lower())
        if field_name is None:
            raise ConfigError(f"Unknown option {label}.{key}")
        out[field_name] = _coerce(value, valid[field_name].type, f"{label}.{field_name}")

    return out


def find_config_file(path: str | os.PathLike[str] | None = None) -> Path | None:
    """
    Locate the YAML config file.

    Explicit ``path`` wins, then ``ALAP_CONFIG_FILE``, then the well-known
    filenames in the current directory. Returns ``None`` when there is nothing
    to load, which is the normal case.
    """
    if path:
        candidate = Path(path).expanduser()
        if not candidate.is_file():
            raise ConfigError(f"Config file not found: {candidate}")
        return candidate

    env_path = os.environ.get(ENV_CONFIG_FILE)
    if env_path:
        candidate = Path(env_path).expanduser()
        if not candidate.is_file():
            raise ConfigError(f"Config file from {ENV_CONFIG_FILE} not found: {candidate}")
        return candidate

    for name in DEFAULT_CONFIG_FILENAMES:
        candidate = Path.cwd() / name
        if candidate.is_file():
            return candidate

    return None


def _load_yaml(path: Path) -> dict[str, Any]:
    """Read a YAML mapping from disk."""
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - pyyaml is a hard dependency
        raise ConfigError("PyYAML is required to read config files") from exc

    try:
        with open(path, encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except OSError as exc:
        raise ConfigError(f"Could not read config file {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc

    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"Config file {path} must contain a mapping at the top level")
    return data


def load_config(
    path: str | os.PathLike[str] | None = None,
    *,
    use_env: bool = True,
    use_file: bool = True,
) -> AppConfig:
    """
    Build the effective :class:`AppConfig`.

    Args:
        path: Explicit YAML config path. Ignored when ``use_file`` is false.
        use_env: Apply ``ALAP_*`` environment overrides.
        use_file: Look for and apply a YAML config file.

    Returns:
        A fully resolved :class:`AppConfig`.

    Raises:
        ConfigError: On an unreadable file, unknown option, or bad value.
    """
    base = AppConfig()
    section_names = {f.name for f in fields(base)}

    file_data: dict[str, Any] = {}
    if use_file:
        config_file = find_config_file(path)
        if config_file is not None:
            file_data = _load_yaml(config_file)

    updates: dict[str, Any] = {}

    for section_name in section_names:
        section = getattr(base, section_name)
        overrides: dict[str, Any] = {}

        raw_section = file_data.get(section_name)
        if raw_section is not None:
            if not isinstance(raw_section, dict):
                raise ConfigError(f"Config section {section_name!r} must be a mapping")
            overrides.update(_normalize_keys(raw_section, section, section_name))

        if use_env:
            overrides.update(_section_overrides_from_env(section_name, section))

        if overrides:
            updates[section_name] = replace(section, **overrides)

    unknown = {str(key) for key in file_data} - section_names
    if unknown:
        raise ConfigError(
            f"Unknown config section(s): {', '.join(sorted(unknown))}. "
            f"Valid sections: {', '.join(sorted(section_names))}"
        )

    resolved = replace(base, **updates) if updates else base
    _validate(resolved)
    return resolved


def _validate(cfg: AppConfig) -> None:
    """Reject combinations that would break the solver at runtime."""
    if cfg.browser.HTTP_TIMEOUT <= 0:
        raise ConfigError("browser.HTTP_TIMEOUT must be greater than zero")
    if cfg.browser.HTTP_MAX_ATTEMPTS < 1:
        raise ConfigError("browser.HTTP_MAX_ATTEMPTS must be at least 1")
    if cfg.mouse.PATH_MAX_STEPS < 1:
        raise ConfigError("mouse.PATH_MAX_STEPS must be at least 1")
    if cfg.mouse.SPEED_FACTOR <= 0:
        raise ConfigError("mouse.SPEED_FACTOR must be greater than zero")
    if cfg.solver.INVISIBLE_SOLVE_MAX_ATTEMPTS < 1:
        raise ConfigError("solver.INVISIBLE_SOLVE_MAX_ATTEMPTS must be at least 1")
    if cfg.solver.SOLVE_TIMEOUT_S < 0:
        raise ConfigError("solver.SOLVE_TIMEOUT_S must not be negative")
    if cfg.sitekey.MIN_LENGTH < 1:
        raise ConfigError("sitekey.MIN_LENGTH must be at least 1")
    if cfg.retry.RETRY_DELAY_BASE <= 0:
        raise ConfigError("retry.RETRY_DELAY_BASE must be greater than zero")
    if not 0 <= cfg.retry.RETRY_JITTER_PCT <= 1:
        raise ConfigError("retry.RETRY_JITTER_PCT must be between 0 and 1")
    if not 1 <= cfg.api.PORT <= 65535:
        raise ConfigError("api.PORT must be between 1 and 65535")
    if cfg.api.MAX_CONCURRENT_SOLVES < 1:
        raise ConfigError("api.MAX_CONCURRENT_SOLVES must be at least 1")
    if cfg.api.QUEUE_MAX_SIZE < 1:
        raise ConfigError("api.QUEUE_MAX_SIZE must be at least 1")
    if cfg.api.JOB_TTL_S <= 0:
        raise ConfigError("api.JOB_TTL_S must be greater than zero")
    if cfg.api.JOB_MAX_RETAINED < 1:
        raise ConfigError("api.JOB_MAX_RETAINED must be at least 1")
    if cfg.api.POOL_MAX_SOLVES_PER_BROWSER < 0:
        raise ConfigError("api.POOL_MAX_SOLVES_PER_BROWSER must not be negative")
    if cfg.storage.TOKEN_TTL_S <= 0:
        raise ConfigError("storage.TOKEN_TTL_S must be greater than zero")
    if cfg.batch.MAX_WORKERS < 1:
        raise ConfigError("batch.MAX_WORKERS must be at least 1")
    if cfg.batch.MAX_WORKERS > cfg.batch.WORKER_LIMIT:
        raise ConfigError(
            f"batch.MAX_WORKERS ({cfg.batch.MAX_WORKERS}) exceeds "
            f"batch.WORKER_LIMIT ({cfg.batch.WORKER_LIMIT})"
        )


def _safe_load() -> AppConfig:
    """Load config, falling back to defaults if the environment is misconfigured."""
    try:
        return load_config()
    except ConfigError as exc:
        # Importing config must never hard-fail the process: a typo in an env
        # var should degrade to defaults with a visible warning, not stop the
        # CLI from starting (and from telling the user what is wrong).
        import warnings

        warnings.warn(f"Falling back to default config: {exc}", RuntimeWarning, stacklevel=2)
        return AppConfig()


# Global config instance
config: AppConfig = _safe_load()


def reload_config(
    path: str | os.PathLike[str] | None = None,
    *,
    use_env: bool = True,
    use_file: bool = True,
) -> AppConfig:
    """
    Re-resolve the global :data:`config` in place.

    Modules that captured ``config.<section>`` at import time keep their old
    values, so this is intended for startup and tests rather than live reload.
    """
    global config
    config = load_config(path, use_env=use_env, use_file=use_file)
    return config


__all__ = [
    "ApiConfig",
    "AppConfig",
    "BatchConfig",
    "BrowserConfig",
    "CloudflareConfig",
    "LoggingConfig",
    "MouseConfig",
    "RetryConfig",
    "SitekeyConfig",
    "SolverConfig",
    "StorageConfig",
    "config",
    "find_config_file",
    "load_config",
    "reload_config",
]
