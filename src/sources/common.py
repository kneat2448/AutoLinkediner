"""Shared helpers for source modules."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, TypedDict


class Candidate(TypedDict, total=False):
    """A normalized story candidate. All sources return lists of these."""

    id: str
    source: str          # hackernews | reddit | huggingface | x
    title: str
    url: str
    summary: str
    score: float         # raw engagement (points, upvotes); normalized later in rank.py
    created_at: str      # ISO-8601 UTC
    raw_text: str
    extra: dict[str, Any]  # source-specific (discussion url, subreddit, etc.)


def iso_from_ts(ts: float) -> str:
    """Unix timestamp → ISO-8601 UTC string."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def parse_iso(value: str) -> datetime:
    """Parse an ISO-8601 string (with Z or offset) into an aware UTC datetime."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def clip(text: str, limit: int) -> str:
    """Collapse whitespace and truncate."""
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
