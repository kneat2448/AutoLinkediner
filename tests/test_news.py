import time

import feedparser

from src import rank
from src.sources import news

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Outlet</title>
<item>
  <title>OpenAI launches a new reasoning model for businesses</title>
  <link>https://example.com/openai-model</link>
  <pubDate>{now}</pubDate>
  <description>&lt;p&gt;The model is aimed at &lt;b&gt;finance&lt;/b&gt; teams.&lt;/p&gt;</description>
</item>
<item>
  <title>An old story</title>
  <link>https://example.com/old</link>
  <pubDate>Mon, 01 Jan 2024 10:00:00 GMT</pubDate>
</item>
</channel></rss>"""


def _feed():
    now = time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime())
    return feedparser.parse(RSS.format(now=now))


def test_news_normalize():
    entry = _feed().entries[0]
    c = news.normalize(entry, "The Verge", 0.8)
    assert c["source"] == "news"
    assert c["id"].startswith("news:")
    assert c["summary"] == "The model is aimed at finance teams."
    assert c["extra"] == {"outlet": "The Verge", "weight": 0.8}
    assert rank.source_credit(c) == "The Verge"
    assert rank.source_tag(c) == "via The Verge"


def test_news_fetch_feed_filters_old(monkeypatch):
    class Resp:
        content = RSS.format(now=time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime())).encode()
    monkeypatch.setattr(news.http, "get", lambda *a, **k: Resp())
    out = news.fetch_feed("Outlet", "https://x", 0.8, since=time.time() - 3600)
    assert [c["url"] for c in out] == ["https://example.com/openai-model"]


def test_news_feed_failure_returns_empty(monkeypatch):
    def boom(*a, **k):
        raise ConnectionError
    monkeypatch.setattr(news.http, "get", boom)
    assert news.fetch_feed("Outlet", "https://x", 0.8, since=0) == []


def _c(id_, title, source="news", outlet=None, weight=0.8):
    extra = {"outlet": outlet, "weight": weight} if outlet else {}
    return {"id": id_, "source": source, "title": title, "url": f"https://e.com/{id_}", "summary": "",
            "score": 100.0, "created_at": "2026-10-05T00:00:00+00:00", "raw_text": "", "extra": extra}


def test_coverage_boosts_widely_reported_story():
    cands = [
        _c("a", "Google releases Gemini 4 with stronger reasoning", outlet="The Verge"),
        _c("b", "Gemini 4 released: Google's stronger reasoning model", outlet="TechCrunch"),
        _c("c", "Google Gemini 4 brings stronger reasoning", source="hackernews"),
        _c("d", "A startup raises money for robot kitchens", outlet="Wired"),
    ]
    cov = rank.coverage(cands)
    assert cov["a"] == 2 and cov["d"] == 0
    scores = rank.heuristic_scores(cands)
    assert scores["a"] > scores["d"]
