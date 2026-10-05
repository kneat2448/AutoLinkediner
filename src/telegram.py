"""Telegram Bot API client (polling via getUpdates only, no webhooks) and command parsing."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src import config, http

log = logging.getLogger(__name__)

API = "https://api.telegram.org/bot{token}/{method}"
FILE_API = "https://api.telegram.org/file/bot{token}/{path}"
MAX_MESSAGE = 4096
MAX_CAPTION = 1024
EDIT_MIN_CHARS = 40

APPROVE_WORDS = {"ok", "okay", "approve", "approved", "👍", "👍🏻", "👍🏼", "👍🏽", "👍🏾", "👍🏿"}
SIMPLE_COMMANDS = {"redo": "redo", "next": "next", "skip": "skip"}
INSTRUCTIONS = "Reply: ok / redo / next / skip / or send edited text"


# ---------- command parsing (pure, unit-tested) ----------

@dataclass
class Command:
    """A parsed owner message."""

    kind: str           # approve | redo | next | skip | edit | tweet | help
    text: str = ""      # full message text (for edit / tweet)
    headline: str = ""  # optional new headline supplied with an edit


_TWEET_RE = re.compile(r"https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/\S+/status(?:es)?/\d+", re.I)
_HEADLINE_RE = re.compile(r"^\s*headline\s*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)


def parse_command(text: str) -> Command:
    """Classify an owner message into a Command.

    Precedence: tweet link > exact command word > edit (> 40 chars) > help.
    An edit may start with a ``headline: ...`` line to change the image headline.
    """
    raw = (text or "").strip()
    if _TWEET_RE.search(raw):
        return Command("tweet", raw)
    word = raw.lower().strip(" .!/")
    if word in APPROVE_WORDS or raw in APPROVE_WORDS:
        return Command("approve")
    if word in SIMPLE_COMMANDS:
        return Command(SIMPLE_COMMANDS[word])
    if len(raw) > EDIT_MIN_CHARS:
        headline = ""
        match = _HEADLINE_RE.search(raw)
        if match and raw[: match.start()].strip() == "":
            headline = match.group(1).strip()
            raw = raw[match.end():].strip()
        return Command("edit", raw, headline)
    return Command("help", raw)


# ---------- API ----------

class TelegramError(RuntimeError):
    pass


def _call(method: str, *, files: dict[str, Any] | None = None, **params: Any) -> Any:
    if not config.TELEGRAM_BOT_TOKEN:
        raise TelegramError("TELEGRAM_BOT_TOKEN is not set")
    url = API.format(token=config.TELEGRAM_BOT_TOKEN, method=method)
    if files:
        resp = http.post(url, data=params, files=files, timeout=60)
    else:
        resp = http.post(url, json=params, timeout=40)
    data = resp.json()
    if not data.get("ok"):
        raise TelegramError(f"{method} failed: {data.get('description')}")
    return data["result"]


def get_updates(offset: int) -> list[dict[str, Any]]:
    """Fetch updates after ``offset`` (non-blocking). Calling with a higher offset confirms older ones."""
    return _call("getUpdates", offset=offset, timeout=0, allowed_updates=["message"])


def send_message(text: str, reply_to: int | None = None) -> list[int]:
    """Send plain text (split into chunks under the 4096-char limit). Returns message ids."""
    ids = []
    for chunk in _chunks(text, MAX_MESSAGE):
        params: dict[str, Any] = {
            "chat_id": config.TELEGRAM_CHAT_ID,
            "text": chunk,
            "disable_web_page_preview": True,
        }
        if reply_to:
            params["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
        ids.append(_call("sendMessage", **params)["message_id"])
    return ids


def send_photo(photo: Path | str, caption: str = "") -> dict[str, Any]:
    """Send a photo by local path or by an existing Telegram file_id. Returns the Message."""
    params = {"chat_id": config.TELEGRAM_CHAT_ID, "caption": caption[:MAX_CAPTION]}
    if isinstance(photo, Path):
        with photo.open("rb") as fh:
            return _call("sendPhoto", files={"photo": (photo.name, fh, "image/png")}, **params)
    return _call("sendPhoto", photo=photo, **params)


def largest_file_id(message: dict[str, Any]) -> str:
    """file_id of the largest size of a sent photo."""
    sizes = message.get("photo") or []
    return max(sizes, key=lambda s: s.get("file_size", 0))["file_id"] if sizes else ""


def download_file(file_id: str) -> bytes:
    """Download a file the bot has access to (≤ 20 MB)."""
    path = _call("getFile", file_id=file_id)["file_path"]
    return http.get(FILE_API.format(token=config.TELEGRAM_BOT_TOKEN, path=path), timeout=60).content


def is_owner(message: dict[str, Any]) -> bool:
    """Only messages from the configured chat are accepted."""
    return bool(config.TELEGRAM_CHAT_ID) and str(message.get("chat", {}).get("id")) == config.TELEGRAM_CHAT_ID


def _chunks(text: str, size: int) -> list[str]:
    if len(text) <= size:
        return [text]
    out, current = [], ""
    for para in text.split("\n"):
        if len(current) + len(para) + 1 > size and current:
            out.append(current)
            current = ""
        current = f"{current}\n{para}" if current else para
        while len(current) > size:
            out.append(current[:size])
            current = current[size:]
    if current:
        out.append(current)
    return out
