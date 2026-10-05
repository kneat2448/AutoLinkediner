from src import research
from src.sources import x_queue


def _x_candidate(**extra):
    return {"id": "x:1", "source": "x", "title": "Firm uses AI for trading", "url": "https://x.com/a/status/1",
            "summary": "", "score": 0, "created_at": "2026-10-05T00:00:00+00:00",
            "raw_text": "Firm uses AI for trading", "extra": {"author": "a", **extra}}


def test_unwrap_bing():
    link = ("http://www.bing.com/news/apiclick.aspx?ref=FexRss&aid=&tid=abc"
            "&url=https%3a%2f%2fwww.example.com%2fstory%3fid%3d1&c=2")
    assert research.unwrap_bing(link) == "https://www.example.com/story?id=1"
    assert research.unwrap_bing("https://plain.com/a") == "https://plain.com/a"


def test_needs_research():
    assert research.needs_research(_x_candidate(), "x" * 10_000)
    hn = {**_x_candidate(), "source": "hackernews"}
    assert research.needs_research(hn, "short")
    assert not research.needs_research(hn, "x" * 10_000)


def test_credit_with():
    assert research.credit_with("@a on X", ["Reuters", "Reuters", "CNBC", "Wired"]) == \
        "@a on X, with reporting from Reuters and CNBC"
    assert research.credit_with("@a on X", []) == "@a on X"


def test_skip_hosts_exact():
    assert research._skip("t.co") and research._skip("mobile.twitter.com")
    assert not research._skip("mint.co") and not research._skip("livemint.com")


def test_research_builds_notes(monkeypatch):
    monkeypatch.setattr(research, "plan", lambda story, title: {
        "topic": "Firm X uses AI for trading", "queries": ["AI trading firm"], "background": ["algorithmic trading"]})
    monkeypatch.setattr(research, "news_search", lambda q: [
        {"title": "Story A", "url": "https://news-a.com/1", "outlet": "News A", "summary": "sa"},
        {"title": "Story A again", "url": "https://news-a.com/2", "outlet": "News A", "summary": "dup outlet"},
        {"title": "Story B", "url": "https://news-b.com/1", "outlet": "News B", "summary": "sb"},
        {"title": "Tweet", "url": "https://x.com/z/status/2", "outlet": "X", "summary": ""},
    ])
    monkeypatch.setattr(research.rank, "fetch_article_text", lambda url, limit=0: f"text of {url}")
    monkeypatch.setattr(research, "wikipedia", lambda term: ("Algorithmic trading", "Trading using computers."))
    monkeypatch.setattr(research, "hn_discussion", lambda q: "")
    found = research.research(_x_candidate(links=["https://firm.com/blog"]), "story")
    assert found.outlets == ["News A", "News B"]
    assert found.links == ["https://firm.com/blog", "https://news-a.com/1", "https://news-b.com/1"]
    assert "Linked page (firm.com)" in found.notes
    assert "Coverage from News B" in found.notes
    assert "Background (Algorithmic trading, Wikipedia)" in found.notes


def test_x_queue_keeps_tweet_text_and_links(tmp_state, monkeypatch):
    monkeypatch.setattr(x_queue, "fetch_tweet", lambda url: ("Tweet body", ["https://t.co/abc"]))
    monkeypatch.setattr(x_queue, "expand_links", lambda links: ["https://firm.com/blog"] if links else [])
    item = x_queue.add("My note about this https://x.com/a/status/5")
    assert item["raw_text"] == "My note about this"
    assert item["tweet_text"] == "Tweet body"
    assert item["links"] == ["https://firm.com/blog"]
    c = x_queue.normalize(item)
    assert c["extra"]["tweet_text"] == "Tweet body"
