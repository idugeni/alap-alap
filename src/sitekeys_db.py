"""
Alap-Alap Captcha Database

Stores all solved captcha data for public sharing.
"""

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from loguru import logger

from src.config import config


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
    last_solve_time: float = 0.0  # Last solve time in seconds
    tags: List[str] = None

    def __post_init__(self):
        if self.tags is None:
            self.tags = []


class SitekeysDB:
    """Sitekeys database manager."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = Path(db_path or config.storage.DATABASE_FILE)
        self._data: Dict[str, SitekeyEntry] = {}
        self._load()

    def _load(self):
        """Load database from file."""
        if self.db_path.exists():
            try:
                with open(self.db_path, encoding="utf-8") as f:
                    data = json.load(f)
                    for key, entry in data.items():
                        self._data[key] = SitekeyEntry(**entry)
                logger.debug(f"Loaded {len(self._data)} sitekeys from {self.db_path}")
            except Exception as e:
                logger.warning(f"Failed to load sitekeys DB: {e}")

    def _save(self):
        """Save database to file."""
        try:
            data = {key: asdict(entry) for key, entry in self._data.items()}
            with open(self.db_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.debug(f"Saved {len(self._data)} sitekeys to {self.db_path}")
        except Exception as e:
            logger.error(f"Failed to save sitekeys DB: {e}")

    def add(
        self,
        sitekey: str,
        url: str,
        platform_name: str = None,
        status: str = "unknown",
        tags: List[str] = None,
    ) -> SitekeyEntry:
        """Add or update a sitekey entry."""
        domain = self._extract_domain(url)
        now = datetime.now(timezone.utc).isoformat()

        # Auto-detect platform name if not provided
        if not platform_name:
            platform_name = self._guess_platform(domain)

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
                entry.tags = list(set(entry.tags + tags))
        else:
            entry = SitekeyEntry(
                sitekey=sitekey,
                url=url,
                domain=domain,
                platform_name=platform_name or domain,
                status=status,
                first_seen=now,
                last_seen=now,
                tags=tags or [],
            )
            self._data[sitekey] = entry

        self._save()
        return entry

    def _guess_platform(self, domain: str) -> str:
        """Guess platform name from domain."""
        known_platforms = {
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
        }

        for key, name in known_platforms.items():
            if key in domain:
                return name

        return domain.split(".")[0].title() if domain else "Unknown"

    def record_solve(self, sitekey: str, success: bool, token: str = "", solve_time: float = 0.0):
        """Record a solve attempt."""
        if sitekey in self._data:
            entry = self._data[sitekey]
            entry.solve_count += 1
            if success:
                entry.success_count += 1
                entry.status = "active"
                entry.last_token = token
                entry.last_solve_time = solve_time
            entry.last_seen = datetime.now(timezone.utc).isoformat()
            self._save()

    def get(self, sitekey: str) -> Optional[SitekeyEntry]:
        """Get a sitekey entry."""
        return self._data.get(sitekey)

    def get_all(self) -> List[SitekeyEntry]:
        """Get all sitekey entries."""
        return list(self._data.values())

    def get_by_domain(self, domain: str) -> List[SitekeyEntry]:
        """Get sitekeys by domain."""
        return [e for e in self._data.values() if e.domain == domain]

    def get_active(self) -> List[SitekeyEntry]:
        """Get all active sitekeys."""
        return [e for e in self._data.values() if e.status == "active"]

    def search(self, query: str) -> List[SitekeyEntry]:
        """Search sitekeys by query."""
        query_lower = query.lower()
        return [
            e
            for e in self._data.values()
            if query_lower in e.sitekey.lower()
            or query_lower in e.domain.lower()
            or query_lower in e.url.lower()
            or any(query_lower in tag.lower() for tag in (e.tags or []))
        ]

    def export_markdown(self) -> str:
        """Export sitekeys as markdown for public sharing."""
        lines = [
            "# Alap-Alap Captcha Database",
            "",
            "Community-maintained list of Cloudflare Turnstile sitekeys and tokens.",
            "",
            f"**Last updated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            f"**Total sitekeys:** {len(self._data)}",
            "",
            "## Solved Captchas",
            "",
            "| Platform | Sitekey | Token | Status | Solve Time | Success Rate |",
            "|----------|---------|-------|--------|------------|--------------|",
        ]

        for entry in sorted(self._data.values(), key=lambda x: x.platform_name):
            rate = f"{entry.success_count}/{entry.solve_count}" if entry.solve_count > 0 else "-"
            status_icon = {"active": "🟢", "inactive": "🔴", "unknown": "⚪"}.get(
                entry.status, "⚪"
            )
            # Redact token: show only first 8 and last 4 chars
            if entry.last_token and len(entry.last_token) > 12:
                token_display = f"`{entry.last_token[:8]}...{entry.last_token[-4:]}`"
            elif entry.last_token:
                token_display = f"`{entry.last_token}`"
            else:
                token_display = "-"
            solve_time = f"{entry.last_solve_time:.1f}s" if entry.last_solve_time > 0 else "-"
            row = (
                f"| **{entry.platform_name}** | `{entry.sitekey[:20]}...` "
                f"| {token_display} | {status_icon} {entry.status} "
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

    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL."""
        try:
            from urllib.parse import urlparse

            parsed = urlparse(url)
            return parsed.netloc or parsed.hostname or url
        except Exception:
            return url


# Global database instance
sitekeys_db = SitekeysDB()
