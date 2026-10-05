"""Entrypoint for poll.yml: read Telegram replies since the stored offset and act on them.

    python -m src.main_poll            # process updates
    python -m src.main_poll --dry-run  # read updates, log what would happen, change nothing
    python -m src.main_poll --peek     # report whether there is work / it needs Chromium (for CI)
"""
from __future__ import annotations

import argparse
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from src import config, linkedin, pipeline, rank, render, state, telegram, write
from src.pipeline import APPROVED, AWAITING, say, show
from src.sources import x_queue

log = logging.getLogger(__name__)


# ---------- handlers ----------

def handle_approve(pending: dict[str, Any]) -> None:
    """Manual mode: send the final copy. Auto mode: publish to LinkedIn and reply with the link."""
    candidate = pending["candidate"]
    if config.POST_MODE == "auto":
        try:
            png = _image_bytes(pending)
            url = linkedin.publish(pending["text"], png, candidate["url"], alt_text=pending.get("headline", ""))
        except Exception as exc:
            log.exception("linkedin: publish failed")
            say(f"⚠️ LinkedIn post failed ({type(exc).__name__}). Nothing was posted. "
                "Reply ok to retry, or post manually from the copy below.")
            _send_final_copy(pending)
            return
        say(f"Posted ✓\n{url}")
        pending["status"] = "posted"
        state.save(state.PENDING, pending)
        pipeline.record(candidate, "posted")
        return
    # Manual mode: the owner posts it, then replies "done". Reminders repeat until then.
    _send_final_copy(pending)
    pending["status"] = APPROVED
    state.save(state.PENDING, pending)
    pipeline.record(candidate, APPROVED)


def handle_done(pending: dict[str, Any]) -> None:
    """Owner confirms they posted the approved copy on LinkedIn."""
    pending["status"] = "posted"
    state.save(state.PENDING, pending)
    pipeline.mark_history(pending["candidate"]["id"], "posted")
    say("Marked as posted ✓ See you tomorrow.")


def _send_final_copy(pending: dict[str, Any]) -> None:
    photo: Path | str = pending.get("photo_file_id") or Path(pending["image"])
    show(photo, "Final copy, ready to post on LinkedIn")
    say(pending["text"])
    say(f"First comment (source link):\n{pending['candidate']['url']}")
    if config.POST_MODE != "auto":
        say("Reply done once it's live on LinkedIn (I'll remind you until then).")


# ---------- daily posting reminder ----------

def reminder_due(pending: dict[str, Any], meta: dict[str, Any], now: datetime) -> str | None:
    """Return the reminder slot key (e.g. '2026-10-05@12') if a reminder should go out now, else None.

    Fires once per configured hour (REMINDER_HOURS, IST) while today's draft is still
    awaiting approval, or approved but not yet confirmed as posted.
    """
    today = now.strftime("%Y-%m-%d")
    if pending.get("date") != today or pending.get("status") not in (AWAITING, APPROVED):
        return None
    passed = [h for h in config.REMINDER_HOURS if now.hour >= h]
    if not passed:
        return None
    slot = f"{today}@{max(passed)}"
    return None if meta.get("last_post_reminder") == slot else slot


def send_reminder_if_due() -> bool:
    """Send the daily posting reminder when due. Returns True if one was sent."""
    pending = state.load(state.PENDING)
    meta = state.load(state.META)
    slot = reminder_due(pending, meta, config.now())
    if not slot:
        return False
    if pending["status"] == AWAITING:
        say("⏰ Reminder: today's LinkedIn draft is still waiting for you.\n" + telegram.INSTRUCTIONS)
    else:
        say("⏰ Reminder: today's post isn't on LinkedIn yet. Here's the copy again.")
        _send_final_copy(pending)
    meta["last_post_reminder"] = slot
    state.save(state.META, meta)
    return True


def _image_bytes(pending: dict[str, Any]) -> bytes | None:
    local = Path(pending.get("image", ""))
    if local.is_file():
        return local.read_bytes()
    if pending.get("photo_file_id"):
        return telegram.download_file(pending["photo_file_id"])
    return None


def handle_redo(pending: dict[str, Any]) -> None:
    """Regenerate post + headline for the same story, re-render, resend."""
    pipeline.send_draft(pipeline.compose(pending), intro="Redo")


def handle_next(pending: dict[str, Any]) -> None:
    """Reject the current story and draft the next-best candidate from the shortlist."""
    current = pending["candidate"]
    pipeline.record(current, "rejected")
    rejected = pending.get("rejected_ids", []) + [current["id"]]
    posted = state.load(state.POSTED)
    remaining = [c for c in pending.get("shortlist", [])
                 if c["id"] not in rejected and not rank.is_duplicate(c, posted)]
    pending["status"] = "rejected"
    state.save(state.PENDING, pending)
    if not remaining:
        say("No more candidates in today's shortlist. Nothing will be posted today unless you forward a tweet "
            "and wait for tomorrow's draft.")
        return
    chosen = rank.pick(remaining)
    if chosen:
        pipeline.send_draft(pipeline.build_draft(chosen, remaining, rejected), intro="Next story")


def handle_skip(pending: dict[str, Any]) -> None:
    pending["status"] = "skipped"
    state.save(state.PENDING, pending)
    pipeline.record(pending["candidate"], "skipped")
    say("Skipped. No post today.")


