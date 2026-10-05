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
SOURCE_CAPS = {"news": 6, "x": 99}   # news covers many outlets; owner-forwarded tweets are never capped
BUZZ_PER_OUTLET = 0.15               # boost per extra outlet covering the same development
BUZZ_MAX = 0.45
BUZZ_SIMILARITY = 0.35
CONTEXT_LIMIT = 14000   # characters of source material given to the writer
ARTICLE_LIMIT = 9000
RESEARCHED_CONTEXT_LIMIT = 24000   # context + research notes
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

_STOPWORDS = set("""a an and are as at be by for from has have how in into is it its new of on or that the
their this to was what when why will with you your ai says say after over about more than just now""".split())


def _keywords(title: str) -> set[str]:
    return {w for w in normalize_title(title).split() if len(w) > 2 and w not in _STOPWORDS}


def _outlet(c: Candidate) -> str:
    return c.get("extra", {}).get("outlet") or c["source"]


def coverage(candidates: list[Candidate]) -> dict[str, int]:
    """How many *other* outlets/sources carry a similar headline (a sign of a big development)."""
    words = {c["id"]: _keywords(c["title"]) for c in candidates}
    out: dict[str, int] = {}
    for c in candidates:
        others = set()
        for o in candidates:
            if o["id"] == c["id"] or _outlet(o) == _outlet(c):
                continue
            a, b = words[c["id"]], words[o["id"]]
            if a and b and len(a & b) / len(a | b) >= BUZZ_SIMILARITY:
                others.add(_outlet(o))
        out[c["id"]] = len(others)
    return out


def _same_story_as_any(c: Candidate, others: list[Candidate]) -> bool:
    a = _keywords(c["title"])
    for o in others:
        b = _keywords(o["title"])
        if a and b and len(a & b) / len(a | b) >= BUZZ_SIMILARITY:
            return True
    return False


def heuristic_scores(candidates: list[Candidate], now: datetime | None = None) -> dict[str, float]:
    """Score = 0.7·engagement + 0.3·recency, plus a buzz boost and the X-queue boost.

    Engagement is log-normalized within each source; for RSS news it's the outlet weight.
    """
    now = now or datetime.now(timezone.utc)
    max_by_source: dict[str, float] = defaultdict(float)
    for c in candidates:
        max_by_source[c["source"]] = max(max_by_source[c["source"]], c.get("score", 0.0))
    buzz = coverage(candidates)
    scores: dict[str, float] = {}
    for c in candidates:
        top = max_by_source[c["source"]]
        if c["source"] == "news":
            engagement = float(c.get("extra", {}).get("weight", 0.7))
        else:
            engagement = math.log1p(c.get("score", 0.0)) / math.log1p(top) if top > 0 else 0.0
        try:
            age_h = max(0.0, (now - parse_iso(c["created_at"])).total_seconds() / 3600)
            recency = 0.5 ** (age_h / RECENCY_HALF_LIFE_HOURS)
        except (KeyError, ValueError):
            recency = 0.0
        score = 0.7 * engagement + 0.3 * recency + min(BUZZ_MAX, BUZZ_PER_OUTLET * buzz[c["id"]])
        c.setdefault("extra", {})["coverage"] = buzz[c["id"]]
        if c["source"] == "x":
            score += config.X_QUEUE_BOOST + 0.7  # owner's own taste: treat as top engagement + boost
        scores[c["id"]] = round(score, 4)
    return scores


def shortlist(candidates: list[Candidate], size: int = config.SHORTLIST_SIZE) -> list[Candidate]:
    """Top candidates by heuristic score, capped per source (SOURCE_CAPS, else MAX_PER_SOURCE)."""
    scores = heuristic_scores(candidates)
    ordered = sorted(candidates, key=lambda c: scores[c["id"]], reverse=True)
    per_source: dict[str, int] = defaultdict(int)
    out: list[Candidate] = []
    for c in ordered:
        if per_source[c["source"]] >= SOURCE_CAPS.get(c["source"], MAX_PER_SOURCE):
            continue
        if _same_story_as_any(c, out):  # keep only the best-scored version of a widely covered story
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
    "news": "News",
}


def _label(c: Candidate) -> str:
    extra = c.get("extra", {})
    if c["source"] == "news":
        label = f"{extra.get('outlet', 'News')}, published {c.get('created_at', '')[:10]}"
    else:
        label = f"{SOURCE_LABELS.get(c['source'], c['source'])}, engagement {int(c.get('score', 0))}"
    if extra.get("coverage"):
        label += f", also covered by {extra['coverage']} other source(s)"
    return label


def pick(candidates: list[Candidate]) -> Candidate | None:
    """Ask the LLM to pick the best story for a general audience. Falls back to the top heuristic."""
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    lines = []
    for i, c in enumerate(candidates, 1):
        lines.append(
            f"[{i}] ({_label(c)})\n"
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

_CITATION_RE = re.compile(r"\(\s*[A-Z][^()]{0,200}?\bet al\.?[^()]*\)|\[\d+(?:[,–-]\s*\d+)*\]")


def fetch_article_text(url: str, limit: int = ARTICLE_LIMIT) -> str:
    """Best-effort readable text from a web page (paragraph text only, citations stripped)."""
    host = urlsplit(url).netloc.lower()
    if any(h in host for h in ("x.com", "twitter.com", "reddit.com", "youtube.com", "news.ycombinator.com")):
        return ""
    try:
        resp = http.get(url, retries=2, timeout=20)
        if "html" not in resp.headers.get("Content-Type", ""):
            return ""
        soup = BeautifulSoup(resp.content, "html.parser")  # bytes: let bs4 detect the encoding
        for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form", "figure", "table"]):
            tag.decompose()
        root = soup.find("article") or soup.find("main") or soup.body or soup
        paragraphs = [_CITATION_RE.sub("", p.get_text(" ", strip=True)) for p in root.find_all("p")]
        text = "\n".join(" ".join(p.split()) for p in paragraphs if len(p.split()) >= 8)
        return text[:limit]
    except Exception:
        log.warning("context: could not fetch article from %s", host)
        return ""


def gather_context(candidate: Candidate) -> str:
    """Collect grounding material for the chosen story.

    Article text for links, the full paper (arXiv HTML) for Hugging Face papers,
    and the top HN comment, so the post can go into real detail.
    """
    parts = [f"Title: {candidate['title']}"]
    if candidate.get("raw_text"):
        label = {"huggingface": "Paper abstract", "x": "Tweet text", "reddit": "Post text"}.get(
            candidate["source"], "Text"
        )
        if candidate["source"] == "x" and candidate.get("extra", {}).get("tweet_text"):
            label = "Owner's note on this tweet"
        parts.append(f"{label}:\n{candidate['raw_text']}")
        if candidate["source"] == "x" and candidate.get("extra", {}).get("tweet_text"):
            parts.append(f"Tweet text:\n{candidate['extra']['tweet_text']}")
    elif candidate.get("summary"):
        parts.append(f"Summary:\n{candidate['summary']}")
    if candidate["source"] == "huggingface":
        paper_id = candidate["id"].split(":", 1)[1]
        paper = fetch_article_text(f"https://arxiv.org/html/{paper_id}")
        # The HTML starts with the abstract we already have; keep only the new paragraphs.
        abstract = candidate.get("raw_text", "")
        paper = "\n".join(p for p in paper.split("\n") if p[:80] not in abstract)
        if paper:
            parts.append(f"Paper body (excerpt, introduction and method):\n{paper}")
    else:
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
    if src == "news":
        return candidate.get("extra", {}).get("outlet") or "News"
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
