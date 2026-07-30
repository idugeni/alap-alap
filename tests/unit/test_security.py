"""Unit tests for the SSRF guard, API key check and rate limiter.

These back the REST API: ``/solve`` and ``/detect`` fetch a caller-supplied URL,
so without :func:`validate_url` anyone able to reach the service could make the
host request its own internal network.
"""

import pytest

from src.errors import UnsafeUrlError
from src.security import (
    RateLimiter,
    check_api_key,
    is_safe_url,
    validate_url,
)


class TestValidateUrl:
    """Test the SSRF guard."""

    def test_public_url_passes(self):
        assert validate_url("https://example.com/login") == "https://example.com/login"

    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1:8080/",
            "http://10.0.0.5/admin",
            "http://192.168.1.1/",
            "http://172.16.0.1/",
            "http://169.254.169.254/latest/meta-data/",
            "http://[::1]/",
            "http://0.0.0.0/",
        ],
    )
    def test_non_public_addresses_are_blocked(self, url):
        with pytest.raises(UnsafeUrlError):
            validate_url(url)

    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "ftp://example.com/x",
            "gopher://example.com/",
            "javascript:alert(1)",
        ],
    )
    def test_non_http_schemes_are_blocked(self, url):
        with pytest.raises(UnsafeUrlError, match="scheme"):
            validate_url(url)

    def test_empty_url_is_blocked(self):
        with pytest.raises(UnsafeUrlError):
            validate_url("")

    def test_missing_host_is_blocked(self):
        with pytest.raises(UnsafeUrlError, match="host"):
            validate_url("http://")

    def test_metadata_hostname_is_blocked(self):
        with pytest.raises(UnsafeUrlError, match="metadata"):
            validate_url("http://metadata.google.internal/")

    def test_allow_private_opens_the_gate(self):
        # Needed for local development against a dev server.
        assert validate_url("http://127.0.0.1:5000/", allow_private=True)

    def test_hostname_resolving_to_loopback_is_blocked(self):
        # DNS rebinding: the name is public but the address is not.
        with pytest.raises(UnsafeUrlError):
            validate_url("http://localhost:8080/")

    def test_is_safe_url_is_the_boolean_form(self):
        assert is_safe_url("https://example.com") is True
        assert is_safe_url("http://127.0.0.1") is False


class TestCheckApiKey:
    """Test the API key comparison."""

    def test_no_expected_key_allows_everything(self):
        assert check_api_key(None, "") is True
        assert check_api_key("anything", None) is True

    def test_matching_key_passes(self):
        assert check_api_key("s3cret", "s3cret") is True

    def test_wrong_key_fails(self):
        assert check_api_key("nope", "s3cret") is False

    def test_missing_key_fails_when_one_is_required(self):
        assert check_api_key(None, "s3cret") is False
        assert check_api_key("", "s3cret") is False

    def test_prefix_of_the_real_key_fails(self):
        assert check_api_key("s3cre", "s3cret") is False


class TestRateLimiter:
    """Test the sliding-window limiter."""

    def test_allows_up_to_the_limit(self):
        limiter = RateLimiter(3, 60)
        assert [limiter.allow("ip") for _ in range(4)] == [True, True, True, False]

    def test_keys_are_independent(self):
        limiter = RateLimiter(1, 60)
        assert limiter.allow("a") is True
        assert limiter.allow("b") is True
        assert limiter.allow("a") is False

    def test_zero_limit_disables_the_limiter(self):
        limiter = RateLimiter(0, 60)
        assert limiter.enabled is False
        assert all(limiter.allow("ip") for _ in range(50))

    def test_retry_after_is_positive_once_blocked(self):
        limiter = RateLimiter(1, 60)
        limiter.allow("ip")
        assert limiter.retry_after("ip") > 0

    def test_retry_after_is_zero_with_room_left(self):
        assert RateLimiter(5, 60).retry_after("ip") == 0.0

    def test_window_expiry_frees_a_slot(self):
        limiter = RateLimiter(1, 0.05)
        assert limiter.allow("ip") is True
        assert limiter.allow("ip") is False
        import time

        time.sleep(0.08)
        assert limiter.allow("ip") is True

    def test_reset_clears_state(self):
        limiter = RateLimiter(1, 60)
        limiter.allow("ip")
        limiter.reset("ip")
        assert limiter.allow("ip") is True
