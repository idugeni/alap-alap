"""Unit tests for SitekeyDetector."""

import dataclasses
from unittest.mock import Mock, patch

import pytest
import requests

from src.detector import SitekeyDetector
from src.errors import ProxyError


class TestSitekeyDetector:
    """Test SitekeyDetector class."""

    def test_init(self):
        """Test detector initialization."""
        detector = SitekeyDetector()
        assert detector.proxy is None
        assert detector.headers is not None

    def test_init_with_proxy(self):
        """Test detector initialization with proxy."""
        proxy = "user:pass@host.example:8080"
        detector = SitekeyDetector(proxy=proxy)
        assert detector.proxy == proxy
        # The proxy must actually reach the HTTP layer, not just be stored.
        assert detector.proxy_info is not None
        assert detector.session.proxies["https"] == "http://user:pass@host.example:8080"

    def test_init_with_invalid_proxy_raises(self):
        """An unparseable proxy fails loudly instead of being ignored."""
        with pytest.raises(ProxyError):
            SitekeyDetector(proxy="user:pass@host:not-a-port")

    def test_extract_from_url(self):
        """Test sitekey extraction from URL parameters."""
        detector = SitekeyDetector()

        url = "https://example.com?sitekey=0x4AAAAAAAQV1p8gT2jN3m4"
        result = detector._extract_from_url(url)
        assert result == "0x4AAAAAAAQV1p8gT2jN3m4"

    def test_extract_from_url_no_sitekey(self):
        """Test sitekey extraction when no sitekey in URL."""
        detector = SitekeyDetector()

        url = "https://example.com"
        result = detector._extract_from_url(url)
        assert result is None

    def test_is_valid_sitekey(self):
        """Test sitekey validation."""
        detector = SitekeyDetector()

        # Valid sitekeys
        assert detector._is_valid_sitekey("0x4AAAAAAAQV1p8gT2jN3m4") is True
        assert detector._is_valid_sitekey("0x4AAAAAAAyCRuAotEBXQqMm") is True

        # Invalid sitekeys
        assert detector._is_valid_sitekey("invalidsitekey") is False
        assert detector._is_valid_sitekey("test") is False
        assert detector._is_valid_sitekey("short") is False
        assert detector._is_valid_sitekey("") is False
        assert detector._is_valid_sitekey(None) is False

    def test_sitekey_patterns(self):
        """Test sitekey pattern matching."""
        detector = SitekeyDetector()

        html = '<div class="cf-turnstile" data-sitekey="0x4AAAAAAAQV1p8gT2jN3m4"></div>'

        for pattern in detector.SITEKEY_PATTERNS:
            match = pattern.search(html)
            if match:
                assert match.group(1) == "0x4AAAAAAAQV1p8gT2jN3m4"
                break


class FakeResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(self, body="", status_code=200, url="https://example.com"):
        self.body = body.encode("utf-8") if isinstance(body, str) else body
        self.status_code = status_code
        self.url = url
        self.encoding = "utf-8"
        self.closed = False

    def iter_content(self, chunk_size=65536):
        for start in range(0, len(self.body), chunk_size):
            yield self.body[start : start + chunk_size]

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def close(self):
        self.closed = True


def attach_session(detector, responses):
    """Give a detector a fake session that returns queued responses."""
    session = Mock()
    session.get = Mock(side_effect=responses)
    session.proxies = {}
    detector._session = session
    return session


class TestHtmlLayer:
    """The static HTML detection layer."""

    def test_sitekey_found_in_html(self):
        detector = SitekeyDetector()
        html = '<div class="cf-turnstile" data-sitekey="0x4AAAAAAAQV1p8gT2jN3m4"></div>'
        attach_session(detector, [FakeResponse(html)])
        assert detector._extract_from_html("https://example.com") == "0x4AAAAAAAQV1p8gT2jN3m4"

    def test_sitekey_found_in_json_blob(self):
        detector = SitekeyDetector()
        attach_session(detector, [FakeResponse('{"sitekey": "0x4AAAAAAAQV1p8gT2jN3m4"}')])
        assert detector._extract_from_html("https://example.com") == "0x4AAAAAAAQV1p8gT2jN3m4"

    def test_sitekey_found_in_turnstile_iframe_url(self):
        detector = SitekeyDetector()
        html = (
            '<iframe src="https://challenges.cloudflare.com/cdn-cgi/challenge-platform/'
            'turnstile/if/ov2?sitekey=0x4AAAAAAAQV1p8gT2jN3m4&theme=light"></iframe>'
        )
        attach_session(detector, [FakeResponse(html)])
        assert detector._extract_from_html("https://example.com") == "0x4AAAAAAAQV1p8gT2jN3m4"

    def test_template_placeholder_is_not_accepted(self):
        detector = SitekeyDetector()
        attach_session(detector, [FakeResponse('data-sitekey="{{ TURNSTILE_SITEKEY }}"')])
        assert detector._extract_from_html("https://example.com") is None

    def test_no_sitekey_returns_none(self):
        detector = SitekeyDetector()
        attach_session(detector, [FakeResponse("<html><body>nothing here</body></html>")])
        assert detector._extract_from_html("https://example.com") is None

    def test_response_is_always_closed(self):
        detector = SitekeyDetector()
        response = FakeResponse("<html></html>")
        attach_session(detector, [response])
        detector._extract_from_html("https://example.com")
        assert response.closed is True

    def test_oversized_response_is_truncated(self):
        detector = SitekeyDetector()
        # The sitekey sits past the byte cap, so it must not be found.
        padding = "x" * (detector._browser.HTTP_MAX_RESPONSE_BYTES + 100)
        body = padding + 'data-sitekey="0x4AAAAAAAQV1p8gT2jN3m4"'
        attach_session(detector, [FakeResponse(body)])
        assert detector._extract_from_html("https://example.com") is None


