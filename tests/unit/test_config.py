"""Unit tests for config module."""

from unittest.mock import patch

import pytest

from src.config import config, load_config
from src.errors import ConfigError


class TestConfig:
    """Test configuration defaults."""

    def test_cloudflare_config(self):
        assert config.cloudflare.API_URL.startswith("https://")
        assert config.cloudflare.CHALLENGE_DOMAIN == "challenges.cloudflare.com"
        assert config.cloudflare.SITEKEY_PREFIX == "0x4"

    def test_browser_config(self):
        assert config.browser.HTTP_TIMEOUT > 0
        assert config.browser.PAGE_GOTO_TIMEOUT_MS > 0
        assert "Chrome" in config.browser.USER_AGENT

    def test_mouse_config(self):
        assert config.mouse.MOVE_THRESHOLD_PX >= 0
        assert config.mouse.SPEED_FACTOR > 0

    def test_solver_config(self):
        assert config.solver.INVISIBLE_SOLVE_MAX_ATTEMPTS > 0
        assert config.solver.IFRAME_WAIT_MAX_ATTEMPTS > 0

    def test_retry_config(self):
        assert config.retry.MAX_RETRIES > 0
        assert config.retry.RETRY_DELAY_BASE > 0

    def test_storage_config(self):
        assert config.storage.DATABASE_FILE.endswith(".json")
        assert config.storage.RESULTS_FILE.endswith(".txt")


class TestNewConfigSections:
    """Sections added for the API and batch solving."""

    def test_api_config_defaults_to_loopback(self):
        # Binding off-loopback should be a deliberate choice, not the default.
        assert config.api.HOST == "127.0.0.1"
        assert 1 <= config.api.PORT <= 65535

    def test_api_auth_is_off_by_default(self):
        assert config.api.KEY == ""

    def test_ssrf_guard_is_on_by_default(self):
        assert config.api.ALLOW_PRIVATE_HOSTS is False

    def test_batch_worker_bounds(self):
        assert config.batch.MAX_WORKERS >= 1
        assert config.batch.MAX_WORKERS <= config.batch.WORKER_LIMIT

    def test_hang_guards_are_configured(self):
        assert config.mouse.PATH_MAX_STEPS > 0
        assert config.solver.SOLVE_TIMEOUT_S >= 0
        assert config.browser.HTTP_MAX_ATTEMPTS >= 1

    def test_to_dict_covers_every_section(self):
        data = config.to_dict()
        for section in ("cloudflare", "browser", "mouse", "solver", "api", "batch"):
            assert section in data
            assert isinstance(data[section], dict)


class TestEnvOverrides:
    """ALAP_<SECTION>_<FIELD> environment overrides."""

    def test_int_override(self, monkeypatch):
        monkeypatch.setenv("ALAP_BROWSER_HTTP_TIMEOUT", "42")
        cfg = load_config(use_file=False)
        assert cfg.browser.HTTP_TIMEOUT == 42
        assert isinstance(cfg.browser.HTTP_TIMEOUT, int)

    def test_float_override(self, monkeypatch):
        monkeypatch.setenv("ALAP_SOLVER_SOLVE_TIMEOUT_S", "12.5")
        assert load_config(use_file=False).solver.SOLVE_TIMEOUT_S == 12.5

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("1", True), ("true", True), ("yes", True), ("on", True), ("0", False), ("no", False)],
    )
    def test_bool_override(self, monkeypatch, raw, expected):
        monkeypatch.setenv("ALAP_API_ALLOW_PRIVATE_HOSTS", raw)
        assert load_config(use_file=False).api.ALLOW_PRIVATE_HOSTS is expected

    def test_string_list_override(self, monkeypatch):
        monkeypatch.setenv("ALAP_SITEKEY_FALSE_POSITIVES", "aa, bb ,cc")
        assert load_config(use_file=False).sitekey.FALSE_POSITIVES == ["aa", "bb", "cc"]

    def test_int_list_override(self, monkeypatch):
        monkeypatch.setenv("ALAP_RETRY_TIMEOUT_RETRY_CODES", "500,503")
        codes = load_config(use_file=False).retry.TIMEOUT_RETRY_CODES
        assert codes == [500, 503]
        assert all(isinstance(code, int) for code in codes)

    def test_api_key_override(self, monkeypatch):
        monkeypatch.setenv("ALAP_API_KEY", "from-env")
        assert load_config(use_file=False).api.KEY == "from-env"

    def test_bad_value_raises(self, monkeypatch):
        monkeypatch.setenv("ALAP_BROWSER_HTTP_TIMEOUT", "not-a-number")
        with pytest.raises(ConfigError):
            load_config(use_file=False)

    def test_unrelated_env_vars_are_ignored(self, monkeypatch):
        monkeypatch.setenv("ALAP_NOT_A_SECTION", "x")
        assert load_config(use_file=False).browser.HTTP_TIMEOUT == 10


