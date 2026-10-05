"""Entrypoint for draft.yml: collect → pick → write → render → send to Telegram.

    python -m src.main_draft             # full daily run
    python -m src.main_draft --dry-run   # print the draft locally; send/post/save nothing
    python -m src.main_draft --force     # draft even if today's draft already exists
"""
from __future__ import annotations

import argparse
import logging
import sys

from src import config, linkedin, main_poll, pipeline, state
from src.pipeline import AWAITING, say

log = logging.getLogger(__name__)


def token_reminder() -> None:
    """From day 50 after LINKEDIN_TOKEN_ISSUED, remind the owner (once a day) to refresh the token."""
    if config.POST_MODE != "auto":
        return
    age = linkedin.token_age_days()
    if age is None or age < config.LINKEDIN_TOKEN_REMIND_DAY:
        return
    meta = state.load(state.META)
    if meta.get("last_token_reminder") == config.today_str():
        return
    say(f"🔑 Your LinkedIn token is {age} days old (they last ~60). "
        "Run scripts/linkedin_auth.py and update LINKEDIN_ACCESS_TOKEN and LINKEDIN_TOKEN_ISSUED.")
    meta["last_token_reminder"] = config.today_str()
    state.save(state.META, meta)


def run(dry_run: bool, force: bool) -> int:
    # 1. Queue anything the owner forwarded overnight (and handle any pending replies).
    if not dry_run:
        try:
            main_poll.process_updates()
        except Exception:
            log.exception("draft: initial poll failed; continuing")
        token_reminder()

    pending = state.load(state.PENDING)
    if not force and pending.get("date") == config.today_str() and pending.get("status") in (AWAITING, "posted", "skipped"):
        log.info("draft: today's draft already exists (status=%s); use --force to redo", pending["status"])
        return 0
    pipeline.expire_stale_pending()

    # 2–4. Collect, dedupe, rank, pick.  5–8. Context, write, render, send.
    candidates = pipeline.collect()
    if not candidates:
        log.warning("draft: no candidates today")
        say("No good AI stories found today. Forward an x.com link if you have one in mind.")
        return 0
    pending = pipeline.draft_from(candidates)
    if not pending:
        return 0
    if dry_run:
        print("\n" + "=" * 60)
        print(f"STORY:    {pending['candidate']['title']}\nURL:      {pending['candidate']['url']}")
        print(f"HEADLINE: {pending['headline']}\nIMAGE:    {pending['image']} ({pending['template']})")
        if pending.get("problems"):
            print(f"VALIDATOR: {'; '.join(pending['problems'])}")
        print("-" * 60 + f"\n{pending['text']}\n" + "=" * 60)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Create today's LinkedIn draft")
    parser.add_argument("--dry-run", action="store_true", help="print the draft; send/post/save nothing")
    parser.add_argument("--force", action="store_true", help="draft even if one exists for today")
    args = parser.parse_args()
    config.setup_logging()
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    state.DRY_RUN = args.dry_run
    sys.exit(run(args.dry_run, args.force))


if __name__ == "__main__":
    main()
