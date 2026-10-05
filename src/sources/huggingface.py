"""Hugging Face daily papers (free, no key)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from src import config, http
from src.sources.common import Candidate, clip, parse_iso

log = logging.getLogger(__name__)

API_URL = "https://huggingface.co/api/daily_papers"
# Daily lists are dated at midnight UTC, so allow an extra day on top of the normal window.
WINDOW_HOURS = config.LOOKBACK_HOURS + 24


def normalize(item: dict[str, Any]) -> Candidate | None:
    """Convert one daily_papers entry into a Candidate."""
    paper = item.get("paper") or {}
    paper_id = paper.get("id")
    title = paper.get("title") or item.get("title")
    if not (paper_id and title):
        return None
    abstract = paper.get("summary") or item.get("summary") or ""
    return Candidate(
        id=f"hf:{paper_id}",
        source="huggingface",
        title=" ".join(title.split()),
        url=f"https://huggingface.co/papers/{paper_id}",
        summary=clip(abstract, 500),
        score=float(paper.get("upvotes") or 0),
        created_at=paper.get("submittedOnDailyAt") or item.get("publishedAt") or "",
        raw_text=clip(abstract, 3000),
        extra={"arxiv_url": f"https://arxiv.org/abs/{paper_id}"},
    )


def fetch() -> list[Candidate]:
    """Daily papers submitted within WINDOW_HOURS."""
    try:
        items = http.get(API_URL, params={"limit": 100}).json()
        cutoff = datetime.now(timezone.utc) - timedelta(hours=WINDOW_HOURS)
        out = []
        for item in items:
            c = normalize(item)
            if c and c["created_at"] and parse_iso(c["created_at"]) >= cutoff:
                out.append(c)
        log.info("huggingface: %d candidates", len(out))
        return out
    except Exception:
        log.exception("huggingface: fetch failed")
        return []