class TestYamlConfig:
    """Optional alap-alap.yml file."""

    def test_file_values_are_applied(self, tmp_path):
        path = tmp_path / "alap-alap.yml"
        path.write_text("browser:\n  HTTP_TIMEOUT: 25\napi:\n  PORT: 8123\n", encoding="utf-8")
        cfg = load_config(path, use_env=False)
        assert cfg.browser.HTTP_TIMEOUT == 25
        assert cfg.api.PORT == 8123

    def test_keys_are_case_insensitive(self, tmp_path):
        path = tmp_path / "alap-alap.yml"
        path.write_text("browser:\n  http_timeout: 30\n", encoding="utf-8")
        assert load_config(path, use_env=False).browser.HTTP_TIMEOUT == 30

    def test_env_wins_over_file(self, tmp_path, monkeypatch):
        path = tmp_path / "alap-alap.yml"
        path.write_text("browser:\n  HTTP_TIMEOUT: 25\n", encoding="utf-8")
        monkeypatch.setenv("ALAP_BROWSER_HTTP_TIMEOUT", "99")
        assert load_config(path).browser.HTTP_TIMEOUT == 99

    def test_unknown_section_raises(self, tmp_path):
        path = tmp_path / "alap-alap.yml"
        path.write_text("bogus:\n  X: 1\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="Unknown config section"):
            load_config(path, use_env=False)

    def test_unknown_option_raises(self, tmp_path):
        path = tmp_path / "alap-alap.yml"
        path.write_text("browser:\n  NOPE: 1\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="Unknown option"):
            load_config(path, use_env=False)

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(ConfigError, match="not found"):
            load_config(tmp_path / "absent.yml")

    def test_empty_file_falls_back_to_defaults(self, tmp_path):
        path = tmp_path / "alap-alap.yml"
        path.write_text("", encoding="utf-8")
        assert load_config(path, use_env=False).browser.HTTP_TIMEOUT == 10


class TestConfigValidation:
    """Invalid combinations are rejected at load time."""

    def test_zero_timeout_is_rejected(self, monkeypatch):
        monkeypatch.setenv("ALAP_BROWSER_HTTP_TIMEOUT", "0")
        with pytest.raises(ConfigError, match="HTTP_TIMEOUT"):
            load_config(use_file=False)

    def test_out_of_range_port_is_rejected(self, monkeypatch):
        monkeypatch.setenv("ALAP_API_PORT", "70000")
        with pytest.raises(ConfigError, match="PORT"):
            load_config(use_file=False)

    def test_workers_above_the_limit_are_rejected(self, monkeypatch):
        monkeypatch.setenv("ALAP_BATCH_MAX_WORKERS", "999")
        with pytest.raises(ConfigError, match="WORKER_LIMIT"):
            load_config(use_file=False)

    def test_jitter_out_of_range_is_rejected(self, monkeypatch):
        monkeypatch.setenv("ALAP_RETRY_RETRY_JITTER_PCT", "5")
        with pytest.raises(ConfigError, match="JITTER"):
            load_config(use_file=False)


class TestNoDanglingOptions:
    """Every config option must be read somewhere in src/."""

    def test_all_options_are_used(self):
        # An option that nothing reads is a promise the code does not keep,
        # which is exactly how the dead `--proxy` argument went unnoticed.
        import re
        from dataclasses import fields
        from pathlib import Path

        options = []
        for section in fields(config):
            sub = getattr(config, section.name)
            for option in fields(sub):
                options.append((section.name, option.name))

        src = Path(__file__).resolve().parents[2] / "src"
        blob = "\n".join(
            path.read_text(encoding="utf-8")
            for path in src.rglob("*.py")
            if path.name != "config.py"
        )

        dangling = [
            f"config.{section}.{name}"
            for section, name in options
            if not re.search(rf"\b{re.escape(name)}\b", blob)
        ]

        assert not dangling, f"Config options never read: {', '.join(dangling)}"


class TestRetryCeiling:
    """retry.MAX_RETRIES is an actual ceiling."""

    def test_ceiling_matches_the_api_bound(self):
        from src.models import SolveRequest

        bound = SolveRequest.model_fields["retries"].metadata
        limits = [getattr(item, "le", None) for item in bound]
        assert config.retry.MAX_RETRIES in [limit for limit in limits if limit is not None]

    def test_ceiling_is_applied(self, monkeypatch):
        from src.core.main import AlapAlap

        monkeypatch.setenv("ALAP_RETRY_MAX_RETRIES", "2")
        reloaded = load_config(use_file=False)
        with patch("src.core.main.config", reloaded):
            assert AlapAlap._clamp_attempts(99) == 2

    def test_below_one_becomes_one(self):
        from src.core.main import AlapAlap

        assert AlapAlap._clamp_attempts(0) == 1
        assert AlapAlap._clamp_attempts(-5) == 1
