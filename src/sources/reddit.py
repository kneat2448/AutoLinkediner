"""Reddit via PRAW using a personal "script" app (read-only)."""
from __future__ import annotations

import logging
import time
from typing import Any

from src import config
from src.sources.common import Candidate, clip, iso_from_ts

log = logging.getLogger(__name__)


def normalize(post: Any) -> Candidate | None:
    """Convert a PRAW Submission (or any object with the same attributes) into a Candidate."""
    if getattr(post, "stickied", False) or getattr(post, "over_18", False):
        return None
    if (post.score or 0) <= config.REDDIT_MIN_SCORE:
        return None
    permalink = f"https://www.reddit.com{post.permalink}"
    url = post.url if not post.is_self and post.url else permalink
    return Candidate(
        id=f"reddit:{post.id}",
        source="reddit",
        title=post.title,
        url=url,
        summary=clip(post.selftext or "", 500),
        score=float(post.score),
        created_at=iso_from_ts(post.created_utc),
        raw_text=clip(post.selftext or "", 3000),
        extra={"discussion_url": permalink, "subreddit": str(post.subreddit)},
    )


def fetch() -> list[Candidate]:
    """Top posts of the day from the configured subreddits with score above REDDIT_MIN_SCORE."""
    client_id = config.env("REDDIT_CLIENT_ID")
    secret = config.env("REDDIT_CLIENT_SECRET")
    if not (client_id and secret):
        log.warning("reddit: REDDIT_CLIENT_ID/SECRET not set, skipping")
        return []
    try:
        import praw

        reddit = praw.Reddit(
            client_id=client_id,
            client_secret=secret,
            user_agent=config.env("REDDIT_USER_AGENT", "AutoLinkediner/1.0"),
            check_for_async=False,
            timeout=config.HTTP_TIMEOUT,
        )
        reddit.read_only = True
        since = time.time() - config.LOOKBACK_HOURS * 3600
        out: list[Candidate] = []
        for name in config.REDDIT_SUBREDDITS:
            try:
                for post in reddit.subreddit(name).top(time_filter="day", limit=25):
                    if post.created_utc >= since and (c := normalize(post)):
                        out.append(c)
            except Exception:
                log.exception("reddit: r/%s failed", name)
        log.info("reddit: %d candidates", len(out))
        return out
    except Exception:
        log.exception("reddit: fetch failed")
        return []
