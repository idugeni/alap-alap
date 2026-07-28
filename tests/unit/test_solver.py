"""Unit tests for CaptchaSolver."""

from src.solver import CaptchaSolver


class TestCaptchaSolver:
    """Test CaptchaSolver class."""

    def test_init(self):
        """Test solver initialization."""
        solver = CaptchaSolver()
        assert solver.proxy is None
        assert solver.headless is True
        assert solver.browser is None

    def test_init_with_proxy(self):
        """Test solver initialization with proxy."""
        proxy = "user:pass@host:port"
        solver = CaptchaSolver(proxy=proxy, headless=False)
        assert solver.proxy == proxy
        assert solver.headless is False

    def test_get_mouse_path(self):
        """Test mouse path calculation."""
        solver = CaptchaSolver()
        
        path = solver._get_mouse_path(0, 0, 100, 100)
        
        assert isinstance(path, list)
        assert len(path) > 0
        assert path[-1] == (100, 100) or (abs(path[-1][0] - 100) <= 3 and abs(path[-1][1] - 100) <= 3)

    def test_get_mouse_path_same_point(self):
        """Test mouse path when start equals end."""
        solver = CaptchaSolver()
        
        path = solver._get_mouse_path(50, 50, 50, 50)
        
        assert isinstance(path, list)
        assert len(path) == 0

    def test_build_page_data(self):
        """Test page data building."""
        solver = CaptchaSolver()
        
        sitekey = "0x4AAAAAAAQV1p8gT2jN3m4"
        page_data = solver._build_page_data(sitekey)
        
        assert sitekey in page_data
        assert "cf-turnstile" in page_data
