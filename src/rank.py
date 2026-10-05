"""Dedupe, heuristic scoring, the LLM final pick, and context fetching for the chosen story."""
from __future__ import annotations

import logging
import math
import re
from collections import defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from src import config, http, llm
from src.sources import hackernews
from src.sources.common import Candidate, clip, parse_iso

log = logging.getLogger(__name__)

RECENCY_HALF_LIFE_HOURS = 18.0
MAX_PER_SOURCE = 4
CONTEXT_LIMIT = 6000
_TRACKING_PARAMS = re.compile(r"^(utm_|ref$|ref_src$|source$|s$|t$|fbclid$|gclid$)")


# ---------- dedupe ----------

def normalize_url(url: str) -> str:
    """Canonical form of a URL for dedupe: lowercase host, no www/fragment/tracking/trailing slash."""
    parts = urlsplit((url or "").strip())
    host = parts.netloc.lower().removeprefix("www.").removeprefix("m.")
    if host == "twitter.com":
        host = "x.com"
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if not _TRACKING_PARAMS.match(k)])
    path = parts.path.rstrip("/")
    return urlunsplit(("https", host, path, query, ""))


def normalize_title(title: str) -> str:
    """Lowercase, alphanumerics only, single spaces."""
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", (title or "").lower()).split())


def titles_match(a: str, b: str, threshold: float = config.FUZZY_TITLE_THRESHOLD) -> bool:
    """Fuzzy title equality."""
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return False
    return na == nb or SequenceMatcher(None, na, nb).ratio() >= threshold


def is_duplicate(candidate: Candidate, history: Iterable[dict[str, Any]]) -> bool:
    """True if the candidate matches any history entry by id, URL, or fuzzy title."""
    url = normalize_url(candidate.get("url", ""))
    for item in history:
        if item.get("id") and item["id"] == candidate.get("id"):
            return True
        if item.get("url") and normalize_url(item["url"]) == url:
            return True
        if item.get("title") and titles_match(item["title"], candidate.get("title", "")):
            return True
    return False


def dedupe(candidates: list[Candidate], posted: list[dict[str, Any]]) -> list[Candidate]:
    """Drop candidates already used (posted.json) and duplicates within the batch."""
    kept: list[Candidate] = []
    for c in candidates:
        if is_duplicate(c, posted) or is_duplicate(c, kept):
            continue
        kept.append(c)
    log.info("dedupe: %d -> %d candidates", len(candidates), len(kept))
    return kept


# ---------- heuristic ranking ----------

def heuristic_scores(candidates: list[Candidate], now: datetime | None = None) -> dict[str, float]:
    """Score = 0.7·engagement (log-normalized within its source) + 0.3·recency (+ X-queue boost)."""
    now = now or datetime.now(timezone.utc)
    max_by_source: dict[str, float] = defaultdict(float)
    for c in candidates:
        max_by_source[c["source"]] = max(max_by_source[c["source"]], c.get("score", 0.0))
    scores: dict[str, float] = {}
    for c in candidates:
        top = max_by_source[c["source"]]
        engagement = math.log1p(c.get("score", 0.0)) / math.log1p(top) if top > 0 else 0.0
        try:
            age_h = max(0.0, (now - parse_iso(c["created_at"])).total_seconds() / 3600)
            recency = 0.5 ** (age_h / RECENCY_HALF_LIFE_HOURS)
        except (KeyError, ValueError):
            recency = 0.0
        score = 0.7 * engagement + 0.3 * recency
        if c["source"] == "x":
            score += config.X_QUEUE_BOOST + 0.7  # owner's own taste: treat as top engagement + boost
        scores[c["id"]] = round(score, 4)
    return scores


def shortlist(candidates: list[Candidate], size: int = config.SHORTLIST_SIZE) -> list[Candidate]:
    """Top candidates by heuristic score, at most MAX_PER_SOURCE per source (X queue uncapped)."""
    scores = heuristic_scores(candidates)
    ordered = sorted(candidates, key=lambda c: scores[c["id"]], reverse=True)
    per_source: dict[str, int] = defaultdict(int)
    out: list[Candidate] = []
    for c in ordered:
        if c["source"] != "x" and per_source[c["source"]] >= MAX_PER_SOURCE:
            continue
        per_source[c["source"]] += 1
        out.append(c)
        if len(out) >= size:
            break
    return out


