"""Unit tests for the Typer CLI.

Dependency checks and the browser are patched out, so no test here installs
anything or launches Camoufox.
"""

import json
from unittest.mock import patch

import pytest
import typer
from typer.testing import CliRunner

from src import cli
from src.sitekeys_db import SitekeysDB

VALID_SITEKEY = "0x4AAAAAAAQV1p8gT2jN3m4"

runner = CliRunner()


@pytest.fixture
def isolated_db(tmp_path):
    """Point the CLI at a throwaway database."""
    db = SitekeysDB(db_path=str(tmp_path / "db.json"))
    with patch.object(cli, "sitekeys_db", db):
        yield db


@pytest.fixture
def no_dependency_check():
    """Never shell out to pip during tests."""
    with patch.object(cli, "ensure_dependencies", lambda **_kwargs: None):
        yield


@pytest.fixture
def results_file(tmp_path):
    return tmp_path / "results.txt"


def make_fake_alap(result):
    """Build an AlapAlap stand-in that returns a fixed result."""

    class FakeAlap:
        last_kwargs: dict = {}

        def __init__(self, *args, **kwargs):
            FakeAlap.last_kwargs = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def solve(self, url, invisible=True, retries=1, timeout=None):
            FakeAlap.last_kwargs = {"invisible": invisible, "retries": retries, "timeout": timeout}
            return result

        def solve_with_sitekey(self, url, sitekey, invisible=True, retries=1, timeout=None):
            FakeAlap.last_kwargs = {"invisible": invisible, "retries": retries, "timeout": timeout}
            return result

    return FakeAlap


SUCCESS = {
    "success": True,
    "token": "tok-" + "x" * 80,
    "sitekey": VALID_SITEKEY,
    "error": None,
    "time": 1.5,
    "attempts": 1,
}

FAILURE = {
    "success": False,
    "token": None,
    "sitekey": VALID_SITEKEY,
    "error": "Solver failed",
    "time": 2.0,
    "attempts": 1,
}


class TestHelp:
    """The CLI surface."""

    def test_help_lists_every_command(self):
        result = runner.invoke(cli.app, ["--help"])
        assert result.exit_code == 0
        for command in ("solve", "batch", "detect", "sitekeys", "health", "info", "config"):
            assert command in result.output

    def test_help_does_not_install_anything(self):
        # ensure_dependencies used to run at import time, so `--help` could
        # trigger pip and a browser download.
        with patch("subprocess.check_call") as check_call:
            runner.invoke(cli.app, ["--help"])
        check_call.assert_not_called()


class TestSolveCommand:
    """The solve command."""

    def test_success(self, isolated_db, no_dependency_check, results_file):
        with patch.object(cli, "AlapAlap", make_fake_alap(SUCCESS)):
            result = runner.invoke(
                cli.app, ["solve", "https://example.com/login", "-o", str(results_file)]
            )
        assert result.exit_code == 0
        assert results_file.exists()

    def test_failure_exits_nonzero(self, isolated_db, no_dependency_check, results_file):
        with patch.object(cli, "AlapAlap", make_fake_alap(FAILURE)):
            result = runner.invoke(
                cli.app, ["solve", "https://example.com/login", "-o", str(results_file)]
            )
        assert result.exit_code == 1

    @pytest.mark.parametrize("retries", ["0", "-3"])
    def test_non_positive_retries_does_not_crash(
        self, isolated_db, no_dependency_check, results_file, retries
    ):
        # This used to raise AttributeError on a None result.
        fake = make_fake_alap(FAILURE)
        with patch.object(cli, "AlapAlap", fake):
            result = runner.invoke(
                cli.app,
                ["solve", "https://example.com/login", "-r", retries, "-o", str(results_file)],
            )
        assert not isinstance(result.exception, AttributeError)
        assert result.exit_code == 1
        assert fake.last_kwargs["retries"] == 1

    def test_retries_are_forwarded(self, isolated_db, no_dependency_check, results_file):
        fake = make_fake_alap(SUCCESS)
        with patch.object(cli, "AlapAlap", fake):
            runner.invoke(
                cli.app,
                ["solve", "https://example.com/", "-r", "4", "-o", str(results_file)],
            )
        assert fake.last_kwargs["retries"] == 4

    def test_visible_flag_inverts_invisible(self, isolated_db, no_dependency_check, results_file):
        fake = make_fake_alap(SUCCESS)
        with patch.object(cli, "AlapAlap", fake):
            runner.invoke(
                cli.app,
                ["solve", "https://example.com/", "--visible", "-o", str(results_file)],
            )
        assert fake.last_kwargs["invisible"] is False

    def test_timeout_is_forwarded(self, isolated_db, no_dependency_check, results_file):
        fake = make_fake_alap(SUCCESS)
        with patch.object(cli, "AlapAlap", fake):
            runner.invoke(
                cli.app,
                ["solve", "https://example.com/", "-t", "45", "-o", str(results_file)],
            )
        assert fake.last_kwargs["timeout"] == 45.0

    def test_result_record_schema_is_unchanged(
        self, isolated_db, no_dependency_check, results_file
    ):
        with patch.object(cli, "AlapAlap", make_fake_alap(SUCCESS)):
            runner.invoke(cli.app, ["solve", "https://example.com/login", "-o", str(results_file)])
        record = json.loads(results_file.read_text(encoding="utf-8").strip())
        assert set(record) == {"url", "sitekey", "token", "status", "error", "timestamp"}
        assert record["status"] == "success"

    def test_solve_records_into_the_database(self, isolated_db, no_dependency_check, results_file):
        with patch.object(cli, "AlapAlap", make_fake_alap(SUCCESS)):
            runner.invoke(cli.app, ["solve", "https://example.com/login", "-o", str(results_file)])
        entry = isolated_db.get(VALID_SITEKEY)
        assert entry is not None
        assert entry.status == "active"
        assert "cli" in entry.tags


