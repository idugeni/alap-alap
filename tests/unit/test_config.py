"""Unit tests for config module."""

from src.config import config


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
