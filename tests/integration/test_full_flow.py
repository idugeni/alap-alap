"""Integration tests for full Alap-Alap flow."""

from unittest.mock import Mock

import pytest

from src.core import AlapAlap


@pytest.mark.integration
class TestFullFlow:
    """Test full captcha solving flow."""

    def test_alap_alap_context_manager(self):
        """Test Alap-Alap context manager."""
        with AlapAlap(headless=True) as alap:
            assert alap.solver is not None

    def test_solve_with_mock(self):
        """Test solve method with mocked solver."""
        with AlapAlap(headless=True) as alap:
            # Mock the detector and solver
            alap.detector.detect = Mock(return_value="0x4AAAAAAAQV1p8gT2jN3m4")
            alap.solver.solve = Mock(return_value="mock-token-12345")

            result = alap.solve("https://example.com/login")

            assert result["success"] is True
            assert result["token"] == "mock-token-12345"
            assert result["sitekey"] == "0x4AAAAAAAQV1p8gT2jN3m4"

    def test_solve_failure(self):
        """Test solve method when detection fails."""
        with AlapAlap(headless=True) as alap:
            # Mock detector to return None
            alap.detector.detect = Mock(return_value=None)

            result = alap.solve("https://example.com/login")

            assert result["success"] is False
            assert result["token"] is None
            assert "sitekey" in result

    def test_solve_with_sitekey(self):
        """Test solve with known sitekey."""
        with AlapAlap(headless=True) as alap:
            # Mock solver
            alap.solver.solve = Mock(return_value="mock-token-12345")

            result = alap.solve_with_sitekey("https://example.com/login", "0x4AAAAAAAQV1p8gT2jN3m4")

            assert result["success"] is True
            assert result["token"] == "mock-token-12345"