def handle_edit(pending: dict[str, Any], cmd: telegram.Command) -> None:
    """Use the owner's text as the post; re-render if a new headline was given; ask for ok."""
    pending["text"] = cmd.text
    if cmd.headline and cmd.headline != pending.get("headline"):
        pending["headline"] = cmd.headline
        pending["image"] = str(render.render(cmd.headline, pending["source_tag"], pipeline.image_path(),
                                             template=pending["template"]))
        pending["photo_file_id"] = show(Path(pending["image"]), f"Preview · {cmd.headline}")
    else:
        show(pending.get("photo_file_id") or Path(pending["image"]), "Preview (image unchanged)")
    say(pending["text"])
    notes = write.find_banned(cmd.text)
    note = f"\n⚠️ Contains banned phrases: {', '.join(notes)}" if notes else ""
    say(f"Edit saved.{note}\nReply ok to approve, or send another edit "
        "(start with 'headline: ...' on the first line to change the image).")
    pending["status"] = AWAITING
    state.save(state.PENDING, pending)


def handle_tweet(text: str, message_id: int) -> None:
    item = x_queue.add(text)
    if item and item.get("raw_text"):
        say("Queued ✓", reply_to=message_id)
        return
    ids = say("Queued, but I couldn't read the tweet's text. Reply to THIS message with the tweet text "
              "so I can use it.", reply_to=message_id)
    if item and ids:
        queue = state.load(state.X_QUEUE)
        for q in queue:
            if q["id"] == item["id"]:
                q["prompt_message_id"] = ids[0]
        state.save(state.X_QUEUE, queue)


def handle_message(message: dict[str, Any]) -> None:
    """Route one owner message."""
    text = message.get("text") or message.get("caption") or ""
    reply_to = (message.get("reply_to_message") or {}).get("message_id")
    if reply_to:
        waiting = next((q for q in state.load(state.X_QUEUE) if q.get("prompt_message_id") == reply_to), None)
        if waiting and text.strip():
            x_queue.set_text(waiting["id"], text)
            say("Got the text. Queued ✓")
            return

    cmd = telegram.parse_command(text)
    log.info("command: %s", cmd.kind)
    if cmd.kind == "tweet":
        handle_tweet(text, message["message_id"])
        return

    pending = state.load(state.PENDING)
    if cmd.kind == "done":
        if pending.get("status") == APPROVED:
            handle_done(pending)
        else:
            say("Nothing is waiting to be marked as posted.\n" + telegram.INSTRUCTIONS)
        return
    awaiting = pending.get("status") == AWAITING
    if cmd.kind == "help" or not awaiting:
        status = f"Current draft: {pending.get('status', 'none')}" if pending else "No draft yet."
        hint = "" if awaiting else "\nThere's no draft awaiting approval right now."
        say(f"{status}{hint}\n{telegram.INSTRUCTIONS}\nForward an x.com link any time to queue it.")
        return
    handlers = {"approve": handle_approve, "redo": handle_redo, "next": handle_next, "skip": handle_skip}
    if cmd.kind == "edit":
        handle_edit(pending, cmd)
    else:
        handlers[cmd.kind](pending)


# ---------- update loop ----------

def fetch_updates() -> tuple[list[dict[str, Any]], int]:
    offset = int(state.load(state.TELEGRAM_OFFSET).get("offset", 0))
    return telegram.get_updates(offset), offset


def process_updates() -> int:
    """Handle all new owner messages. Returns the number handled."""
    updates, offset = fetch_updates()
    handled = 0
    for update in updates:
        offset = max(offset, update["update_id"] + 1)
        message = update.get("message")
        if message and telegram.is_owner(message):
            try:
                handle_message(message)
                handled += 1
            except Exception as exc:
                log.exception("failed to handle message")
                say(f"⚠️ Something went wrong handling that ({type(exc).__name__}). Check the Actions log.")
        elif message:
            log.warning("ignoring message from a non-owner chat")
        state.save(state.TELEGRAM_OFFSET, {"offset": offset})
    log.info("poll: %d updates, %d handled", len(updates), handled)
    send_reminder_if_due()
    return handled


def peek() -> None:
    """Report (for CI) whether there are updates and whether handling them may need Chromium."""
    updates, _ = fetch_updates()
    needs_render = False
    for update in updates:
        message = update.get("message") or {}
        if not telegram.is_owner(message):
            continue
        cmd = telegram.parse_command(message.get("text") or "")
        if cmd.kind in ("redo", "next") or (cmd.kind == "edit" and cmd.headline):
            needs_render = True
    reminder = reminder_due(state.load(state.PENDING), state.load(state.META), config.now())
    has_work = bool(updates) or bool(reminder)
    lines = [f"has_work={'true' if has_work else 'false'}", f"needs_render={'true' if needs_render else 'false'}"]
    log.info("peek: %s", ", ".join(lines))
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Process Telegram replies")
    parser.add_argument("--dry-run", action="store_true", help="send nothing, post nothing, save nothing")
    parser.add_argument("--peek", action="store_true", help="only report whether there is work to do")
    args = parser.parse_args()
    config.setup_logging()
    state.DRY_RUN = args.dry_run
    if args.peek:
        peek()
    else:
        process_updates()


if __name__ == "__main__":
    main()
