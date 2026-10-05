"""Web research for a chosen story: related news coverage, linked pages, and plain-language background.

Used for every owner-forwarded tweet (a tweet alone is too thin to write a detailed post from)
and for any story whose fetched context is thin. All sources are free and keyless:
Bing News RSS, Hacker News (Algolia), and the Wikipedia API. Costs one LLM call (the plan).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlsplit

import feedparser

from src import config, http, llm, rank
from src.sources import hackernews
from src.sources.common import Candidate, clip

log = logging.getLogger(__name__)

BING_NEWS_RSS = "https://www.bing.com/news/search"
WIKI_SEARCH = "https://en.wikipedia.org/w/api.php"
WIKI_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
HN_SEARCH = "https://hn.algolia.com/api/v1/search"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AutoLinkediner/1.0; +https://github.com/kneat2448/AutoLinkediner)"}

MAX_ARTICLES = 3
ARTICLE_CHARS = 2500
THIN_CONTEXT_CHARS = 2500   # research non-X stories when gathered context is shorter than this
SKIP_HOSTS = ("x.com", "twitter.com", "t.co", "reddit.com", "youtube.com", "youtu.be", "instagram.com",
              "facebook.com", "linkedin.com", "tiktok.com")


@dataclass
class Research:
    """Research notes plus the outlets and links they came from."""

    notes: str = ""
    outlets: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)


def needs_research(candidate: Candidate, context: str) -> bool:
    """Always for owner-forwarded tweets; otherwise only when the context is thin."""
    return candidate["source"] == "x" or len(context) < THIN_CONTEXT_CHARS


def plan(story: str, fallback_title: str) -> dict[str, Any]:
    """LLM research plan: topic, 2–3 search queries, 0–2 background terms. Falls back to the title."""
    prompt = (config.PROMPTS_DIR / "research.md").read_text(encoding="utf-8").replace("{{STORY}}", story[:3000])
    try:
        result = llm.complete_json(prompt, temperature=0.2)
        queries = [q.strip() for q in result.get("queries", []) if isinstance(q, str) and q.strip()][:3]
        background = [b.strip() for b in result.get("background", []) if isinstance(b, str) and b.strip()][:2]
        if queries:
            log.info("research: plan topic=%r queries=%s background=%s", result.get("topic"), queries, background)
            return {"topic": result.get("topic", ""), "queries": queries, "background": background}
    except Exception:
        log.exception("research: plan failed; searching by title")
    return {"topic": fallback_title, "queries": [fallback_title[:100]], "background": []}


def unwrap_bing(link: str) -> str:
    """Bing News RSS links are click-trackers; the real article URL is in the `url` parameter."""
    params = parse_qs(urlsplit(link).query)
    return params.get("url", [link])[0]


def _host(url: str) -> str:
    return urlsplit(url).netloc.lower().removeprefix("www.")


def _skip(host: str) -> bool:
    return any(host == h or host.endswith("." + h) for h in SKIP_HOSTS)


def news_search(query: str, limit: int = 6) -> list[dict[str, str]]:
    """Recent news articles for a query via Bing News RSS: [{title, url, outlet, summary}]."""
    try:
        resp = http.get(BING_NEWS_RSS, params={"q": query, "format": "rss"}, headers=HEADERS, retries=2)
        out = []
        for entry in feedparser.parse(resp.content).entries[:limit]:
            url = unwrap_bing(entry.get("link", ""))
            if not url.startswith("http"):
                continue
            outlet = entry.get("news_source") or entry.get("source", {}).get("title") or _host(url)
            out.append({"title": entry.get("title", ""), "url": url, "outlet": str(outlet),
                        "summary": clip(rank._CITATION_RE.sub("", entry.get("summary", "")), 300)})
        return out
    except Exception:
        log.warning("research: news search failed for %r", query)
        return []


def wikipedia(term: str) -> tuple[str, str]:
    """(title, plain-language summary) for the best Wikipedia match, or ('', '')."""
    try:
        hits = http.get(WIKI_SEARCH, headers=HEADERS, retries=2, params={
            "action": "query", "list": "search", "srsearch": term, "srlimit": 1, "format": "json",
        }).json()["query"]["search"]
        if not hits:
            return "", ""
        title = hits[0]["title"]
        data = http.get(WIKI_SUMMARY.format(title=title.replace(" ", "_")), headers=HEADERS, retries=2).json()
        return title, clip(data.get("extract", ""), 900)
    except Exception:
        log.warning("research: wikipedia lookup failed for %r", term)
        return "", ""


def hn_discussion(query: str) -> str:
    """Title + top comment of the most-discussed related HN story, if any."""
    try:
        hits = http.get(HN_SEARCH, retries=2, params={
            "query": query, "tags": "story", "numericFilters": "points>50", "hitsPerPage": 1,
        }).json().get("hits", [])
        if not hits:
            return ""
        hit = hits[0]
        comment = hackernews.top_comment({"id": f"hn:{hit['objectID']}"})  # type: ignore[typeddict-item]
        text = f"Related Hacker News thread: \"{hit.get('title')}\" ({hit.get('points')} points)"
        return text + (f"\nTop reader comment (opinion, not fact): {comment}" if comment else "")
    except Exception:
        log.warning("research: HN search failed")
        return ""


def research(candidate: Candidate, story: str) -> Research:
    """Run the research plan and return formatted notes for the writer."""
    result = Research()
    the_plan = plan(story, candidate["title"])
    sections: list[str] = []
    seen_hosts = {_host(candidate.get("url", ""))}

    # 1. Pages linked from the tweet / post itself (primary sources)
    for url in candidate.get("extra", {}).get("links", [])[:2]:
        if _skip(_host(url)):
            continue
        text = rank.fetch_article_text(url, limit=ARTICLE_CHARS)
        if text:
            sections.append(f"Linked page ({_host(url)}):\n{text}")
            result.links.append(url)
            seen_hosts.add(_host(url))

    # 2. News coverage, one article per outlet
    articles: list[dict[str, str]] = []
    for query in the_plan["queries"]:
        for art in news_search(query):
            host = _host(art["url"])
            if host in seen_hosts or _skip(host):
                continue
            seen_hosts.add(host)
            articles.append(art)
    for art in articles:
        if len(result.outlets) >= MAX_ARTICLES:
            break
        text = rank.fetch_article_text(art["url"], limit=ARTICLE_CHARS) or art["summary"]
        if not text:
            continue
        sections.append(f"Coverage from {art['outlet']}: \"{art['title']}\"\n{text}")
        result.outlets.append(art["outlet"])
        result.links.append(art["url"])

    # 3. Background a non-expert needs
    for term in the_plan["background"]:
        title, summary = wikipedia(term)
        if summary:
            sections.append(f"Background ({title}, Wikipedia):\n{summary}")

    # 4. What technical readers are saying
    hn = hn_discussion(the_plan["queries"][0])
    if hn:
        sections.append(hn)

    if sections:
        header = (f"Research notes on: {the_plan['topic'] or candidate['title']}\n"
                  "(Found by web search. Some coverage may be older background. Use it for context and "
                  "explanation, but don't present older events as new, and keep the main story's facts primary.)")
        result.notes = header + "\n\n" + "\n\n".join(sections)
    log.info("research: %d sections, outlets=%s", len(sections), result.outlets)
    return result


def credit_with(base: str, outlets: list[str]) -> str:
    """'@user on X' + up to two outlets whose reporting the post drew on."""
    extra = [o for o in dict.fromkeys(outlets) if o and o != base][:2]
    return f"{base}, with reporting from {' and '.join(extra)}" if extra else base
