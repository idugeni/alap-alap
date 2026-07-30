"""Unit tests for sitekeys database."""

import json
import os
import tempfile
import threading

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


class TestTokenRedaction:
    """Tokens are credentials, so they are truncated on disk."""

    def setup_method(self):
        self.temp_path = tempfile.mktemp(suffix=".json")
        self.db = SitekeysDB(db_path=self.temp_path)

    def teardown_method(self):
        if os.path.exists(self.temp_path):
            os.remove(self.temp_path)

    def test_full_token_stays_in_memory(self):
        self.db.add("0x4AAAAAAA1234567890123", "https://example.com")
        self.db.record_solve("0x4AAAAAAA1234567890123", True, token="full-token-abcdef123456")
        assert self.db.get("0x4AAAAAAA1234567890123").last_token == "full-token-abcdef123456"

    def test_disk_copy_is_redacted(self):
        self.db.add("0x4AAAAAAA1234567890123", "https://example.com")
        self.db.record_solve("0x4AAAAAAA1234567890123", True, token="full-token-abcdef123456")

        with open(self.temp_path, encoding="utf-8") as handle:
            stored = json.load(handle)["0x4AAAAAAA1234567890123"]["last_token"]

        assert stored != "full-token-abcdef123456"
        assert "..." in stored

    def test_token_preview_shape(self):
        self.db.add("0x4AAAAAAA1234567890123", "https://example.com")
        self.db.record_solve("0x4AAAAAAA1234567890123", True, token="abcdefghijklmnop")
        entry = self.db.get("0x4AAAAAAA1234567890123")
        assert entry.token_preview(8) == "abcdefgh...mnop"

    def test_short_token_is_not_mangled(self):
        self.db.add("0x4AAAAAAA1234567890123", "https://example.com")
        self.db.record_solve("0x4AAAAAAA1234567890123", True, token="short")
        assert self.db.get("0x4AAAAAAA1234567890123").token_preview(8) == "short"


class TestPersistenceRobustness:
    """Loading must survive bad and future-shaped files."""

    def test_corrupt_file_is_quarantined_not_wiped(self, tmp_path):
        path = tmp_path / "db.json"
        path.write_text("{not valid json", encoding="utf-8")

        db = SitekeysDB(db_path=str(path))

        assert len(db) == 0
        # The unreadable original is preserved for manual recovery.
        assert list(tmp_path.glob("*.corrupt-*.json"))

    def test_unknown_fields_are_ignored(self, tmp_path):
        path = tmp_path / "db.json"
        path.write_text(
            json.dumps(
                {
                    "0x4KEY": {
                        "sitekey": "0x4KEY",
                        "url": "https://a.com",
                        "domain": "a.com",
                        "platform_name": "A",
                        "status": "active",
                        "first_seen": "2026-01-01T00:00:00+00:00",
                        "last_seen": "2026-01-01T00:00:00+00:00",
                        "field_from_a_newer_version": 123,
                    }
                }
            ),
            encoding="utf-8",
        )

        assert len(SitekeysDB(db_path=str(path))) == 1

    def test_missing_file_starts_empty(self, tmp_path):
        assert len(SitekeysDB(db_path=str(tmp_path / "absent.json"))) == 0

    def test_no_temp_files_are_left_behind(self, tmp_path):
        db = SitekeysDB(db_path=str(tmp_path / "db.json"))
        for index in range(10):
            db.add(f"0x4AAAAAAA{index:013d}", f"https://d{index}.com")
        assert not list(tmp_path.glob("*.tmp"))


class TestConcurrentWrites:
    """The REST API can write from several threads at once."""

    def test_parallel_adds_all_land(self, tmp_path):
        path = tmp_path / "db.json"
        db = SitekeysDB(db_path=str(path))

        def worker(worker_id):
            for index in range(20):
                db.add(
                    f"0x4AAAAAAA{worker_id:02d}{index:02d}000000000", f"https://d{worker_id}.com"
                )

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert len(db) == 160
        # The file must still be parseable, not a half-written mess.
        with open(path, encoding="utf-8") as handle:
            assert len(json.load(handle)) == 160


class TestStatusTransitions:
    """Status bookkeeping."""

    def setup_method(self):
        self.temp_path = tempfile.mktemp(suffix=".json")
        self.db = SitekeysDB(db_path=self.temp_path)

    def teardown_method(self):
        if os.path.exists(self.temp_path):
            os.remove(self.temp_path)

    def test_success_marks_active(self):
        self.db.add("0x4A" + "1" * 20, "https://a.com")
        self.db.record_solve("0x4A" + "1" * 20, True, token="t")
        assert self.db.get("0x4A" + "1" * 20).status == "active"

    def test_first_failure_marks_inactive(self):
        self.db.add("0x4A" + "2" * 20, "https://a.com")
        self.db.record_solve("0x4A" + "2" * 20, False)
        assert self.db.get("0x4A" + "2" * 20).status == "inactive"

    def test_a_previously_solved_key_is_not_demoted(self):
        key = "0x4A" + "3" * 20
        self.db.add(key, "https://a.com")
        self.db.record_solve(key, True, token="t")
        self.db.record_solve(key, False)
        assert self.db.get(key).status == "active"

    def test_record_result_does_not_demote_a_working_key(self):
        key = "0x4A" + "4" * 20
        self.db.record_result("https://a.com", {"success": True, "sitekey": key, "token": "t"})
        self.db.record_result(
            "https://a.com", {"success": False, "sitekey": key, "error": "Solver failed"}
        )
        assert self.db.get(key).status == "active"

    def test_record_result_without_a_sitekey_is_a_noop(self):
        assert self.db.record_result("https://a.com", {"success": False, "sitekey": None}) is None
        assert len(self.db) == 0

    def test_invalid_status_falls_back_to_unknown(self):
        entry = self.db.add("0x4A" + "5" * 20, "https://a.com", status="bogus")
        assert entry.status == "unknown"


