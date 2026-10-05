"""Tweets the owner forwarded to the Telegram bot (no scraping, no paid X API)."""
from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from src import config, http, state
from src.sources.common import Candidate, clip, parse_iso

log = logging.getLogger(__name__)

TWEET_URL_RE = re.compile(
    r"https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/([A-Za-z0-9_]+)/status(?:es)?/(\d+)\S*",
    re.IGNORECASE,
)
OEMBED_URL = "https://publish.twitter.com/oembed"


def find_tweet_url(text: str) -> re.Match[str] | None:
    """Return the first x.com/twitter.com status link in text, if any."""
    return TWEET_URL_RE.search(text or "")


def fetch_tweet_text(url: str) -> str:
    """Best-effort tweet text via the public oEmbed endpoint. Returns '' on any failure."""
    try:
        data = http.get(OEMBED_URL, params={"url": url, "omit_script": "1"}, retries=2).json()
        match = re.search(r"<p[^>]*>(.*?)</p>", data.get("html", ""), re.DOTALL)
        if not match:
            return ""
        text = re.sub(r"<br\s*/?>", "\n", match.group(1))
        text = re.sub(r"<[^>]+>", "", text)
        return html.unescape(text).strip()
    except Exception:
        log.warning("x_queue: tweet text fetch failed")
        return ""


def add(text: str) -> dict[str, Any] | None:
    """Queue a forwarded tweet. Uses the owner's accompanying text as raw_text, else fetches it.

    Returns the queued item (``raw_text`` may be '' if fetching failed), or None if no link.
    """
    match = find_tweet_url(text)
    if not match:
        return None
    author, tweet_id = match.group(1), match.group(2)
    url = f"https://x.com/{author}/status/{tweet_id}"
    owner_text = (text[: match.start()] + text[match.end():]).strip()
    raw_text = owner_text or fetch_tweet_text(url)
    queue = state.load(state.X_QUEUE)
    item = next((q for q in queue if q["id"] == tweet_id), None)
    if item:
        if raw_text:
            item["raw_text"] = raw_text
    else:
        item = {
            "id": tweet_id,
            "url": url,
            "author": author,
            "raw_text": raw_text,
            "added_at": datetime.now(timezone.utc).isoformat(),
        }
        queue.append(item)
    state.save(state.X_QUEUE, queue)
    return item


def awaiting_text() -> dict[str, Any] | None:
    """The most recent queued tweet that still has no text, if any."""
    return next((q for q in reversed(state.load(state.X_QUEUE)) if not q.get("raw_text")), None)


def set_text(tweet_id: str, text: str) -> None:
    """Attach pasted text to a queued tweet."""
    queue = state.load(state.X_QUEUE)
    for item in queue:
        if item["id"] == tweet_id:
            item["raw_text"] = text.strip()
    state.save(state.X_QUEUE, queue)


def remove(tweet_ids: set[str]) -> None:
    """Drop used tweets from the queue."""
    queue = state.load(state.X_QUEUE)
    state.save(state.X_QUEUE, [q for q in queue if q["id"] not in tweet_ids])


def normalize(item: dict[str, Any]) -> Candidate | None:
    """Convert a queued tweet into a Candidate (skipped if it has no text yet)."""
    text = (item.get("raw_text") or "").strip()
    if not text:
        return None
    return Candidate(
        id=f"x:{item['id']}",
        source="x",
        title=clip(text.split("\n")[0], 140),
        url=item["url"],
        summary=clip(text, 500),
        score=0.0,
        created_at=item.get("added_at", ""),
        raw_text=text,
        extra={"author": item.get("author", "")},
    )


def fetch() -> list[Candidate]:
    """Queued tweets younger than X_QUEUE_MAX_AGE_DAYS that have text."""
    try:
        queue = state.load(state.X_QUEUE)
        cutoff = datetime.now(timezone.utc) - timedelta(days=config.X_QUEUE_MAX_AGE_DAYS)
        fresh = [q for q in queue if not q.get("added_at") or parse_iso(q["added_at"]) >= cutoff]
        if len(fresh) != len(queue):
            state.save(state.X_QUEUE, fresh)
        out = [c for c in (normalize(q) for q in fresh) if c]
        log.info("x_queue: %d candidates", len(out))
        return out
    except Exception:
        log.exception("x_queue: fetch failed")
        return []
