"""AI news via RSS: official AI-lab blogs and major tech news outlets (free, no keys).

Each feed has a weight: official lab announcements (new models, launches) rank highest,
then established newsrooms, then smaller blogs.
"""
from __future__ import annotations

import calendar
import hashlib
import logging
import time
from typing import Any

import feedparser
from bs4 import BeautifulSoup

from src import config, http
from src.sources.common import Candidate, clip, iso_from_ts

log = logging.getLogger(__name__)

# (outlet name, feed URL, weight). Checked working Oct 2026; Anthropic has no RSS feed.
FEEDS: list[tuple[str, str, float]] = [
    ("OpenAI", "https://openai.com/news/rss.xml", 1.0),
    ("Google DeepMind", "https://deepmind.google/blog/rss.xml", 1.0),
    ("Google", "https://blog.google/technology/ai/rss/", 0.9),
    ("MIT Technology Review", "https://www.technologyreview.com/topic/artificial-intelligence/feed", 0.85),
    ("The Verge", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", 0.8),
    ("TechCrunch", "https://techcrunch.com/category/artificial-intelligence/feed/", 0.8),
    ("Ars Technica", "https://arstechnica.com/ai/feed/", 0.8),
    ("Wired", "https://www.wired.com/feed/tag/ai/latest/rss", 0.8),
    ("The Decoder", "https://the-decoder.com/feed/", 0.75),
    ("NVIDIA", "https://blogs.nvidia.com/feed/", 0.6),
    ("Simon Willison", "https://simonwillison.net/atom/everything/", 0.6),
]
FEED_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AutoLinkediner/1.0; +https://github.com/kneat2448/AutoLinkediner)"}


def _text(html: str) -> str:
    return " ".join(BeautifulSoup(html or "", "html.parser").get_text(" ").split())


def normalize(entry: Any, outlet: str, weight: float) -> Candidate | None:
    """Convert one feedparser entry into a Candidate."""
    title = " ".join((entry.get("title") or "").split())
    url = entry.get("link") or ""
    stamp = entry.get("published_parsed") or entry.get("updated_parsed")
    if not (title and url and stamp):
        return None
    summary = _text(entry.get("summary") or "")
    content = entry.get("content") or []
    full = _text(content[0].get("value", "")) if content else ""
    return Candidate(
        id="news:" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:12],
        source="news",
        title=title,
        url=url,
        summary=clip(summary or full, 500),
        score=weight * 100,
        created_at=iso_from_ts(calendar.timegm(stamp)),
        raw_text=clip(full or summary, 3000),
        extra={"outlet": outlet, "weight": weight},
    )


def fetch_feed(outlet: str, url: str, weight: float, since: float) -> list[Candidate]:
    """Recent entries from one feed; [] on any failure."""
    try:
        parsed = feedparser.parse(http.get(url, headers=FEED_HEADERS, retries=2).content)
        out = []
        for entry in parsed.entries[:60]:
            c = normalize(entry, outlet, weight)
            if c and calendar.timegm(entry.get("published_parsed") or entry.get("updated_parsed")) >= since:
                out.append(c)
        return out
    except Exception:
        log.warning("news: %s feed failed", outlet)
        return []


def fetch() -> list[Candidate]:
    """Entries from all feeds published within LOOKBACK_HOURS."""
    try:
        since = time.time() - config.LOOKBACK_HOURS * 3600
        out: list[Candidate] = []
        for outlet, url, weight in FEEDS:
            out.extend(fetch_feed(outlet, url, weight, since))
        log.info("news: %d candidates from %d feeds", len(out), len(FEEDS))
        return out
    except Exception:
        log.exception("news: fetch failed")
        return []
