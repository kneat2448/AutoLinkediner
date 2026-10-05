import pytest

from src import config, telegram
from src.telegram import parse_command


@pytest.mark.parametrize("text", ["ok", "OK", "Ok!", "approve", "Approved", "👍", " ok "])
def test_approve(text):
    assert parse_command(text).kind == "approve"


@pytest.mark.parametrize("text,kind", [("redo", "redo"), ("Next", "next"), ("skip", "skip"), ("/skip", "skip")])
def test_simple_commands(text, kind):
    assert parse_command(text).kind == kind


def test_tweet_link_wins():
    cmd = parse_command("ok https://x.com/user/status/123456")
    assert cmd.kind == "tweet"
    assert parse_command("https://twitter.com/user/status/1").kind == "tweet"


def test_non_status_x_link_is_not_tweet():
    assert parse_command("https://x.com/user").kind == "help"


def test_edit_requires_more_than_40_chars():
    assert parse_command("a" * 40).kind == "help"
    cmd = parse_command("This is my edited version of the post, rewritten.")
    assert cmd.kind == "edit" and cmd.headline == ""


def test_edit_with_headline():
    cmd = parse_command("headline: Small models catch up fast\nHere is my full edited post text, which is long enough.")
    assert cmd.kind == "edit"
    assert cmd.headline == "Small models catch up fast"
    assert cmd.text.startswith("Here is my full edited post")


def test_short_unknown_is_help():
    assert parse_command("hello").kind == "help"
    assert parse_command("").kind == "help"


def test_is_owner(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "123")
    assert telegram.is_owner({"chat": {"id": 123}})
    assert not telegram.is_owner({"chat": {"id": 999}})
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "")
    assert not telegram.is_owner({"chat": {"id": 123}})


def test_chunks():
    text = "\n".join(["x" * 100] * 100)
    chunks = telegram._chunks(text, 4096)
    assert all(len(c) <= 4096 for c in chunks)
    assert "".join(chunks).replace("\n", "") == text.replace("\n", "")
