"""Post and headline generation, plus the voice-spec validator (banned phrases, length, format)."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from src import config, llm

log = logging.getLogger(__name__)

BANNED_PATTERNS: dict[str, str] = {
    "game-changer": r"\bgame[\s-]?changer",
    "revolutionary": r"\brevolutionar(y|ize|izes|ized|izing)\b",
    "groundbreaking": r"\bground[\s-]?breaking\b",
    "excited to share": r"\bexcited to share\b",
    "let's dive in": r"\blet[’']?s dive in\b",
    "in today's fast-paced world": r"\bin today[’']?s fast[\s-]paced world\b",
    "the future is here": r"\bthe future is here\b",
    "buckle up": r"\bbuckle up\b",
    "mind-blowing": r"\bmind[\s-]?blowing\b",
    "unleash": r"\bunleash(es|ed|ing)?\b",
    "delve": r"\bdelv(e|es|ed|ing)\b",
    "landscape": r"\blandscapes?\b",
    "it's not just X, it's Y": r"\bit[’']?s not (just|only)\b[^.?!\n]*?,\s*(it[’']?s|but)\b",
    "here's the thing": r"\bhere[’']?s the thing\b",
    "the best part?": r"\bthe best part\?",
    "Thoughts?": r"\bthoughts\?",
}
_BANNED_RE = {name: re.compile(p, re.IGNORECASE) for name, p in BANNED_PATTERNS.items()}

# Pictographic emoji (not arrows/punctuation)
_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF\U0001F900-\U0001F9FF]"
)
_BOLD_UNICODE_RE = re.compile("[\U0001D400-\U0001D7FF]")
_HASHTAG_RE = re.compile(r"(?<!\w)#\w+")
_BULLET_RE = re.compile(r"^\s*([-*•▪●]|\d+[.)])\s+", re.MULTILINE)

MIN_WORDS, MAX_WORDS = 180, 340     # prompt asks for ~200–320; small tolerance avoids needless retries
HOOK_MAX_WORDS = 15
HEADLINE_MIN_WORDS, HEADLINE_MAX_WORDS = 4, 9


@dataclass
class Draft:
    """A finished post body (without the Source/hashtag lines) plus those parts separately."""

    body: str
    hashtags: list[str]
    source_credit: str

    @property
    def text(self) -> str:
        """Full post: body, Source line, then hashtags last."""
        out = f"{self.body}\n\nSource: {self.source_credit}"
        if self.hashtags:
            out += "\n\n" + " ".join(self.hashtags)
        return out


def find_banned(text: str) -> list[str]:
    """Names of banned phrases present in text."""
    return [name for name, rx in _BANNED_RE.items() if rx.search(text)]


def validate_post(body: str, hashtags: list[str] | None = None) -> list[str]:
    """Return a list of human-readable problems; empty means the post passes."""
    hashtags = hashtags or []
    problems: list[str] = []
    banned = find_banned(body)
    if banned:
        problems.append(f"uses banned phrases: {', '.join(banned)}")
    words = len(body.split())
    if not MIN_WORDS <= words <= MAX_WORDS:
        problems.append(f"is {words} words; it must be about 200–320 words")
    lines = [ln for ln in body.splitlines() if ln.strip()]
    if lines and len(lines[0].split()) >= HOOK_MAX_WORDS:
        problems.append(f"the hook (first line) must be under {HOOK_MAX_WORDS} words")
    if body.count("—") > 1:
        problems.append("uses more than one em dash")
    if body.count("!") > 1:
        problems.append("uses exclamation marks; get energy from specifics instead")
    if len(_EMOJI_RE.findall(body)) > 1:
        problems.append("uses more than one emoji")
    if _BOLD_UNICODE_RE.search(body):
        problems.append("uses bold/fancy Unicode text")
    if len(_BULLET_RE.findall(body)) > 2:
        problems.append("uses bullet points; write short paragraphs instead")
    if len(hashtags) > 3 or len(_HASHTAG_RE.findall(body)) > 0:
        problems.append("hashtags must be 0–3 and only on the final line")
    if lines and not lines[-1].rstrip().endswith("?"):
        problems.append("must end with a genuine closing question")
    if re.search(r"https?://", body):
        problems.append("must not contain links")
    return problems


def split_post(raw: str) -> tuple[str, list[str]]:
    """Separate LLM output into body and trailing hashtags, dropping any Source line it wrote."""
    text = raw.strip().strip("`").strip()
    lines = text.splitlines()
    hashtags: list[str] = []
    while lines and not lines[-1].strip():
        lines.pop()
    if lines and all(tok.startswith("#") for tok in lines[-1].split()):
        hashtags = lines.pop().split()
    kept = [ln for ln in lines if not re.match(r"^\s*(source|via)\s*:", ln, re.IGNORECASE)]
    body = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()
    body = re.sub(r"\*\*(.+?)\*\*", r"\1", body)  # strip markdown bold
    return body, hashtags


def validate_headline(headline: str) -> list[str]:
    """Problems with an image headline; empty means OK."""
    problems = []
    n = len(headline.split())
    if not HEADLINE_MIN_WORDS <= n <= HEADLINE_MAX_WORDS:
        problems.append(f"is {n} words; it must be 4–9 words")
    if headline and headline[-1] in ".!:;,—-":
        problems.append("must not end with punctuation (only '?' is allowed)")
    banned = find_banned(headline)
    if banned:
        problems.append(f"uses banned phrases: {', '.join(banned)}")
    return problems


def clean_headline(raw: str) -> str:
    """Strip quotes, labels, markdown and trailing periods from a model-produced headline."""
    line = next((ln for ln in raw.strip().splitlines() if ln.strip()), "")
    line = re.sub(r"^\s*(headline\s*:)\s*", "", line, flags=re.IGNORECASE)
    line = line.strip().strip("*#`").strip().strip('"“”\'').strip()
    return line.rstrip(".!;:,").strip()


def _fill(template: str, **values: str) -> str:
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", value)
    return template


def write_post(title: str, context: str, credit: str) -> Draft:
    """Generate a post that passes validation (up to WRITE_MAX_ATTEMPTS tries).

    Returns the last attempt even if it still fails validation, with a warning logged,
    so the owner always gets something to review.
    """
    base = _fill(
        (config.PROMPTS_DIR / "write_post.md").read_text(encoding="utf-8"),
        TITLE=title,
        SOURCE=credit,
        CONTEXT=context,
    )
    feedback = ""
    body, hashtags = "", []
    for attempt in range(1, config.WRITE_MAX_ATTEMPTS + 1):
        prompt = base + (f"\n\nYour previous draft was rejected because it {feedback}. Fix that." if feedback else "")
        body, hashtags = split_post(llm.complete(prompt, temperature=0.7))
        problems = validate_post(body, hashtags)
        if not problems:
            return Draft(body, hashtags, credit)
        feedback = "; it ".join(problems)
        log.warning("write: attempt %d failed validation: %s", attempt, feedback)
    log.warning("write: returning post that still fails validation")
    return Draft(body, hashtags[:3], credit)


def write_headline(post_body: str) -> str:
    """Generate a 4–9 word image headline (up to WRITE_MAX_ATTEMPTS tries)."""
    base = _fill((config.PROMPTS_DIR / "headline.md").read_text(encoding="utf-8"), POST=post_body)
    feedback = ""
    headline = ""
    for attempt in range(1, config.WRITE_MAX_ATTEMPTS + 1):
        prompt = base + (f"\n\nYour previous headline was rejected because it {feedback}." if feedback else "")
        headline = clean_headline(llm.complete(prompt, temperature=0.6))
        problems = validate_headline(headline)
        if not problems:
            return headline
        feedback = "; it ".join(problems)
        log.warning("headline: attempt %d failed: %s", attempt, feedback)
    return headline