class TestQueriesAndExports:
    """Reporting helpers."""

    def setup_method(self):
        self.temp_path = tempfile.mktemp(suffix=".json")
        self.db = SitekeysDB(db_path=self.temp_path)
        self.db.add("0x4A" + "1" * 20, "https://etherscan.io/l", platform_name="Etherscan")
        self.db.record_solve("0x4A" + "1" * 20, True, token="tok-123456789", solve_time=4.0)
        self.db.add("0x4A" + "2" * 20, "https://other.com/l", platform_name="Other")

    def teardown_method(self):
        if os.path.exists(self.temp_path):
            os.remove(self.temp_path)

    def test_stats(self):
        stats = self.db.stats()
        assert stats["total_sitekeys"] == 2
        assert stats["active_sitekeys"] == 1
        assert stats["total_domains"] == 2
        assert stats["success_rate"] == 1.0
        assert stats["avg_solve_time"] == 4.0

    def test_search_matches_platform_name(self):
        assert len(self.db.search("Etherscan")) == 1

    def test_search_is_case_insensitive(self):
        assert len(self.db.search("ETHERSCAN")) == 1

    def test_get_by_domain(self):
        assert len(self.db.get_by_domain("etherscan.io")) == 1

    def test_csv_export_has_a_header_and_rows(self):
        lines = self.db.export_csv().strip().splitlines()
        assert lines[0].startswith("platform_name,")
        assert len(lines) == 3

    def test_json_export_is_parseable(self):
        assert len(json.loads(self.db.export_json())) == 2

    def test_markdown_export_redacts_tokens(self):
        markdown = self.db.export_markdown()
        assert "tok-1234" in markdown
        assert "tok-123456789" not in markdown

    def test_remove(self):
        assert self.db.remove("0x4A" + "1" * 20) is True
        assert self.db.remove("0x4A" + "1" * 20) is False
        assert len(self.db) == 1

    def test_prune_needs_criteria(self):
        assert self.db.prune() == 0
        assert len(self.db) == 2

    def test_prune_failed_only(self):
        assert self.db.prune(only_failed=True) == 1
        assert len(self.db) == 1

    def test_contains(self):
        assert ("0x4A" + "1" * 20) in self.db
        assert "nope" not in self.db

    def test_success_rate_is_zero_without_attempts(self):
        assert self.db.get("0x4A" + "2" * 20).success_rate == 0.0


class TestTokenExpiry:
    """Turnstile tokens expire in about five minutes."""

    def setup_method(self):
        self.temp_path = tempfile.mktemp(suffix=".json")
        self.db = SitekeysDB(db_path=self.temp_path)
        self.key = "0x4AAAAAAA1234567890123"

    def teardown_method(self):
        if os.path.exists(self.temp_path):
            os.remove(self.temp_path)

    def test_no_token_means_no_verdict(self):
        self.db.add(self.key, "https://example.com")
        entry = self.db.get(self.key)
        assert entry.token_age is None
        assert entry.token_expires_in is None
        assert entry.token_is_fresh is False

    def test_a_fresh_token_is_reported_fresh(self):
        self.db.add(self.key, "https://example.com")
        self.db.record_solve(self.key, True, token="tok-abcdef123456")
        entry = self.db.get(self.key)
        assert entry.token_obtained_at
        assert entry.token_age is not None
        assert entry.token_age < 5
        assert entry.token_is_fresh is True

    def test_expiry_countdown_shrinks(self):
        from src.config import config

        self.db.add(self.key, "https://example.com")
        self.db.record_solve(self.key, True, token="tok-abcdef123456")
        remaining = self.db.get(self.key).token_expires_in
        assert 0 < remaining <= config.storage.TOKEN_TTL_S

    def test_an_old_token_is_stale(self):
        from datetime import datetime, timedelta, timezone

        self.db.add(self.key, "https://example.com")
        self.db.record_solve(self.key, True, token="tok-abcdef123456")

        entry = self.db.get(self.key)
        entry.token_obtained_at = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

        assert entry.token_is_fresh is False
        assert entry.token_expires_in < 0

    def test_a_failed_solve_does_not_refresh_the_timestamp(self):
        self.db.add(self.key, "https://example.com")
        self.db.record_solve(self.key, True, token="tok-abcdef123456")
        obtained = self.db.get(self.key).token_obtained_at

        self.db.record_solve(self.key, False)
        assert self.db.get(self.key).token_obtained_at == obtained

    def test_unparseable_timestamp_is_not_fresh(self):
        self.db.add(self.key, "https://example.com")
        self.db.record_solve(self.key, True, token="tok-abcdef123456")
        entry = self.db.get(self.key)
        entry.token_obtained_at = "not a date"
        assert entry.token_age is None
        assert entry.token_is_fresh is False

    def test_stats_counts_fresh_tokens(self):
        self.db.add(self.key, "https://example.com")
        self.db.record_solve(self.key, True, token="tok-abcdef123456")
        assert self.db.stats()["fresh_tokens"] == 1

    def test_get_fresh_tokens(self):
        self.db.add(self.key, "https://example.com")
        self.db.record_solve(self.key, True, token="tok-abcdef123456")
        self.db.add("0x4AAAAAAA9999999999999", "https://other.com")
        assert len(self.db.get_fresh_tokens()) == 1

    def test_timestamp_survives_a_reload(self):
        self.db.add(self.key, "https://example.com")
        self.db.record_solve(self.key, True, token="tok-abcdef123456")

        reloaded = SitekeysDB(db_path=self.temp_path)
        assert reloaded.get(self.key).token_obtained_at
