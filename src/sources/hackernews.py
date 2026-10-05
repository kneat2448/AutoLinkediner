"""Hacker News via the Algolia API (free, no key)."""
from __future__ import annotations

import logging
import re
import time
from typing import Any

from bs4 import BeautifulSoup

from src import config, http
from src.sources.common import Candidate, clip, iso_from_ts

log = logging.getLogger(__name__)

SEARCH_URL = "https://hn.algolia.com/api/v1/search"
ITEM_URL = "https://hn.algolia.com/api/v1/items/{id}"
_KEYWORD_RE = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in config.HN_KEYWORDS) + r")s?\b", re.IGNORECASE
)


def is_ai_title(title: str) -> bool:
    """True if the title mentions one of the AI keywords as a whole word."""
    return bool(_KEYWORD_RE.search(title or ""))


def normalize(hit: dict[str, Any]) -> Candidate | None:
    """Convert one Algolia hit into a Candidate, or None if it isn't an AI story."""
    title = hit.get("title") or ""
    if not title or not is_ai_title(title):
        return None
    object_id = str(hit["objectID"])
    discussion = f"https://news.ycombinator.com/item?id={object_id}"
    return Candidate(
        id=f"hn:{object_id}",
        source="hackernews",
        title=title,
        url=hit.get("url") or discussion,
        summary=clip(hit.get("story_text") or "", 500),
        score=float(hit.get("points") or 0),
        created_at=iso_from_ts(hit.get("created_at_i") or 0),
        raw_text="",
        extra={"discussion_url": discussion, "num_comments": hit.get("num_comments") or 0},
    )


def fetch() -> list[Candidate]:
    """Fetch AI stories from the last LOOKBACK_HOURS with more than HN_MIN_POINTS points."""
    try:
        since = int(time.time() - config.LOOKBACK_HOURS * 3600)
        hits: dict[str, dict[str, Any]] = {}
        for keyword in config.HN_KEYWORDS:
            params = {
                "tags": "story",
                "query": keyword,
                "numericFilters": f"created_at_i>{since},points>{config.HN_MIN_POINTS}",
                "hitsPerPage": 50,
            }
            for hit in http.get(SEARCH_URL, params=params).json().get("hits", []):
                hits[str(hit["objectID"])] = hit
        out = [c for c in (normalize(h) for h in hits.values()) if c]
        log.info("hackernews: %d candidates", len(out))
        return out
    except Exception:
        log.exception("hackernews: fetch failed")
        return []


def top_comment(candidate: Candidate) -> str:
    """Best-effort: text of the first top-level comment on the HN thread."""
    try:
        object_id = candidate["id"].split(":", 1)[1]
        item = http.get(ITEM_URL.format(id=object_id), retries=2).json()
        for child in item.get("children", []):
            if child.get("text"):
                return clip(BeautifulSoup(child["text"], "html.parser").get_text(" "), 800)
    except Exception:
        log.warning("hackernews: could not fetch top comment")
    return ""