class TestDetectCommand:
    """The detect command."""

    def test_sitekey_found(self, isolated_db, no_dependency_check, results_file):
        with patch.object(cli, "SitekeyDetector") as detector:
            detector.return_value.detect_with_method.return_value = (VALID_SITEKEY, "html")
            result = runner.invoke(
                cli.app, ["detect", "https://example.com", "-o", str(results_file)]
            )
        assert result.exit_code == 0
        assert isolated_db.get(VALID_SITEKEY) is not None

    def test_sitekey_missing_exits_nonzero(self, isolated_db, no_dependency_check, results_file):
        with patch.object(cli, "SitekeyDetector") as detector:
            detector.return_value.detect_with_method.return_value = (None, None)
            result = runner.invoke(
                cli.app, ["detect", "https://example.com", "-o", str(results_file)]
            )
        assert result.exit_code == 1
        record = json.loads(results_file.read_text(encoding="utf-8").strip())
        assert record["status"] == "no_sitekey"


class TestBatchCommand:
    """The batch command."""

    def test_solves_every_url(self, isolated_db, no_dependency_check, results_file, tmp_path):
        urls = tmp_path / "urls.txt"
        urls.write_text("# a comment\nhttps://a.com/1\n\nhttps://b.com/2\n", encoding="utf-8")

        def fake_batch(url_list, **kwargs):
            return [{**SUCCESS, "url": u} for u in url_list]

        with patch.object(cli, "solve_batch", fake_batch):
            result = runner.invoke(
                cli.app, ["batch", str(urls), "-o", str(results_file), "-w", "2"]
            )

        assert result.exit_code == 0
        # Comments and blank lines are skipped.
        assert len(results_file.read_text(encoding="utf-8").strip().splitlines()) == 2

    def test_missing_file_exits_nonzero(self, no_dependency_check, tmp_path):
        result = runner.invoke(cli.app, ["batch", str(tmp_path / "absent.txt")])
        assert result.exit_code == 1

    def test_empty_file_exits_nonzero(self, no_dependency_check, tmp_path):
        urls = tmp_path / "urls.txt"
        urls.write_text("# only comments\n\n", encoding="utf-8")
        result = runner.invoke(cli.app, ["batch", str(urls)])
        assert result.exit_code == 1

    def test_all_failures_exit_nonzero(
        self, isolated_db, no_dependency_check, results_file, tmp_path
    ):
        urls = tmp_path / "urls.txt"
        urls.write_text("https://a.com/1\n", encoding="utf-8")

        with patch.object(cli, "solve_batch", lambda u, **k: [{**FAILURE, "url": u[0]}]):
            result = runner.invoke(cli.app, ["batch", str(urls), "-o", str(results_file)])
        assert result.exit_code == 1


