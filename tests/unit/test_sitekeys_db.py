"""Unit tests for sitekeys database."""

import os
import tempfile

from src.sitekeys_db import SitekeysDB


class TestSitekeysDB:
    """Test SitekeysDB class."""

    def setup_method(self):
        """Create temp database for each test."""
        self.temp_path = tempfile.mktemp(suffix=".json")
        self.db = SitekeysDB(db_path=self.temp_path)

    def teardown_method(self):
        """Cleanup temp database."""
        if os.path.exists(self.temp_path):
            os.remove(self.temp_path)

    def test_add_sitekey(self):
        entry = self.db.add(
            "0x4AAAAAAA1234567890123", "https://example.com", platform_name="Example"
        )
        assert entry.sitekey == "0x4AAAAAAA1234567890123"
        assert entry.platform_name == "Example"
        assert entry.domain == "example.com"

    def test_get_sitekey(self):
        self.db.add("0x4AAAAAAA1234567890123", "https://example.com")
        entry = self.db.get("0x4AAAAAAA1234567890123")
        assert entry is not None
        assert entry.sitekey == "0x4AAAAAAA1234567890123"

    def test_get_all(self):
        self.db.add("0x4AAAAAAA1111111111111", "https://a.com")
        self.db.add("0x4AAAAAAA2222222222222", "https://b.com")
        assert len(self.db.get_all()) == 2

    def test_record_solve(self):
        self.db.add("0x4AAAAAAA1234567890123", "https://example.com")
        self.db.record_solve(
            "0x4AAAAAAA1234567890123", success=True, token="test-token-123", solve_time=5.0
        )
        entry = self.db.get("0x4AAAAAAA1234567890123")
        assert entry.solve_count == 1
        assert entry.success_count == 1
        assert entry.last_token == "test-token-123"
        assert entry.last_solve_time == 5.0

    def test_search(self):
        self.db.add("0x4AAAAAAA1234567890123", "https://etherscan.io", platform_name="Etherscan")
        results = self.db.search("etherscan")
        assert len(results) == 1

    def test_get_active(self):
        self.db.add("0x4AAAAAAA1234567890123", "https://example.com", status="active")
        self.db.add("0x4AAAAAAA9999999999999", "https://other.com", status="inactive")
        active = self.db.get_active()
        assert len(active) == 1
        assert active[0].status == "active"

    def test_export_markdown(self):
        self.db.add("0x4AAAAAAA1234567890123", "https://example.com", platform_name="Example")
        self.db.record_solve("0x4AAAAAAA1234567890123", success=True, token="test-token-12345678")
        md = self.db.export_markdown()
        assert "Example" in md
        assert "0x4AAAAAAA1234567890123"[:20] in md  # truncated sitekey
        assert "test-tok" in md  # redacted token (first 8 chars)
