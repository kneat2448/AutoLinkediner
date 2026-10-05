"""Configuration: environment variables, paths and constants."""
from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "state"
PROMPTS_DIR = ROOT / "prompts"
TEMPLATES_DIR = ROOT / "templates"
FONTS_DIR = ROOT / "assets" / "fonts"
OUT_DIR = ROOT / "out"

TZ = ZoneInfo("Asia/Kolkata")

# Collection window and filters
LOOKBACK_HOURS = 36
HN_MIN_POINTS = 80
HN_KEYWORDS = [
    "AI", "LLM", "OpenAI", "Anthropic", "Gemini", "model", "neural",
    "GPT", "Claude", "agent", "robotics",
]
REDDIT_SUBREDDITS = ["MachineLearning", "LocalLLaMA", "artificial", "singularity", "OpenAI"]
REDDIT_MIN_SCORE = 100
SHORTLIST_SIZE = 12
X_QUEUE_BOOST = 0.5          # added to the normalized score of owner-forwarded tweets
X_QUEUE_MAX_AGE_DAYS = 7     # forwarded tweets older than this are dropped
FUZZY_TITLE_THRESHOLD = 0.85
WRITE_MAX_ATTEMPTS = 3
HTTP_TIMEOUT = 20


def env(name: str, default: str = "") -> str:
    """Read an env var, stripped; empty counts as unset (unset GitHub secrets arrive as '').

    Never log the returned value for secrets.
    """
    return os.environ.get(name, "").strip() or default


LLM_PROVIDER = env("LLM_PROVIDER", "gemini").lower()
LLM_MODEL = env("LLM_MODEL")
LLM_FALLBACK_MODEL = env("LLM_FALLBACK_MODEL")  # optional, same provider; used when LLM_MODEL keeps failing
TELEGRAM_BOT_TOKEN = env("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = env("TELEGRAM_CHAT_ID")
AUTHOR_NAME = env("AUTHOR_NAME", "Your Name")
POST_MODE = env("POST_MODE", "manual").lower()
LINKEDIN_ACCESS_TOKEN = env("LINKEDIN_ACCESS_TOKEN")
LINKEDIN_TOKEN_ISSUED = env("LINKEDIN_TOKEN_ISSUED")  # YYYY-MM-DD
LINKEDIN_VERSION = env("LINKEDIN_VERSION", "202609")  # YYYYMM; bump if LinkedIn sunsets it
LINKEDIN_TOKEN_REMIND_DAY = 50
# IST hours at which to remind the owner while today's post isn't done (one reminder per hour listed).
REMINDER_HOURS = sorted(int(h) for h in env("REMINDER_HOURS", "12,18").split(",") if h.strip().isdigit())


def now() -> datetime:
    """Current time in IST."""
    return datetime.now(TZ)


def today_str() -> str:
    """Today's date in IST as YYYY-MM-DD."""
    return now().strftime("%Y-%m-%d")


def setup_logging() -> None:
    """Configure root logging for entrypoints."""
    logging.basicConfig(
        level=env("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