class TestHttpRetry:
    """Transient failures are retried, permanent ones are not."""

    def _fast_detector(self):
        """A detector whose backoff is effectively instant."""
        detector = SitekeyDetector()
        detector._browser = dataclasses.replace(
            detector._browser,
            HTTP_MAX_ATTEMPTS=3,
            HTTP_RETRY_BACKOFF_S=0.0,
            HTTP_RETRY_BACKOFF_MAX_S=0.0,
        )
        return detector

    def test_retries_a_429_then_succeeds(self):
        detector = self._fast_detector()
        html = 'data-sitekey="0x4AAAAAAAQV1p8gT2jN3m4"'
        session = attach_session(detector, [FakeResponse(status_code=429), FakeResponse(html)])
        assert detector._extract_from_html("https://example.com") == "0x4AAAAAAAQV1p8gT2jN3m4"
        assert session.get.call_count == 2

    def test_retries_a_503_then_succeeds(self):
        detector = self._fast_detector()
        html = 'data-sitekey="0x4AAAAAAAQV1p8gT2jN3m4"'
        attach_session(detector, [FakeResponse(status_code=503), FakeResponse(html)])
        assert detector._extract_from_html("https://example.com") == "0x4AAAAAAAQV1p8gT2jN3m4"

    def test_gives_up_after_max_attempts(self):
        detector = self._fast_detector()
        session = attach_session(detector, [FakeResponse(status_code=429)] * 5)
        assert detector._extract_from_html("https://example.com") is None
        assert session.get.call_count == 3

    def test_connection_error_is_retried(self):
        detector = self._fast_detector()
        html = 'data-sitekey="0x4AAAAAAAQV1p8gT2jN3m4"'
        session = attach_session(detector, [requests.ConnectionError("reset"), FakeResponse(html)])
        assert detector._extract_from_html("https://example.com") == "0x4AAAAAAAQV1p8gT2jN3m4"
        assert session.get.call_count == 2

    def test_404_is_not_retried(self):
        detector = self._fast_detector()
        session = attach_session(detector, [FakeResponse(status_code=404)] * 3)
        assert detector._extract_from_html("https://example.com") is None
        assert session.get.call_count == 1

    def test_failure_returns_none_rather_than_raising(self):
        detector = self._fast_detector()
        attach_session(detector, [requests.Timeout("too slow")] * 5)
        assert detector._extract_from_html("https://example.com") is None


class TestSsrfIntegration:
    """The detector refuses unsafe targets when told to."""

    def test_private_target_is_refused_when_disallowed(self):
        detector = SitekeyDetector(allow_private_hosts=False)
        assert detector.detect_with_method("http://127.0.0.1:8080/") == (None, None)

    def test_private_target_is_allowed_by_default(self):
        # Direct CLI and library use may legitimately target localhost.
        detector = SitekeyDetector()
        attach_session(detector, [FakeResponse("<html></html>")])
        with patch.object(detector, "_extract_with_browser", return_value=None):
            detector.detect_with_method("http://127.0.0.1:8080/")
        # Reaching the HTTP layer at all proves the guard did not fire.
        assert detector._session.get.called

    def test_bad_scheme_is_refused(self):
        detector = SitekeyDetector(allow_private_hosts=False)
        assert detector.detect("file:///etc/passwd") is None


