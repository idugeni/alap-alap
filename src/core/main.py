"""
Alap-Alap Core Module

Main entry point for the Alap-Alap captcha solver.
"""

import time
from typing import Optional
from loguru import logger

from ..detector import SitekeyDetector
from ..solver import CaptchaSolver


class AlapAlap:
    """
    Alap-Alap - Cloudflare Turnstile Captcha Solver

    A high-performance captcha solver that automatically detects sitekeys
    and solves Cloudflare Turnstile challenges using Camoufox for
    fingerprint resistance.

    Usage:
        >>> from src.core import AlapAlap
        >>> with AlapAlap() as alap:
        ...     result = alap.solve("https://example.com/login")
        ...     print(result)
    """

    def __init__(self, proxy: Optional[str] = None, headless: bool = True):
        """
        Initialize Alap-Alap solver.

        Args:
            proxy: Optional proxy string (format: user:pass@host:port)
            headless: Run browser in headless mode (default: True)
        """
        self.proxy = proxy
        self.headless = headless
        self.detector = SitekeyDetector(proxy=proxy)
        self.solver = None

    def __enter__(self):
        self.solver = CaptchaSolver(proxy=self.proxy, headless=self.headless)
        self.solver.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.solver:
            self.solver.stop()

    def solve(self, url: str, invisible: bool = True) -> dict:
        """
        Solve Turnstile captcha for a given URL.

        Args:
            url: Target URL to solve captcha on
            invisible: Use invisible mode (default: True)

        Returns:
            dict with 'success', 'token', 'sitekey', 'error', 'time' keys
        """
        start_time = time.time()

        sitekey = self.detector.detect(url)
        if not sitekey:
            logger.warning(f"No sitekey found for {url}")
            return {
                "success": False,
                "token": None,
                "sitekey": None,
                "error": "Could not detect sitekey",
                "time": time.time() - start_time
            }

        logger.info(f"Solving captcha for {url}")
        token = self.solver.solve(url, sitekey, invisible)
        elapsed = time.time() - start_time

        if token:
            logger.success(f"Solved in {elapsed:.1f}s")
            return {
                "success": True,
                "token": token,
                "sitekey": sitekey,
                "error": None,
                "time": elapsed
            }
        else:
            logger.error(f"Solver failed for {url}")
            return {
                "success": False,
                "token": None,
                "sitekey": sitekey,
                "error": "Solver failed",
                "time": elapsed
            }

    def solve_with_sitekey(self, url: str, sitekey: str, invisible: bool = True) -> dict:
        """
        Solve Turnstile captcha with known sitekey.

        Args:
            url: Target URL
            sitekey: Known sitekey
            invisible: Use invisible mode (default: True)

        Returns:
            dict with 'success', 'token', 'error', 'time' keys
        """
        start_time = time.time()

        logger.info(f"Solving captcha for {url} with sitekey {sitekey[:20]}...")
        token = self.solver.solve(url, sitekey, invisible)
        elapsed = time.time() - start_time

        if token:
            logger.success(f"Solved in {elapsed:.1f}s")
            return {
                "success": True,
                "token": token,
                "sitekey": sitekey,
                "error": None,
                "time": elapsed
            }
        else:
            logger.error(f"Solver failed for {url}")
            return {
                "success": False,
                "token": None,
                "sitekey": sitekey,
                "error": "Solver failed",
                "time": elapsed
            }