# ---------- LLM pick ----------

SOURCE_LABELS = {
    "hackernews": "Hacker News",
    "reddit": "Reddit",
    "huggingface": "Hugging Face paper",
    "x": "Forwarded by owner (X)",
}


def pick(candidates: list[Candidate]) -> Candidate | None:
    """Ask the LLM to pick the best story for a general audience. Falls back to the top heuristic."""
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    lines = []
    for i, c in enumerate(candidates, 1):
        lines.append(
            f"[{i}] ({SOURCE_LABELS.get(c['source'], c['source'])}, engagement {int(c.get('score', 0))})\n"
            f"Title: {c['title']}\nSummary: {clip(c.get('summary', ''), 400) or '(none)'}"
        )
    prompt = (config.PROMPTS_DIR / "pick.md").read_text(encoding="utf-8").replace(
        "{{CANDIDATES}}", "\n\n".join(lines)
    )
    try:
        result = llm.complete_json(prompt, temperature=0.2)
        index = int(result["index"])
        if 1 <= index <= len(candidates):
            log.info("pick: #%d %s (%s)", index, candidates[index - 1]["title"], result.get("reason", ""))
            return candidates[index - 1]
        log.warning("pick: index %s out of range, using top heuristic", index)
    except Exception:
        log.exception("pick: LLM pick failed, using top heuristic")
    return candidates[0]


# ---------- context ----------

def fetch_article_text(url: str, limit: int = 4000) -> str:
    """Best-effort readable text from a web page (paragraph text only)."""
    host = urlsplit(url).netloc.lower()
    if any(h in host for h in ("x.com", "twitter.com", "reddit.com", "youtube.com", "news.ycombinator.com")):
        return ""
    try:
        resp = http.get(url, retries=2, timeout=15)
        if "html" not in resp.headers.get("Content-Type", ""):
            return ""
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
            tag.decompose()
        root = soup.find("article") or soup.find("main") or soup.body or soup
        paragraphs = [p.get_text(" ", strip=True) for p in root.find_all("p")]
        text = "\n".join(p for p in paragraphs if len(p.split()) >= 8)
        return text[:limit]
    except Exception:
        log.warning("context: could not fetch article from %s", host)
        return ""


def gather_context(candidate: Candidate) -> str:
    """Collect grounding material for the chosen story (article text, abstract, top HN comment)."""
    parts = [f"Title: {candidate['title']}"]
    if candidate.get("raw_text"):
        label = {"huggingface": "Paper abstract", "x": "Tweet text", "reddit": "Post text"}.get(
            candidate["source"], "Text"
        )
        parts.append(f"{label}:\n{candidate['raw_text']}")
    elif candidate.get("summary"):
        parts.append(f"Summary:\n{candidate['summary']}")
    article = fetch_article_text(candidate["url"])
    if article:
        parts.append(f"Article text (excerpt):\n{article}")
    if candidate["source"] == "hackernews":
        comment = hackernews.top_comment(candidate)
        if comment:
            parts.append(f"A top reader comment on Hacker News (opinion, not fact):\n{comment}")
    return "\n\n".join(parts)[:CONTEXT_LIMIT]


def source_credit(candidate: Candidate) -> str:
    """Human-readable credit for the `Source:` line."""
    src = candidate["source"]
    if src == "huggingface":
        return "Hugging Face Daily Papers"
    if src == "x":
        author = candidate.get("extra", {}).get("author")
        return f"@{author} on X" if author else "X"
    host = urlsplit(candidate.get("url", "")).netloc.lower().removeprefix("www.")
    if src == "reddit" and (not host or host.endswith("reddit.com")):
        sub = candidate.get("extra", {}).get("subreddit")
        return f"r/{sub}" if sub else "Reddit"
    if src == "hackernews" and host == "news.ycombinator.com":
        return "Hacker News"
    return host or SOURCE_LABELS.get(src, src)


def source_tag(candidate: Candidate) -> str:
    """Short tag for the image card, e.g. 'via Hugging Face'."""
    if candidate["source"] == "huggingface":
        return "via Hugging Face"
    return f"via {source_credit(candidate)}"