class TestDetectionOrder:
    """The layers run cheapest first."""

    def test_url_layer_short_circuits(self):
        detector = SitekeyDetector()
        session = attach_session(detector, [FakeResponse("<html></html>")])
        sitekey, method = detector.detect_with_method(
            "https://example.com/?sitekey=0x4AAAAAAAQV1p8gT2jN3m4"
        )
        assert (sitekey, method) == ("0x4AAAAAAAQV1p8gT2jN3m4", "url")
        # No HTTP request was needed.
        assert session.get.call_count == 0

    def test_html_layer_runs_before_the_browser(self):
        detector = SitekeyDetector()
        attach_session(detector, [FakeResponse('data-sitekey="0x4AAAAAAAQV1p8gT2jN3m4"')])
        with patch.object(detector, "_extract_with_browser") as browser:
            sitekey, method = detector.detect_with_method("https://example.com/")
        assert (sitekey, method) == ("0x4AAAAAAAQV1p8gT2jN3m4", "html")
        browser.assert_not_called()

    def test_browser_is_the_last_resort(self):
        detector = SitekeyDetector()
        attach_session(detector, [FakeResponse("<html></html>")])
        with patch.object(detector, "_extract_with_browser") as browser:
            browser.return_value = "0x4AAAAAAAQV1p8gT2jN3m4"
            detector.last_method = "dom"
            sitekey, _method = detector.detect_with_method("https://example.com/")
        assert sitekey == "0x4AAAAAAAQV1p8gT2jN3m4"
        browser.assert_called_once()

    def test_nothing_found_returns_a_pair_of_nones(self):
        detector = SitekeyDetector()
        attach_session(detector, [FakeResponse("<html></html>")])
        with patch.object(detector, "_extract_with_browser", return_value=None):
            assert detector.detect_with_method("https://example.com/") == (None, None)


class TestBundlePrioritisation:
    """JS bundle ordering and deduplication."""

    def test_turnstile_bundles_come_first(self):
        detector = SitekeyDetector()
        ordered = detector._prioritize_bundles(
            [
                "https://a.com/vendor.js",
                "https://a.com/turnstile-widget.js",
                "https://a.com/login.js",
            ]
        )
        assert "turnstile" in ordered[0]

    def test_duplicates_are_removed(self):
        detector = SitekeyDetector()
        ordered = detector._prioritize_bundles(["https://a.com/x.js", "https://a.com/x.js"])
        assert len(ordered) == 1

    def test_bundle_pattern_matching(self):
        detector = SitekeyDetector()
        content = 'var cfg={sitekey:"0x4AAAAAAAQV1p8gT2jN3m4"};'
        assert detector._search_bundle_patterns(content) == "0x4AAAAAAAQV1p8gT2jN3m4"

    def test_bundle_without_a_key_returns_none(self):
        detector = SitekeyDetector()
        assert detector._search_bundle_patterns("var x = 1;") is None


class TestSessionLifecycle:
    """HTTP session management."""

    def test_session_is_created_lazily(self):
        detector = SitekeyDetector()
        assert detector._session is None
        assert detector.session is not None
        assert detector._session is not None

    def test_session_is_reused(self):
        detector = SitekeyDetector()
        assert detector.session is detector.session

    def test_close_releases_the_session(self):
        detector = SitekeyDetector()
        detector.session  # noqa: B018 - force creation
        detector.close()
        assert detector._session is None

    def test_context_manager_closes(self):
        with SitekeyDetector() as detector:
            detector.session  # noqa: B018 - force creation
        assert detector._session is None

    def test_user_agent_header_is_set(self):
        assert "User-Agent" in SitekeyDetector().headers


class TestSitekeyValidationEdgeCases:
    """Extra guards on _is_valid_sitekey."""

    def test_overly_long_key_is_rejected(self):
        detector = SitekeyDetector()
        assert detector._is_valid_sitekey("0x4" + "a" * 500) is False

    def test_whitespace_is_rejected(self):
        detector = SitekeyDetector()
        assert detector._is_valid_sitekey("0x4AAAAAAA QV1p8gT2jN3m4") is False

    def test_template_syntax_is_rejected(self):
        detector = SitekeyDetector()
        assert detector._is_valid_sitekey("${TURNSTILE_SITEKEY_VALUE}") is False
        assert detector._is_valid_sitekey("{{turnstile_sitekey_here}}") is False

    def test_non_string_is_rejected(self):
        detector = SitekeyDetector()
        assert detector._is_valid_sitekey(12345) is False

    def test_known_false_positive_is_rejected(self):
        detector = SitekeyDetector()
        assert detector._is_valid_sitekey("your-sitekey-goes-here") is False


class TestUrlLayerVariants:
    """Parameter name handling in the URL layer."""

    def test_site_key_underscore_variant(self):
        detector = SitekeyDetector()
        result = detector._extract_from_url("https://a.com/?site_key=0x4AAAAAAAQV1p8gT2jN3m4")
        assert result == "0x4AAAAAAAQV1p8gT2jN3m4"

    def test_fragment_parameters(self):
        detector = SitekeyDetector()
        result = detector._extract_from_url("https://a.com/#sitekey=0x4AAAAAAAQV1p8gT2jN3m4")
        assert result == "0x4AAAAAAAQV1p8gT2jN3m4"

    def test_empty_parameter_is_ignored(self):
        detector = SitekeyDetector()
        assert detector._extract_from_url("https://a.com/?sitekey=") is None

    def test_malformed_url_does_not_raise(self):
        detector = SitekeyDetector()
        assert detector._extract_from_url("not a url at all") is None
