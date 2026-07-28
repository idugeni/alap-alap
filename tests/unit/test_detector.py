"""Unit tests for SitekeyDetector."""

from src.detector import SitekeyDetector


class TestSitekeyDetector:
    """Test SitekeyDetector class."""

    def test_init(self):
        """Test detector initialization."""
        detector = SitekeyDetector()
        assert detector.proxy is None
        assert detector.headers is not None

    def test_init_with_proxy(self):
        """Test detector initialization with proxy."""
        proxy = "user:pass@host:port"
        detector = SitekeyDetector(proxy=proxy)
        assert detector.proxy == proxy

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
