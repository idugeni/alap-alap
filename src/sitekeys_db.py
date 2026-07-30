"""
Alap-Alap Captcha Database

Stores all solved captcha data for public sharing.

Writes are serialized behind a lock and land on disk atomically (temp file plus
``os.replace``), so a crash or two concurrent API requests cannot leave a
half-written ``captcha_database.json`` behind.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from loguru import logger

from src.config import config

#: Recognised lifecycle states.
VALID_STATUSES = ("active", "inactive", "unknown")

#: Icons used by the CLI table and the markdown export.
STATUS_ICONS = {"active": "🟢", "inactive": "🔴", "unknown": "⚪"}

#: Domain to friendly-name map used when no platform name is supplied.
KNOWN_PLATFORMS = {
    "etherscan.io": "Etherscan",
    "etherscan.com": "Etherscan",
    "accounts.x.ai": "xAI / Grok",
    "grok.com": "Grok",
    "openai.com": "OpenAI",
    "platform.openai.com": "OpenAI Platform",
    "chat.openai.com": "ChatGPT",
    "anthropic.com": "Anthropic",
    "console.anthropic.com": "Anthropic Console",
    "huggingface.co": "Hugging Face",
    "replicate.com": "Replicate",
    "cohere.com": "Cohere",
    "mistral.ai": "Mistral AI",
    "deepseek.com": "DeepSeek",
    "together.ai": "Together AI",
    "groq.com": "Groq",
    "binance.com": "Binance",
    "coinbase.com": "Coinbase",
    "kraken.com": "Kraken",
    "kucoin.com": "KuCoin",
    "bybit.com": "Bybit",
    "gate.io": "Gate.io",
    "okx.com": "OKX",
    "crypto.com": "Crypto.com",
    "cloudflare.com": "Cloudflare",
    "discord.com": "Discord",
    "x.com": "X / Twitter",
    "shopify.com": "Shopify",
    "upwork.com": "Upwork",
    "fiverr.com": "Fiverr",
}


def _utc_now() -> str:
    """Current UTC timestamp as ISO-8601."""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SitekeyEntry:
    """A discovered sitekey entry."""

    sitekey: str
    url: str
    domain: str
    platform_name: str  # Friendly name like "Etherscan", "xAI/Grok"
    status: str  # "active", "inactive", "unknown"
    first_seen: str
    last_seen: str
    solve_count: int = 0
    success_count: int = 0
    last_token: str = ""  # Last solved token (for proof)
    last_solve_time: float = 0.0  # Last solve time in seconds (a duration)
    #: When the stored token was obtained. Turnstile tokens expire after about
    #: five minutes, so without a timestamp there is no way to tell whether a
    #: stored token is still usable. `last_solve_time` is a duration, not a date.
    token_obtained_at: str = ""
    tags: list[str] | None = None

    def __post_init__(self):
        if self.tags is None:
            self.tags = []

    @property
    def token_age(self) -> float | None:
        """Seconds since the stored token was obtained, or ``None``."""
        if not self.last_token or not self.token_obtained_at:
            return None
        obtained = SitekeysDB._parse_timestamp(self.token_obtained_at)
        if obtained is None:
            return None
        return max(0.0, (datetime.now(timezone.utc) - obtained).total_seconds())

    @property
    def token_expires_in(self) -> float | None:
        """Seconds until the stored token expires; negative once stale."""
        age = self.token_age
        if age is None:
            return None
        return config.storage.TOKEN_TTL_S - age

    @property
    def token_is_fresh(self) -> bool:
        """Whether the stored token should still be accepted by Cloudflare."""
        remaining = self.token_expires_in
        return remaining is not None and remaining > 0

    @property
    def success_rate(self) -> float:
        """Fraction of attempts that produced a token, 0.0 when never tried."""
        if self.solve_count <= 0:
            return 0.0
        return self.success_count / self.solve_count

    @property
    def status_icon(self) -> str:
        """Icon for the current status."""
        return STATUS_ICONS.get(self.status, "⚪")

    def token_preview(self, chars: int = 8) -> str:
        """Redacted token: leading ``chars`` plus the last four characters."""
        if not self.last_token:
            return ""
        if len(self.last_token) > chars + 4:
            return f"{self.last_token[:chars]}...{self.last_token[-4:]}"
        return self.last_token


class SitekeysDB:
    """
    Sitekeys database manager.

    Thread safe for use from the REST API. The lock is per-instance and the
    replace is atomic, which covers concurrent threads in one process; a
    separate process writing the same file at the same time is still last-write
    wins.
    """

    def __init__(self, db_path: str | None = None, *, autosave: bool = True):
        self.db_path = Path(db_path or config.storage.DATABASE_FILE)
        self.autosave = autosave
        self._data: dict[str, SitekeyEntry] = {}
        self._lock = threading.RLock()
        self._storage = config.storage
        self._load()

    # ----------------------------------------------------------------- #
    # Persistence
    # ----------------------------------------------------------------- #

    def _load(self):
        """Load database from file."""
        if not self.db_path.exists():
            return

        try:
            with open(self.db_path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            # A corrupt file is preserved rather than silently overwritten on
            # the next save, so the data can still be recovered by hand.
            self._quarantine(f"Corrupt sitekeys DB: {e}")
            return
        except OSError as e:
            logger.warning(f"Failed to load sitekeys DB: {e}")
            return

        if not isinstance(data, dict):
            self._quarantine("Sitekeys DB is not a JSON object")
            return

        known = {f.name for f in fields(SitekeyEntry)}
        loaded, skipped = 0, 0

        for key, entry in data.items():
            if not isinstance(entry, dict):
                skipped += 1
                continue
            try:
                # Drop unknown keys so a file written by a newer version with
                # extra fields still loads instead of raising TypeError.
                self._data[key] = SitekeyEntry(**{k: v for k, v in entry.items() if k in known})
                loaded += 1
            except (TypeError, ValueError) as e:
                logger.debug(f"Skipping malformed entry {key}: {e}")
                skipped += 1

        logger.debug(f"Loaded {loaded} sitekeys from {self.db_path}")
        if skipped:
            logger.warning(f"Skipped {skipped} malformed sitekey entrie(s)")

    def _quarantine(self, reason: str) -> None:
        """Move an unreadable database aside so it is not lost."""
        logger.warning(reason)
        try:
            backup = self.db_path.with_suffix(f".corrupt-{int(datetime.now().timestamp())}.json")
            shutil.move(str(self.db_path), str(backup))
            logger.warning(f"Moved unreadable database to {backup}")
        except OSError as e:  # pragma: no cover - best effort
            logger.error(f"Could not preserve corrupt database: {e}")

    def _serialize(self) -> dict[str, dict[str, Any]]:
        """Build the JSON payload, redacting tokens when configured."""
        redact = self._storage.REDACT_STORED_TOKENS
        preview_chars = max(0, self._storage.TOKEN_PREVIEW_CHARS)

        payload: dict[str, dict[str, Any]] = {}
        for key, entry in self._data.items():
            record = asdict(entry)
            if redact and record.get("last_token"):
                # Tokens are short-lived credentials. Keep enough to prove a
                # solve happened without writing a usable token to disk.
                record["last_token"] = entry.token_preview(preview_chars)
            payload[key] = record
        return payload

    def _save(self):
        """Save database to file atomically."""
        with self._lock:
            payload = self._serialize()

            try:
                parent = self.db_path.parent
                parent.mkdir(parents=True, exist_ok=True)

                # Write to a sibling temp file then replace: a reader either
                # sees the old complete file or the new complete file.
                # noqa: SIM115 - delete=False is required so the file survives
                # close() and can be os.replace()d into position; the `with`
                # block below still guarantees the handle is closed.
                handle = tempfile.NamedTemporaryFile(  # noqa: SIM115
                    mode="w",
                    encoding="utf-8",
                    dir=parent,
                    prefix=f".{self.db_path.name}.",
                    suffix=".tmp",
                    delete=False,
                )
                temp_path = Path(handle.name)
                try:
                    with handle:
                        json.dump(payload, handle, indent=2, ensure_ascii=False)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temp_path, self.db_path)
                except BaseException:
                    temp_path.unlink(missing_ok=True)
                    raise

                logger.debug(f"Saved {len(payload)} sitekeys to {self.db_path}")
            except OSError as e:
                logger.error(f"Failed to save sitekeys DB: {e}")

    def save(self) -> None:
        """Force a write to disk. Useful when ``autosave`` is off."""
        self._save()

    def _maybe_save(self) -> None:
        """Persist unless batching is in effect."""
        if self.autosave:
            self._save()

    # ----------------------------------------------------------------- #
    # Mutations
    # ----------------------------------------------------------------- #

    def add(
        self,
        sitekey: str,
        url: str,
        platform_name: str | None = None,
        status: str = "unknown",
        tags: list[str] | None = None,
    ) -> SitekeyEntry:
        """Add or update a sitekey entry."""
        domain = self._extract_domain(url)
        now = _utc_now()

        if status not in VALID_STATUSES:
            logger.debug(f"Unknown status {status!r}, storing as 'unknown'")
            status = "unknown"

        # Auto-detect platform name if not provided
        if not platform_name:
            platform_name = self._guess_platform(domain)

        with self._lock:
            if sitekey in self._data:
                entry = self._data[sitekey]
                entry.last_seen = now
                entry.url = url
                entry.domain = domain
                if platform_name:
                    entry.platform_name = platform_name
                if status != "unknown":
                    entry.status = status
                if tags:
                    entry.tags = sorted(set((entry.tags or []) + tags))
            else:
                entry = SitekeyEntry(
                    sitekey=sitekey,
                    url=url,
                    domain=domain,
                    platform_name=platform_name or domain,
                    status=status,
                    first_seen=now,
                    last_seen=now,
                    tags=sorted(set(tags)) if tags else [],
                )
                self._data[sitekey] = entry

            self._maybe_save()
            return entry

    def record_solve(self, sitekey: str, success: bool, token: str = "", solve_time: float = 0.0):
        """Record a solve attempt."""
        with self._lock:
            entry = self._data.get(sitekey)
            if entry is None:
                logger.debug(f"record_solve for unknown sitekey {sitekey[:20]}...")
                return

            entry.solve_count += 1
            if success:
                entry.success_count += 1
                entry.status = "active"
                if token:
                    entry.last_token = token
                    entry.token_obtained_at = _utc_now()
                entry.last_solve_time = solve_time
            elif entry.success_count == 0:
                # Never solved and just failed again: mark it dead so the CLI
                # and API can tell a stale key from an untried one.
                entry.status = "inactive"

            entry.last_seen = _utc_now()
            self._maybe_save()

    def record_result(
        self,
        url: str,
        result: dict[str, Any],
        tags: list[str] | None = None,
    ) -> SitekeyEntry | None:
        """
        Store a solve outcome produced by :class:`~src.core.AlapAlap`.

        Shared by the CLI and the REST API so both record the same way. A key
        that has solved before is never demoted to ``inactive`` by a single
        failure; only never-successful keys are marked dead.

        Args:
            url: URL the attempt targeted.
            result: Result dict with ``success``/``token``/``sitekey``/``time``.
            tags: Extra tags to attach, e.g. ``["api"]`` or ``["cli"]``.

        Returns:
            The stored entry, or ``None`` when the result carries no sitekey.
        """
        sitekey = result.get("sitekey")
        if not sitekey:
            return None

        with self._lock:
            existing = self._data.get(sitekey)
            if result.get("success"):
                status = "active"
            elif existing and existing.success_count > 0:
                status = existing.status
            else:
                status = "inactive"

            entry = self.add(sitekey, url, status=status, tags=tags)
            self.record_solve(
                sitekey,
                bool(result.get("success")),
                token=result.get("token") or "",
                solve_time=float(result.get("time") or 0.0),
            )
            return entry

    def remove(self, sitekey: str) -> bool:
        """Delete an entry. Returns whether it existed."""
        with self._lock:
            existed = self._data.pop(sitekey, None) is not None
            if existed:
                self._maybe_save()
            return existed

    def prune(self, *, older_than_days: int | None = None, only_failed: bool = False) -> int:
        """
        Drop stale entries.

        Args:
            older_than_days: Remove entries not seen within this many days.
            only_failed: Restrict removal to entries that never solved.

        Returns:
            Number of entries removed.
        """
        if older_than_days is None and not only_failed:
            # No criteria means no deletion, rather than "delete everything".
            return 0

        with self._lock:
            cutoff = None
            if older_than_days is not None:
                cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)

            doomed: list[str] = []
            for key, entry in self._data.items():
                if only_failed and entry.success_count > 0:
                    continue
                if cutoff is not None and not self._is_stale(entry, cutoff):
                    continue
                doomed.append(key)

            for key in doomed:
                del self._data[key]

            if doomed:
                self._maybe_save()

            return len(doomed)

    @classmethod
    def _is_stale(cls, entry: SitekeyEntry, cutoff: datetime) -> bool:
        """Whether ``entry`` was last seen before ``cutoff``.

        An unparseable timestamp counts as fresh, so a bad value never causes
        silent data loss.
        """
        seen = cls._parse_timestamp(entry.last_seen)
        if seen is None:
            return False
        return seen < cutoff

    @staticmethod
    def _parse_timestamp(value: str) -> datetime | None:
        """Parse a stored ISO timestamp, tolerating older naive values."""
        try:
            parsed = datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed

    # ----------------------------------------------------------------- #
    # Queries
    # ----------------------------------------------------------------- #

    def _guess_platform(self, domain: str) -> str:
        """Guess platform name from domain."""
        for key, name in KNOWN_PLATFORMS.items():
            if key in domain:
                return name

        return domain.split(".")[0].title() if domain else "Unknown"

    def get(self, sitekey: str) -> SitekeyEntry | None:
        """Get a sitekey entry."""
        return self._data.get(sitekey)

    def get_all(self) -> list[SitekeyEntry]:
        """Get all sitekey entries."""
        return list(self._data.values())

    def get_by_domain(self, domain: str) -> list[SitekeyEntry]:
        """Get sitekeys by domain."""
        return [e for e in self._data.values() if e.domain == domain]

    def get_active(self) -> list[SitekeyEntry]:
        """Get all active sitekeys."""
        return [e for e in self._data.values() if e.status == "active"]

    def search(self, query: str) -> list[SitekeyEntry]:
        """Search sitekeys by query."""
        query_lower = (query or "").lower()
        return [
            e
            for e in self._data.values()
            if query_lower in e.sitekey.lower()
            or query_lower in e.domain.lower()
            or query_lower in e.url.lower()
            or query_lower in e.platform_name.lower()
            or any(query_lower in tag.lower() for tag in (e.tags or []))
        ]

    def stats(self) -> dict[str, Any]:
        """Aggregate counters for the CLI ``stats`` view and ``GET /stats``."""
        entries = self.get_all()
        total_solves = sum(e.solve_count for e in entries)
        total_success = sum(e.success_count for e in entries)
        solved = [e for e in entries if e.last_solve_time > 0]

        return {
            "total_sitekeys": len(entries),
            "active_sitekeys": sum(1 for e in entries if e.status == "active"),
            "inactive_sitekeys": sum(1 for e in entries if e.status == "inactive"),
            "unknown_sitekeys": sum(1 for e in entries if e.status == "unknown"),
            "total_domains": len({e.domain for e in entries if e.domain}),
            "total_solve_attempts": total_solves,
            "successful_solves": total_success,
            "success_rate": (total_success / total_solves) if total_solves else 0.0,
            "avg_solve_time": (
                round(sum(e.last_solve_time for e in solved) / len(solved), 2) if solved else 0.0
            ),
            "fresh_tokens": sum(1 for e in entries if e.token_is_fresh),
        }

    def get_fresh_tokens(self) -> list[SitekeyEntry]:
        """Entries whose stored token has not expired yet."""
        return [e for e in self._data.values() if e.token_is_fresh]

    def __len__(self) -> int:
        return len(self._data)

    def __contains__(self, sitekey: object) -> bool:
        return sitekey in self._data

    # ----------------------------------------------------------------- #
    # Export
    # ----------------------------------------------------------------- #

    def export_markdown(self) -> str:
        """Export sitekeys as markdown for public sharing."""
        summary = self.stats()
        lines = [
            "# Alap-Alap Captcha Database",
            "",
            "Community-maintained list of Cloudflare Turnstile sitekeys and tokens.",
            "",
            f"**Last updated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            f"**Total sitekeys:** {len(self._data)}",
            f"**Active:** {summary['active_sitekeys']} | "
            f"**Domains:** {summary['total_domains']} | "
            f"**Success rate:** {summary['success_rate'] * 100:.1f}%",
            "",
            "## Solved Captchas",
            "",
            "| Platform | Sitekey | Token | Status | Solve Time | Success Rate |",
            "|----------|---------|-------|--------|------------|--------------|",
        ]

        for entry in sorted(self._data.values(), key=lambda x: x.platform_name):
            rate = f"{entry.success_count}/{entry.solve_count}" if entry.solve_count > 0 else "-"
            # Redact token: show only first 8 and last 4 chars
            preview = entry.token_preview(8)
            token_display = f"`{preview}`" if preview else "-"
            solve_time = f"{entry.last_solve_time:.1f}s" if entry.last_solve_time > 0 else "-"
            row = (
                f"| **{entry.platform_name}** | `{entry.sitekey[:20]}...` "
                f"| {token_display} | {entry.status_icon} {entry.status} "
                f"| {solve_time} | {rate} |"
            )
            lines.append(row)

        lines.extend(
            [
                "",
                "## Usage",
                "",
                "```python",
                "from src.sitekeys_db import SitekeysDB",
                "",
                "db = SitekeysDB()",
                "sitekeys = db.get_active()",
                "for entry in sitekeys:",
                "    print(f'{entry.domain}: {entry.sitekey}')",
                "```",
                "",
                "---",
                "",
                "*Generated by Alap-Alap - Cloudflare Turnstile Captcha Solver*",
            ]
        )

        return "\n".join(lines)

    def export_csv(self) -> str:
        """Export sitekeys as CSV, tokens redacted."""
        import csv
        import io

        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(
            [
                "platform_name",
                "sitekey",
                "domain",
                "url",
                "status",
                "solve_count",
                "success_count",
                "success_rate",
                "last_solve_time",
                "first_seen",
                "last_seen",
                "tags",
            ]
        )

        for entry in sorted(self._data.values(), key=lambda x: x.platform_name):
            writer.writerow(
                [
                    entry.platform_name,
                    entry.sitekey,
                    entry.domain,
                    entry.url,
                    entry.status,
                    entry.solve_count,
                    entry.success_count,
                    f"{entry.success_rate:.3f}",
                    f"{entry.last_solve_time:.2f}",
                    entry.first_seen,
                    entry.last_seen,
                    ";".join(entry.tags or []),
                ]
            )

        return buffer.getvalue()

    def export_json(self) -> str:
        """Export the database as a JSON string, tokens redacted as on disk."""
        return json.dumps(self._serialize(), indent=2, ensure_ascii=False)

    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL."""
        try:
            parsed = urlparse(url)
            return parsed.netloc or parsed.hostname or url
        except Exception:
            return url


# Global database instance
sitekeys_db = SitekeysDB()
