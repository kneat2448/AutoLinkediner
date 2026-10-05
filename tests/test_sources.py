from types import SimpleNamespace

from src.sources import hackernews, huggingface, reddit, x_queue

KEYS = {"id", "source", "title", "url", "summary", "score", "created_at", "raw_text"}


def test_hackernews_normalize_filters_non_ai(load_fixture):
    hits = load_fixture("hn_search.json")["hits"]
    out = [c for c in (hackernews.normalize(h) for h in hits) if c]
    assert [c["id"] for c in out] == ["hn:41000001", "hn:41000004"]
    first = out[0]
    assert KEYS <= first.keys()
    assert first["source"] == "hackernews"
    assert first["score"] == 512.0
    assert first["created_at"].startswith("2025-")
    # Self posts fall back to the discussion URL
    assert out[1]["url"] == "https://news.ycombinator.com/item?id=41000004"


def test_hackernews_keyword_word_boundaries():
    assert hackernews.is_ai_title("New AI agents for spreadsheets")
    assert hackernews.is_ai_title("Claude gets memory")
    assert not hackernews.is_ai_title("Said the farmer about rain")  # "ai" inside a word
    assert not hackernews.is_ai_title("A text editor in Rust")


def test_huggingface_normalize(load_fixture):
    items = load_fixture("hf_daily_papers.json")
    out = [c for c in (huggingface.normalize(i) for i in items) if c]
    assert len(out) == 1
    c = out[0]
    assert KEYS <= c.keys()
    assert c["id"] == "hf:2610.01234"
    assert c["title"] == "Small Models Reason Well"
    assert c["url"] == "https://huggingface.co/papers/2610.01234"
    assert c["score"] == 42.0
    assert "3B parameter" in c["raw_text"]


def _post(**kw):
    base = dict(id="abc", title="Local LLM runs on a phone", score=250, permalink="/r/LocalLLaMA/comments/abc/x/",
                url="https://blog.example.com/post", is_self=False, selftext="", created_utc=1759600000,
                subreddit="LocalLLaMA", stickied=False, over_18=False)
    base.update(kw)
    return SimpleNamespace(**base)


def test_reddit_normalize():
    c = reddit.normalize(_post())
    assert KEYS <= c.keys()
    assert c["id"] == "reddit:abc"
    assert c["url"] == "https://blog.example.com/post"
    assert c["extra"]["discussion_url"].startswith("https://www.reddit.com/r/LocalLLaMA/")


def test_reddit_normalize_filters():
    assert reddit.normalize(_post(score=50)) is None
    assert reddit.normalize(_post(stickied=True)) is None
    self_post = reddit.normalize(_post(is_self=True, selftext="Body text"))
    assert self_post["url"].startswith("https://www.reddit.com/")
    assert self_post["raw_text"] == "Body text"


def test_reddit_fetch_without_credentials_returns_empty(monkeypatch):
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    assert reddit.fetch() == []


def test_x_queue_add_with_owner_text_and_normalize(tmp_state, monkeypatch):
    monkeypatch.setattr(x_queue, "fetch_tweet", lambda url: ("The tweet itself", []))
    item = x_queue.add("Big news on open models https://twitter.com/someone/status/12345?s=20")
    assert item["raw_text"] == "Big news on open models"
    assert item["url"] == "https://x.com/someone/status/12345"
    c = x_queue.normalize(item)
    assert c["id"] == "x:12345" and c["source"] == "x"
    assert x_queue.fetch()[0]["id"] == "x:12345"


def test_x_queue_without_text_is_not_a_candidate(tmp_state, monkeypatch):
    monkeypatch.setattr(x_queue, "fetch_tweet", lambda url: ("", []))
    item = x_queue.add("https://x.com/someone/status/999")
    assert item["raw_text"] == ""
    assert x_queue.fetch() == []
    x_queue.set_text("999", "Pasted tweet text")
    assert x_queue.fetch()[0]["raw_text"] == "Pasted tweet text"


def test_source_failure_returns_empty(monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("down")
    monkeypatch.setattr(hackernews.http, "get", boom)
    assert hackernews.fetch() == []
    assert huggingface.fetch() == []
