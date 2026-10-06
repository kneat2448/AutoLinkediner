"""Post and headline generation, the voice-firewall pass, and the voice-spec validator.

Writing craft follows the $100K Ghostwriter skills in the-100k-ghostwriter/ (post-writer,
hook-writer, voice-firewall): a concise opening that keeps its question open past
"see more", one thought per line, concrete numbers from the source, and no machine tells.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from src import config, llm

log = logging.getLogger(__name__)

BANNED_PATTERNS: dict[str, str] = {
    # Project voice spec
    "game-changer": r"\bgame[\s-]?chang(er|ing)",
    "revolutionary": r"\brevolutionar(y|ize|izes|ized|izing)\b",
    "groundbreaking": r"\bground[\s-]?breaking\b",
    "excited to share": r"\bexcited to share\b",
    "let's dive in": r"\blet[’']?s dive in\b",
    "in today's fast-paced world": r"\bin today[’']?s fast[\s-]paced\b",
    "the future is here": r"\bthe future is here\b",
    "buckle up": r"\bbuckle up\b",
    "mind-blowing": r"\bmind[\s-]?blowing\b",
    "unleash": r"\bunleash(es|ed|ing)?\b",
    "delve": r"\bdelv(e|es|ed|ing)\b",
    "landscape": r"\blandscapes?\b",
    "it's not X, it's Y": r"\b(it|this|that)([’']?s not| is not| isn[’']t) (just |only |about )?[^.?!\n]{1,60}?[,.;]\s*(it|this|that)([’']s| is)\b",
    "not X, but Y": r"\bis not (just |only )?(an? |the )?\w+( \w+)?, but\b",
    "here's the thing": r"\bhere[’']?s the thing\b",
    "the best part?": r"\bthe best part\?",
    "Thoughts?": r"\bthoughts\?",
    "Agree?": r"(^|\n)\s*agree\?",
    # Voice-firewall tells: vendor grammar, filler transitions, generic frames, intensifiers
    "seamless": r"\bseamless(ly)?\b",
    "leverage": r"\bleverag(e|es|ed|ing)\b",
    "unlock": r"\bunlock(s|ed|ing)?\b",
    "elevate": r"\belevat(e|es|ed|ing)\b",
    "powered by": r"\bpowered by\b",
    "at the end of the day": r"\bat the end of the day\b",
    "more on that later": r"\bmore on that later\b",
    "whether you're a X or a Y": r"\bwhether you[’']?re an? \w+",
    "rhetorical transition question": r"(^|\n)\s*(so,? )?(what does (this|that) (actually |really )?mean( for you)?|why does (this|that|it) matter|why should you care|what[’']?s the catch|the result|the twist)\?",
    "insane": r"\binsane(ly)?\b",
    "massive": r"\bmassive(ly)?\b",
}
_BANNED_RE = {name: re.compile(p, re.IGNORECASE) for name, p in BANNED_PATTERNS.items()}

# Openers anyone could write (post-writer / hook-writer guardrails)
_GENERIC_OPENER_RE = re.compile(
    r"^\s*(most people (think|believe)|here[’']?s what|i have a confession|let me tell you|unpopular opinion|imagine\b)",
    re.IGNORECASE,
)

# Pictographic emoji (not arrows/punctuation)
_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF\U0001F900-\U0001F9FF]"
)
_BOLD_UNICODE_RE = re.compile("[\U0001D400-\U0001D7FF]")
_HASHTAG_RE = re.compile(r"(?<!\w)#\w+")
_BULLET_RE = re.compile(r"^\s*([-*•▪●]|\d+[.)])\s+", re.MULTILINE)

MIN_WORDS, MAX_WORDS = 130, 300     # prompt asks for ~150–280; small tolerance avoids needless retries
HOOK_MAX_WORDS = 15
MAX_BULLETS = 5                     # one short list of concrete items, like the screenshot style
HEADLINE_MIN_WORDS, HEADLINE_MAX_WORDS = 4, 9
ALT_MARKER = "=== ALTERNATE OPENINGS ==="


@dataclass
class Draft:
    """A finished post body (without the Source/hashtag lines) plus those parts separately."""

    body: str
    hashtags: list[str]
    source_credit: str
    alt_openings: str = ""
    voice_score: int | None = None
    notes: list[str] = field(default_factory=list)

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


def echo_lines(body: str) -> list[str]:
    """First words that open 3+ consecutive (non-list) lines: the 'parallel repetition' tell."""
    lines = [ln.strip() for ln in body.splitlines() if ln.strip() and not _BULLET_RE.match(ln)]
    firsts = [re.sub(r"[^\w']", "", ln.split()[0].lower()) if ln.split() else "" for ln in lines]
    found = []
    for i in range(len(firsts) - 2):
        if firsts[i] and firsts[i] == firsts[i + 1] == firsts[i + 2] and firsts[i] not in found:
            found.append(firsts[i])
    return found


def validate_post(body: str, hashtags: list[str] | None = None) -> list[str]:
    """Return a list of human-readable problems; empty means the post passes."""
    hashtags = hashtags or []
    problems: list[str] = []
    banned = find_banned(body)
    if banned:
        problems.append(f"uses banned phrases: {', '.join(banned)}")
    words = len(body.split())
    if not MIN_WORDS <= words <= MAX_WORDS:
        problems.append(f"is {words} words; it must be about 150–280 words")
    lines = [ln for ln in body.splitlines() if ln.strip()]
    if lines and len(lines[0].split()) >= HOOK_MAX_WORDS:
        problems.append(f"the hook (first line) must be under {HOOK_MAX_WORDS} words")
    if lines and _GENERIC_OPENER_RE.match(lines[0]):
        problems.append("opens with a generic line anyone could write; open on the specific fact or moment")
    echoes = echo_lines(body)
    if echoes:
        problems.append(f"has 3+ consecutive lines starting with the same word ({', '.join(echoes)}); escalate instead of echoing")
    if body.count("—") > 1:
        problems.append("uses more than one em dash")
    if body.count("!") > 1:
        problems.append("uses exclamation marks; get energy from specifics instead")
    if len(_EMOJI_RE.findall(body)) > 1:
        problems.append("uses more than one emoji")
    if _BOLD_UNICODE_RE.search(body):
        problems.append("uses bold/fancy Unicode text")
    if len(_BULLET_RE.findall(body)) > MAX_BULLETS:
        problems.append(f"has more than {MAX_BULLETS} bullet lines; keep at most one short list")
    if len(hashtags) > 3 or len(_HASHTAG_RE.findall(body)) > 0:
        problems.append("hashtags must be 0–3 and only on the final line")
    if re.search(r"https?://", body):
        problems.append("must not contain links")
    return problems


def split_post(raw: str) -> tuple[str, list[str]]:
    """Separate LLM output into body and trailing hashtags, dropping any Source line it wrote."""
    text, _ = split_alternates(raw)
    text = text.strip().strip("`").strip()
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


def split_alternates(raw: str) -> tuple[str, str]:
    """(post, alternate-openings section) from writer output."""
    if ALT_MARKER in raw:
        post, alts = raw.split(ALT_MARKER, 1)
        return post, alts.strip()
    return raw, ""


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
    """Generate a post that passes validation (up to WRITE_MAX_ATTEMPTS tries), then run the firewall.

    Returns the best attempt even if it still fails validation, so the owner always gets
    something to review (the problems are shown on Telegram).
    """
    base = _fill(
        (config.PROMPTS_DIR / "write_post.md").read_text(encoding="utf-8"),
        TITLE=title,
        SOURCE=credit,
        CONTEXT=context,
    )
    feedback = ""
    body, hashtags, alts = "", [], ""
    for attempt in range(1, config.WRITE_MAX_ATTEMPTS + 1):
        prompt = base + (f"\n\nYour previous draft was rejected because it {feedback}. Fix that." if feedback else "")
        raw = llm.complete(prompt, temperature=0.75)
        _, alts = split_alternates(raw)
        body, hashtags = split_post(raw)
        problems = validate_post(body, hashtags)
        if not problems:
            break
        feedback = "; it ".join(problems)
        log.warning("write: attempt %d failed validation: %s", attempt, feedback)
    draft = Draft(body, hashtags[:3], credit, alt_openings=alts)
    return voice_firewall(draft, context)


_SCORE_RE = re.compile(r"^\s*SCORE\s*:\s*(\d+)", re.IGNORECASE | re.MULTILINE)
_CLEAN_MARKER = "=== CLEAN DRAFT ==="


def voice_firewall(draft: Draft, context: str) -> Draft:
    """One LLM pass that rewrites machine-sounding lines (voice-firewall skill).

    The rewrite is kept only if it still passes validation and is not worse than the original;
    any failure keeps the original draft.
    """
    prompt = _fill(
        (config.PROMPTS_DIR / "voice_firewall.md").read_text(encoding="utf-8"),
        POST=draft.body + ("\n\n" + " ".join(draft.hashtags) if draft.hashtags else ""),
        CONTEXT=context[:8000],
    )
    try:
        raw = llm.complete(prompt, temperature=0.4)
    except Exception:
        log.exception("firewall: LLM call failed; keeping original draft")
        return draft
    score_match = _SCORE_RE.search(raw)
    score = int(score_match.group(1)) if score_match else None
    if _CLEAN_MARKER not in raw:
        log.warning("firewall: no clean draft in response; keeping original")
        draft.voice_score = score
        return draft
    notes = [ln.strip("-• ").strip() for ln in raw.split(_CLEAN_MARKER)[0].splitlines()
             if ln.strip().startswith(("-", "•"))][:6]
    body, hashtags = split_post(raw.split(_CLEAN_MARKER, 1)[1])
    before, after = validate_post(draft.body, draft.hashtags), validate_post(body, hashtags)
    if body and len(after) <= len(before):
        log.info("firewall: applied (score %s, %d fixes)", score, len(notes))
        return Draft(body, hashtags[:3], draft.source_credit, draft.alt_openings, score, notes)
    log.warning("firewall: rewrite failed validation (%s); keeping original", "; ".join(after))
    draft.voice_score = score
    return draft


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
