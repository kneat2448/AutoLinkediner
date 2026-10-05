"""Shared pipeline steps used by both entrypoints: collect, build/send drafts, and act on approvals."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from src import config, rank, render, state, telegram, write
from src.sources import hackernews, huggingface, news, reddit, x_queue
from src.sources.common import Candidate

log = logging.getLogger(__name__)

AWAITING = "awaiting_approval"
APPROVED = "approved"  # manual mode: approved, waiting for the owner to post it and reply "done"


# ---------- outbound messaging (no-ops in dry-run) ----------

def say(text: str, reply_to: int | None = None) -> list[int]:
    """Send a Telegram message, or log it in dry-run mode."""
    if state.DRY_RUN:
        log.info("dry-run: would send Telegram message:\n%s", text)
        return []
    return telegram.send_message(text, reply_to=reply_to)


def show(photo: Path | str, caption: str = "") -> str:
    """Send a photo; returns its Telegram file_id ('' in dry-run)."""
    if state.DRY_RUN:
        log.info("dry-run: would send photo %s", photo)
        return ""
    return telegram.largest_file_id(telegram.send_photo(photo, caption))


# ---------- collection ----------

def collect() -> list[Candidate]:
    """All candidates from every source, deduped against history. Each source fails gracefully."""
    candidates: list[Candidate] = []
    for source in (x_queue, news, hackernews, reddit, huggingface):
        candidates.extend(source.fetch())
    return rank.dedupe(candidates, state.load(state.POSTED))


# ---------- drafting ----------

def image_path() -> Path:
    return config.OUT_DIR / f"{config.today_str()}.png"


def compose(pending: dict[str, Any]) -> dict[str, Any]:
    """(Re)write post + headline for pending['candidate'] using its stored context, then render."""
    candidate = pending["candidate"]
    draft = write.write_post(candidate["title"], pending["context"], pending["source_credit"])
    pending["text"] = draft.text
    pending["headline"] = write.write_headline(draft.body)
    pending["problems"] = write.validate_post(draft.body, draft.hashtags)
    pending["image"] = str(render.render(pending["headline"], pending["source_tag"], image_path(),
                                         template=pending["template"]))
    return pending


def build_draft(candidate: Candidate, shortlist: list[Candidate], rejected_ids: list[str]) -> dict[str, Any]:
    """Fetch context for the chosen story and produce a complete pending draft."""
    pending: dict[str, Any] = {
        "status": AWAITING,
        "date": config.today_str(),
        "created_at": config.now().isoformat(),
        "candidate": candidate,
        "shortlist": shortlist,
        "rejected_ids": rejected_ids,
        "context": rank.gather_context(candidate),
        "source_credit": rank.source_credit(candidate),
        "source_tag": rank.source_tag(candidate),
        "template": render.template_for(config.now().date()),
        "photo_file_id": "",
    }
    return compose(pending)


def send_draft(pending: dict[str, Any], intro: str = "Today's draft") -> dict[str, Any]:
    """Send the image, post text, source link and instructions to the owner, then save pending."""
    candidate = pending["candidate"]
    file_id = show(Path(pending["image"]), f"{intro} · {pending['headline']}")
    pending["photo_file_id"] = file_id or pending.get("photo_file_id", "")
    say(pending["text"])
    footer = f"Link: {candidate['url']}"
    discussion = candidate.get("extra", {}).get("discussion_url")
    if discussion and discussion != candidate["url"]:
        footer += f"\nDiscussion: {discussion}"
    if pending.get("problems"):
        footer += "\n\n⚠️ Validator notes: " + "; ".join(pending["problems"])
    say(f"{footer}\n\n{telegram.INSTRUCTIONS}")
    pending["status"] = AWAITING
    state.save(state.PENDING, pending)
    return pending


def draft_from(candidates: list[Candidate], rejected_ids: list[str] | None = None,
               intro: str = "Today's draft") -> dict[str, Any] | None:
    """Shortlist → LLM pick → build → send. Returns the pending draft, or None if nothing to pick."""
    shortlist = rank.shortlist(candidates)
    chosen = rank.pick(shortlist)
    if not chosen:
        return None
    return send_draft(build_draft(chosen, shortlist, rejected_ids or []), intro)


# ---------- history ----------

def record(candidate: Candidate, status: str) -> None:
    """Add a story to posted.json (dedupe history) and drop it from the X queue if it came from there."""
    posted = state.load(state.POSTED)
    posted.append({
        "id": candidate["id"],
        "url": candidate["url"],
        "title": candidate["title"],
        "date": config.today_str(),
        "status": status,
    })
    state.save(state.POSTED, posted)
    if candidate["source"] == "x":
        x_queue.remove({candidate["id"].split(":", 1)[1]})


def mark_history(story_id: str, status: str) -> None:
    """Update the status of the most recent history entry for a story."""
    posted = state.load(state.POSTED)
    for item in reversed(posted):
        if item.get("id") == story_id:
            item["status"] = status
            break
    state.save(state.POSTED, posted)


def expire_stale_pending() -> None:
    """A draft from an earlier day that was never answered is marked expired (not recorded)."""
    pending = state.load(state.PENDING)
    if pending.get("status") == AWAITING and pending.get("date") != config.today_str():
        pending["status"] = "expired"
        state.save(state.PENDING, pending)
        log.info("pending: expired unanswered draft from %s", pending.get("date"))
