import pytest

from src import config, main_poll, pipeline, state
from src.sources import x_queue


@pytest.fixture
def sent(tmp_state, monkeypatch):
    """Capture outbound Telegram traffic."""
    log = []
    fake_say = lambda text, reply_to=None: log.append(("msg", text)) or [len(log)]
    fake_show = lambda photo, caption="": log.append(("photo", caption)) or "file-id"
    for mod in (pipeline, main_poll):
        monkeypatch.setattr(mod, "say", fake_say)
        monkeypatch.setattr(mod, "show", fake_show)
    monkeypatch.setattr(config, "POST_MODE", "manual")
    return log


def _pending():
    cand = {"id": "hn:1", "source": "hackernews", "title": "Story", "url": "https://example.com/s",
            "summary": "", "score": 100, "created_at": "2026-10-05T00:00:00+00:00", "raw_text": ""}
    p = {"status": pipeline.AWAITING, "date": config.today_str(), "candidate": cand, "shortlist": [cand],
         "rejected_ids": [], "text": "Post text?\n\nSource: example.com", "headline": "Story headline is here",
         "image": "out/none.png", "photo_file_id": "abc", "source_tag": "via example.com",
         "template": "clean_white"}
    state.save(state.PENDING, p)
    return p


def msg(text, mid=10):
    return {"message_id": mid, "chat": {"id": 1}, "text": text}


def test_approve_manual_sends_final_copy_and_records(sent):
    _pending()
    main_poll.handle_message(msg("ok"))
    assert state.load(state.PENDING)["status"] == "posted"
    assert state.load(state.POSTED)[0]["id"] == "hn:1"
    texts = [t for kind, t in sent if kind == "msg"]
    assert "Post text?\n\nSource: example.com" in texts
    assert any("https://example.com/s" in t for t in texts)


def test_skip(sent):
    _pending()
    main_poll.handle_message(msg("skip"))
    assert state.load(state.PENDING)["status"] == "skipped"
    assert state.load(state.POSTED)[0]["status"] == "skipped"


def test_next_with_empty_shortlist(sent):
    _pending()
    main_poll.handle_message(msg("next"))
    assert state.load(state.POSTED)[0]["status"] == "rejected"
    assert "No more candidates" in sent[-1][1]


def test_edit_without_headline_keeps_image(sent):
    _pending()
    new_text = "My own rewritten version of the post, much better now?"
    main_poll.handle_message(msg(new_text))
    p = state.load(state.PENDING)
    assert p["text"] == new_text and p["status"] == pipeline.AWAITING
    assert ("photo", "Preview (image unchanged)") in sent


def test_command_without_pending_gets_help(sent):
    main_poll.handle_message(msg("ok"))
    assert "no draft awaiting" in sent[-1][1].lower()


def test_tweet_then_reply_with_text(sent, monkeypatch):
    monkeypatch.setattr(x_queue, "fetch_tweet_text", lambda url: "")
    main_poll.handle_message(msg("https://x.com/a/status/77", mid=5))
    item = state.load(state.X_QUEUE)[0]
    assert item["raw_text"] == "" and item["prompt_message_id"]
    reply = {"message_id": 6, "chat": {"id": 1}, "text": "The actual tweet text",
             "reply_to_message": {"message_id": item["prompt_message_id"]}}
    main_poll.handle_message(reply)
    assert state.load(state.X_QUEUE)[0]["raw_text"] == "The actual tweet text"


def test_tweet_with_owner_text_queues(sent):
    main_poll.handle_message(msg("Worth covering https://x.com/a/status/88"))
    assert sent[-1] == ("msg", "Queued ✓")
