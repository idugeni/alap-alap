"""Unit tests for the shared pydantic models."""

import pytest
from pydantic import ValidationError

from src.models import (
    DetectRequest,
    SolveOutcome,
    SolveRequest,
    SolveResult,
)

VALID_SITEKEY = "0x4AAAAAAAQV1p8gT2jN3m4"


class TestSolveOutcome:
    """The result contract shared by every surface."""

    def test_ok_builds_a_success(self):
        outcome = SolveOutcome.ok("tok", VALID_SITEKEY, 1.25)
        assert outcome.success is True
        assert outcome.token == "tok"
        assert outcome.error is None

    def test_fail_builds_a_failure(self):
        outcome = SolveOutcome.fail("nope", sitekey=VALID_SITEKEY, elapsed=2.0)
        assert outcome.success is False
        assert outcome.token is None
        assert outcome.error == "nope"

    def test_to_dict_keeps_the_legacy_keys(self):
        # Existing callers index these keys directly.
        keys = set(SolveOutcome.ok("tok", VALID_SITEKEY, 1.0).to_dict())
        assert keys == {"success", "token", "sitekey", "error", "time", "attempts"}

    def test_attempts_defaults_to_one(self):
        assert SolveOutcome.ok("tok", VALID_SITEKEY, 1.0).to_dict()["attempts"] == 1

    def test_attempts_can_be_set(self):
        assert SolveOutcome.fail("x", attempts=4).to_dict()["attempts"] == 4


class TestSolveResult:
    """Records written to the results file."""

    def test_timestamp_is_filled_in(self):
        assert SolveResult(url="https://a.com", status="success").timestamp

    def test_from_outcome_maps_success(self):
        record = SolveResult.from_outcome(
            "https://a.com", SolveOutcome.ok("tok", VALID_SITEKEY, 1.0)
        )
        assert record.status == "success"
        assert record.token == "tok"
        assert record.sitekey == VALID_SITEKEY

    def test_from_outcome_maps_failure(self):
        record = SolveResult.from_outcome("https://a.com", SolveOutcome.fail("boom"))
        assert record.status == "failed"
        assert record.error == "boom"

    def test_from_outcome_accepts_a_plain_dict(self):
        record = SolveResult.from_outcome(
            "https://a.com",
            {"success": True, "token": "t", "sitekey": VALID_SITEKEY, "error": None},
        )
        assert record.status == "success"

    def test_json_schema_is_stable(self):
        record = SolveResult(url="https://a.com", status="success")
        assert set(record.model_dump()) == {
            "url",
            "sitekey",
            "token",
            "status",
            "error",
            "timestamp",
        }


class TestSolveRequest:
    """Validation of POST /solve bodies."""

    def test_minimal_body(self):
        request = SolveRequest(url="https://a.com")
        assert request.invisible is True
        assert request.retries == 1

    def test_url_is_trimmed(self):
        assert SolveRequest(url="  https://a.com  ").url == "https://a.com"

    def test_blank_url_is_rejected(self):
        with pytest.raises(ValidationError):
            SolveRequest(url="   ")

    def test_unknown_field_is_rejected(self):
        with pytest.raises(ValidationError):
            SolveRequest(url="https://a.com", bogus=1)

    @pytest.mark.parametrize("retries", [0, -1, 11])
    def test_retries_bounds(self, retries):
        with pytest.raises(ValidationError):
            SolveRequest(url="https://a.com", retries=retries)

    @pytest.mark.parametrize("timeout", [0, -5, 601])
    def test_timeout_bounds(self, timeout):
        with pytest.raises(ValidationError):
            SolveRequest(url="https://a.com", timeout=timeout)

    def test_timeout_within_range_is_accepted(self):
        assert SolveRequest(url="https://a.com", timeout=90).timeout == 90


class TestDetectRequest:
    """Validation of POST /detect bodies."""

    def test_minimal_body(self):
        assert DetectRequest(url="https://a.com").proxy is None

    def test_blank_url_is_rejected(self):
        with pytest.raises(ValidationError):
            DetectRequest(url="")

    def test_unknown_field_is_rejected(self):
        with pytest.raises(ValidationError):
            DetectRequest(url="https://a.com", invisible=True)
