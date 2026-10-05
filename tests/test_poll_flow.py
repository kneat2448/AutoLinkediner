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


def test_approve_manual_sends_final_copy_then_done(sent):
    _pending()
    main_poll.handle_message(msg("ok"))
    assert state.load(state.PENDING)["status"] == pipeline.APPROVED
    history = state.load(state.POSTED)[0]
    assert history["id"] == "hn:1" and history["status"] == "approved"
    texts = [t for kind, t in sent if kind == "msg"]
    assert "Post text?\n\nSource: example.com" in texts
    assert any("https://example.com/s" in t for t in texts)
    assert any("Reply done" in t for t in texts)

    main_poll.handle_message(msg("done"))
    assert state.load(state.PENDING)["status"] == "posted"
    assert state.load(state.POSTED)[0]["status"] == "posted"


def test_done_without_approved_draft(sent):
    _pending()
    main_poll.handle_message(msg("done"))
    assert state.load(state.PENDING)["status"] == pipeline.AWAITING
    assert "Nothing is waiting" in sent[-1][1]


def _at(hour):
    from datetime import datetime
    return datetime(2026, 10, 5, hour, 10, tzinfo=config.TZ)


def test_reminder_due_slots(monkeypatch):
    monkeypatch.setattr(config, "REMINDER_HOURS", [12, 18])
    p = {"date": "2026-10-05", "status": pipeline.AWAITING}
    assert main_poll.reminder_due(p, {}, _at(9)) is None
    assert main_poll.reminder_due(p, {}, _at(12)) == "2026-10-05@12"
    assert main_poll.reminder_due(p, {"last_post_reminder": "2026-10-05@12"}, _at(13)) is None
    assert main_poll.reminder_due(p, {"last_post_reminder": "2026-10-05@12"}, _at(18)) == "2026-10-05@18"
    assert main_poll.reminder_due({**p, "status": pipeline.APPROVED}, {}, _at(19)) == "2026-10-05@18"
    assert main_poll.reminder_due({**p, "status": "posted"}, {}, _at(19)) is None
    assert main_poll.reminder_due({**p, "date": "2026-10-04"}, {}, _at(19)) is None


def test_send_reminder_resends_copy_once(sent, monkeypatch):
    monkeypatch.setattr(config, "REMINDER_HOURS", [12])
    monkeypatch.setattr(config, "now", lambda: _at(13))
    p = _pending()
    p.update(date="2026-10-05", status=pipeline.APPROVED)
    state.save(state.PENDING, p)
    assert main_poll.send_reminder_if_due() is True
    assert any("isn't on LinkedIn yet" in t for k, t in sent if k == "msg")
    assert any(k == "photo" for k, _ in sent)
    assert main_poll.send_reminder_if_due() is False


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