class TestSitekeysCommand:
    """Database management."""

    @pytest.fixture
    def seeded_db(self, isolated_db):
        isolated_db.add(
            VALID_SITEKEY, "https://etherscan.io/login", platform_name="Etherscan", status="active"
        )
        isolated_db.record_solve(VALID_SITEKEY, True, token="tok-abcdefgh1234", solve_time=3.2)
        return isolated_db

    def test_list(self, seeded_db):
        result = runner.invoke(cli.app, ["sitekeys", "list"])
        assert result.exit_code == 0
        assert "Etherscan" in result.output

    def test_list_empty(self, isolated_db):
        result = runner.invoke(cli.app, ["sitekeys", "list"])
        assert result.exit_code == 0
        assert "No sitekeys" in result.output

    def test_list_filtered_by_status(self, seeded_db):
        result = runner.invoke(cli.app, ["sitekeys", "list", "--status", "inactive"])
        assert "No sitekeys" in result.output

    def test_search_positional_query(self, seeded_db):
        # The form documented in the README.
        result = runner.invoke(cli.app, ["sitekeys", "search", "etherscan"])
        assert result.exit_code == 0
        assert "etherscan.io" in result.output

    def test_search_option_query_still_works(self, seeded_db):
        result = runner.invoke(cli.app, ["sitekeys", "search", "--query", "ether"])
        assert result.exit_code == 0
        assert "etherscan.io" in result.output

    def test_search_without_a_term_exits_nonzero(self, seeded_db):
        result = runner.invoke(cli.app, ["sitekeys", "search"])
        assert result.exit_code == 1

    def test_search_with_no_match(self, seeded_db):
        result = runner.invoke(cli.app, ["sitekeys", "search", "nothing-here"])
        assert result.exit_code == 0
        assert "No results" in result.output

    def test_stats(self, seeded_db):
        result = runner.invoke(cli.app, ["sitekeys", "stats"])
        assert result.exit_code == 0
        assert "Total Sitekeys" in result.output

    def test_export_markdown(self, seeded_db, tmp_path):
        target = tmp_path / "OUT.md"
        result = runner.invoke(cli.app, ["sitekeys", "export", "-o", str(target)])
        assert result.exit_code == 0
        assert "Etherscan" in target.read_text(encoding="utf-8")

    def test_export_csv(self, seeded_db, tmp_path):
        target = tmp_path / "out.csv"
        result = runner.invoke(
            cli.app, ["sitekeys", "export", "--format", "csv", "-o", str(target)]
        )
        assert result.exit_code == 0
        assert "platform_name" in target.read_text(encoding="utf-8")

    def test_export_json(self, seeded_db, tmp_path):
        target = tmp_path / "out.json"
        result = runner.invoke(
            cli.app, ["sitekeys", "export", "--format", "json", "-o", str(target)]
        )
        assert result.exit_code == 0
        assert VALID_SITEKEY in json.loads(target.read_text(encoding="utf-8"))

    def test_unknown_export_format_exits_nonzero(self, seeded_db, tmp_path):
        result = runner.invoke(cli.app, ["sitekeys", "export", "--format", "xml"])
        assert result.exit_code == 1

    def test_unknown_action_exits_nonzero(self, isolated_db):
        result = runner.invoke(cli.app, ["sitekeys", "frobnicate"])
        assert result.exit_code == 1

    def test_prune_without_criteria_exits_nonzero(self, seeded_db):
        result = runner.invoke(cli.app, ["sitekeys", "prune"])
        assert result.exit_code == 1

    def test_prune_failed_only(self, isolated_db):
        isolated_db.add("0x4AAAAAAA9999999999999", "https://dead.com")
        result = runner.invoke(cli.app, ["sitekeys", "prune", "--failed"])
        assert result.exit_code == 0
        assert len(isolated_db.get_all()) == 0


class TestInfoAndConfig:
    """Read-only informational commands."""

    def test_info(self, isolated_db):
        result = runner.invoke(cli.app, ["info"])
        assert result.exit_code == 0
        assert "Alap-Alap" in result.output

    def test_health(self, isolated_db):
        result = runner.invoke(cli.app, ["health"])
        assert result.exit_code == 0
        assert "camoufox" in result.output

    def test_config_table(self):
        result = runner.invoke(cli.app, ["config"])
        assert result.exit_code == 0
        assert "solver" in result.output

    def test_config_json_is_parseable(self):
        result = runner.invoke(cli.app, ["config", "--json", "--section", "api"])
        assert result.exit_code == 0
        assert "HOST" in result.output

    def test_config_unknown_section_exits_nonzero(self):
        result = runner.invoke(cli.app, ["config", "--section", "nope"])
        assert result.exit_code == 1


class TestDependencyHelpers:
    """ensure_dependencies and missing_packages."""

    def test_nothing_missing_is_a_noop(self):
        with (
            patch.object(cli, "missing_packages", lambda: []),
            patch("subprocess.check_call") as check_call,
        ):
            cli.ensure_dependencies()
        check_call.assert_not_called()

    def test_check_only_mode_exits_instead_of_installing(self):
        with (
            patch.object(cli, "missing_packages", lambda: ["camoufox"]),
            patch("subprocess.check_call") as check_call,
            pytest.raises(typer.Exit),
        ):
            cli.ensure_dependencies(auto_install=False)
        check_call.assert_not_called()

    def test_real_packages_are_detected(self):
        # requests is a hard dependency, so it must never be reported missing.
        assert "requests" not in cli.missing_packages()
