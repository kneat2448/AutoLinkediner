from src import rank


def cand(id_, title, url, source="hackernews", score=100.0, created_at="2026-10-05T00:00:00+00:00"):
    return {"id": id_, "source": source, "title": title, "url": url, "summary": "", "score": score,
            "created_at": created_at, "raw_text": ""}


def test_normalize_url():
    assert rank.normalize_url("https://www.Example.com/a/?utm_source=x&id=3#top") == "https://example.com/a?id=3"
    assert rank.normalize_url("http://twitter.com/u/status/1") == rank.normalize_url("https://x.com/u/status/1")


def test_dedupe_against_history_by_url_and_title():
    posted = [
        {"id": "hn:1", "url": "https://example.com/story", "title": "OpenAI releases new model"},
    ]
    candidates = [
        cand("hn:9", "Something else", "https://www.example.com/story/?utm_campaign=z"),  # same URL
        cand("reddit:2", "OpenAI Releases New Model!", "https://other.com/x"),           # fuzzy title
        cand("hn:3", "A different story entirely", "https://new.com/y"),
    ]
    assert [c["id"] for c in rank.dedupe(candidates, posted)] == ["hn:3"]


def test_dedupe_within_batch():
    candidates = [
        cand("hn:1", "Google ships Gemini update", "https://blog.google/gemini"),
        cand("reddit:1", "Google ships Gemini update", "https://blog.google/gemini", source="reddit"),
    ]
    assert len(rank.dedupe(candidates, [])) == 1


def test_titles_match_threshold():
    assert rank.titles_match("New model beats GPT on math", "New model beats GPT on math tests")
    assert not rank.titles_match("New model beats GPT on math", "EU passes AI liability law")


def test_shortlist_caps_per_source_and_boosts_x():
    many = [cand(f"hf:{i}", f"Paper number {i}", f"https://hf.co/{i}", source="huggingface", score=i)
            for i in range(10)]
    x_item = cand("x:1", "Owner forwarded this", "https://x.com/a/status/1", source="x", score=0)
    out = rank.shortlist(many + [x_item])
    assert out[0]["id"] == "x:1"
    assert sum(1 for c in out if c["source"] == "huggingface") == rank.MAX_PER_SOURCE
