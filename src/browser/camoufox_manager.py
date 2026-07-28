"""
Alap-Alap Browser Manager

Manages Camoufox browser instances for anti-fingerprint browsing.
"""

from typing import Optional


class CamoufoxManager:
    """
    Manage Camoufox browser instances.

    Provides a clean interface for creating and managing
    Camoufox browsers with consistent configuration.
    """

    def __init__(self, headless: bool = True, proxy: Optional[str] = None):
        self.headless = headless
        self.proxy = proxy
        self._context = None
        self._browser = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()

    def start(self):
        """Start the Camoufox browser."""
        try:
            from camoufox.sync_api import Camoufox
            self._context = Camoufox(headless=self.headless)
            self._browser = self._context.__enter__()
        except ImportError:
            raise ImportError("Camoufox is required. Install with: pip install camoufox")

    def stop(self):
        """Stop the Camoufox browser."""
        if self._context:
            self._context.__exit__(None, None, None)
            self._context = None
            self._browser = None

    @property
    def browser(self):
        """Get the browser instance."""
        if self._browser is None:
            raise RuntimeError("Browser not started. Call start() first.")
        return self._browser

    def new_page(self):
        """Create a new page."""
        return self.browser.new_context()
