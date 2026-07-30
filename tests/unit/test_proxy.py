"""Unit tests for proxy parsing.

The ``--proxy`` option used to be stored and then never forwarded anywhere, so
these tests assert on the two shapes consumers actually need rather than just
on the parsed fields.
"""

import pytest

from src.errors import ProxyError
from src.proxy import ProxyRotator, parse_proxy


class TestParseProxy:
    """Test parse_proxy."""

    def test_none_returns_none(self):
        assert parse_proxy(None) is None

    def test_blank_returns_none(self):
        assert parse_proxy("") is None
        assert parse_proxy("   ") is None

    def test_host_and_port(self):
        info = parse_proxy("1.2.3.4:8080")
        assert info is not None
        assert info.scheme == "http"
        assert info.host == "1.2.3.4"
        assert info.port == 8080
        assert info.username is None

    def test_documented_credential_form(self):
        info = parse_proxy("user:pass@host.example:3128")
        assert info is not None
        assert info.username == "user"
        assert info.password == "pass"
        assert info.host == "host.example"
        assert info.port == 3128

    def test_explicit_scheme_is_kept(self):
        assert parse_proxy("socks5://1.2.3.4:1080").scheme == "socks5"
        assert parse_proxy("https://1.2.3.4:443").scheme == "https"

    def test_percent_encoded_credentials_are_decoded(self):
        info = parse_proxy("us%40er:p%40ss@host.example:8080")
        assert info.username == "us@er"
        assert info.password == "p@ss"

    def test_unsupported_scheme_raises(self):
        with pytest.raises(ProxyError, match="scheme"):
            parse_proxy("ftp://1.2.3.4:21")

    def test_invalid_port_raises(self):
        with pytest.raises(ProxyError, match="port"):
            parse_proxy("user:pass@host:port")

    def test_missing_host_raises(self):
        with pytest.raises(ProxyError, match="host"):
            parse_proxy("http://:8080")


class TestProxyShapes:
    """The parsed proxy must serialise for requests and for Playwright."""

    def test_requests_dict_includes_credentials(self):
        info = parse_proxy("user:pass@host.example:8080")
        assert info.as_requests_dict() == {
            "http": "http://user:pass@host.example:8080",
            "https": "http://user:pass@host.example:8080",
        }

    def test_playwright_dict_splits_credentials_out(self):
        # Playwright wants the server URL clean and the credentials separate.
        info = parse_proxy("user:pass@host.example:8080")
        assert info.as_playwright_dict() == {
            "server": "http://host.example:8080",
            "username": "user",
            "password": "pass",
        }

    def test_playwright_dict_without_credentials(self):
        assert parse_proxy("1.2.3.4:8080").as_playwright_dict() == {"server": "http://1.2.3.4:8080"}

    def test_masked_hides_the_password(self):
        masked = parse_proxy("user:sup3rsecret@host.example:8080").masked()
        assert "sup3rsecret" not in masked
        assert "user" in masked


class TestProxyRotator:
    """Round-robin pool used by batch solving."""

    def test_empty_rotator_returns_none(self):
        assert ProxyRotator().next() is None

    def test_cycles_in_order(self):
        rotator = ProxyRotator.from_strings(["1.1.1.1:80", "2.2.2.2:80"])
        assert len(rotator) == 2
        assert rotator.next().host == "1.1.1.1"
        assert rotator.next().host == "2.2.2.2"
        assert rotator.next().host == "1.1.1.1"

    def test_blank_entries_are_skipped(self):
        assert len(ProxyRotator.from_strings(["1.1.1.1:80", "", "  "])) == 1
