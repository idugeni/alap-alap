"""
Alap-Alap Data Models

Pydantic models shared by the CLI, the Python API and the REST API so the three
surfaces agree on field names and validation rules.

:class:`SolveOutcome` mirrors the dict that :meth:`AlapAlap.solve` has always
returned (``success``, ``token``, ``sitekey``, ``error``, ``time``). It exists so
that shape is defined in one place and validated once; ``to_dict()`` reproduces
the original contract exactly, which keeps every existing caller working.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Status values written to the results file.
ResultStatus = Literal["success", "failed", "sitekey_only", "no_sitekey"]

#: Lifecycle states tracked per sitekey in the database.
SitekeyStatus = Literal["active", "inactive", "unknown"]


def utc_now_iso() -> str:
    """Current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


class SolveOutcome(BaseModel):
    """Result of a single solve attempt."""

    model_config = ConfigDict(extra="ignore")

    success: bool
    token: str | None = None
    sitekey: str | None = None
    error: str | None = None
    time: float = 0.0
    attempts: int = 1

    def to_dict(self) -> dict[str, Any]:
        """Return the legacy dict shape callers expect."""
        return {
            "success": self.success,
            "token": self.token,
            "sitekey": self.sitekey,
            "error": self.error,
            "time": self.time,
            "attempts": self.attempts,
        }

    @classmethod
    def ok(
        cls,
        token: str,
        sitekey: str | None,
        elapsed: float,
        attempts: int = 1,
    ) -> SolveOutcome:
        """Build a successful outcome."""
        return cls(
            success=True,
            token=token,
            sitekey=sitekey,
            error=None,
            time=elapsed,
            attempts=attempts,
        )

    @classmethod
    def fail(
        cls,
        error: str,
        sitekey: str | None = None,
        elapsed: float = 0.0,
        attempts: int = 1,
    ) -> SolveOutcome:
        """Build a failed outcome."""
        return cls(
            success=False,
            token=None,
            sitekey=sitekey,
            error=error,
            time=elapsed,
            attempts=attempts,
        )


class SolveResult(BaseModel):
    """A line in the results file."""

    model_config = ConfigDict(extra="ignore")

    url: str
    sitekey: str | None = None
    token: str | None = None
    status: str
    error: str | None = None
    timestamp: str = Field(default_factory=utc_now_iso)

    @classmethod
    def from_outcome(cls, url: str, outcome: SolveOutcome | dict[str, Any]) -> SolveResult:
        """Build a results-file record from a solve outcome."""
        data = outcome.to_dict() if isinstance(outcome, SolveOutcome) else dict(outcome)
        return cls(
            url=url,
            sitekey=data.get("sitekey"),
            token=data.get("token"),
            status="success" if data.get("success") else "failed",
            error=data.get("error"),
        )


class SolveRequest(BaseModel):
    """Body of ``POST /solve``."""

    model_config = ConfigDict(extra="forbid")

    url: str
    sitekey: str | None = None
    proxy: str | None = None
    invisible: bool = True
    timeout: float | None = Field(default=None, gt=0, le=600)
    retries: int = Field(default=1, ge=1, le=10)

    @field_validator("url")
    @classmethod
    def _url_not_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("url must not be empty")
        return value.strip()


class DetectRequest(BaseModel):
    """Body of ``POST /detect``."""

    model_config = ConfigDict(extra="forbid")

    url: str
    proxy: str | None = None

    @field_validator("url")
    @classmethod
    def _url_not_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("url must not be empty")
        return value.strip()


class BatchItem(BaseModel):
    """One entry in a batch solve response."""

    model_config = ConfigDict(extra="ignore")

    url: str
    success: bool
    token: str | None = None
    sitekey: str | None = None
    error: str | None = None
    time: float = 0.0
