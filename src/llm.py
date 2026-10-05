"""Provider-agnostic LLM wrapper (Gemini free tier, Groq free tier, Anthropic paid).

The model always comes from LLM_MODEL; nothing is hardcoded.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import requests

from src import config, http

log = logging.getLogger(__name__)

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
LLM_TIMEOUT = 90
# Free tiers often return 503 "model overloaded" for a minute or two; wait it out: 5s, 10s, 20s, 40s.
LLM_RETRIES = 5
LLM_BACKOFF = 5.0


class LLMError(RuntimeError):
    """Raised when the LLM is misconfigured or returns nothing usable."""


def complete(prompt: str, *, system: str = "", temperature: float = 0.7, max_tokens: int = 4096) -> str:
    """Send one prompt to the configured provider and return the text response.

    If the main model keeps failing (e.g. 503 "overloaded") and LLM_FALLBACK_MODEL is set,
    the same prompt is retried once on the fallback model (same provider).
    """
    model = config.LLM_MODEL
    if not model:
        raise LLMError("LLM_MODEL is not set")
    try:
        return _call(model, prompt, system, temperature, max_tokens)
    except requests.HTTPError as exc:
        fallback = config.LLM_FALLBACK_MODEL
        if not fallback or fallback == model:
            raise
        log.warning("LLM: main model failed (%s); trying fallback model", _status(exc))
        return _call(fallback, prompt, system, temperature, max_tokens)


def _status(exc: requests.HTTPError) -> str:
    return str(exc.response.status_code) if exc.response is not None else "error"


def _call(model: str, prompt: str, system: str, temperature: float, max_tokens: int) -> str:
    provider = config.LLM_PROVIDER
    log.info("LLM call: provider=%s model=%s", provider, model)
    if provider == "gemini":
        return _gemini(model, prompt, system, temperature, max_tokens)
    if provider == "groq":
        return _groq(model, prompt, system, temperature, max_tokens)
    if provider == "anthropic":
        return _anthropic(model, prompt, system, temperature, max_tokens)
    raise LLMError(f"Unknown LLM_PROVIDER: {provider!r}")


def complete_json(prompt: str, *, system: str = "", temperature: float = 0.3) -> Any:
    """Like ``complete`` but parses a JSON object out of the response."""
    return extract_json(complete(prompt, system=system, temperature=temperature))


def extract_json(text: str) -> Any:
    """Parse JSON from a model response, tolerating ```json fences and surrounding prose."""
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else text
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", candidate, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    raise LLMError("Could not parse JSON from LLM response")


def _require(key_name: str) -> str:
    key = config.env(key_name)
    if not key:
        raise LLMError(f"{key_name} is not set")
    return key


def _gemini(model: str, prompt: str, system: str, temperature: float, max_tokens: int) -> str:
    body: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    resp = http.post(
        GEMINI_URL.format(model=model),
        headers={"x-goog-api-key": _require("GEMINI_API_KEY")},
        json=body,
        timeout=LLM_TIMEOUT,
        retries=LLM_RETRIES,
        backoff=LLM_BACKOFF,
    )
    data = resp.json()
    try:
        parts = data["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError) as exc:
        raise LLMError(f"Gemini returned no content: {str(data)[:300]}") from exc
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    return _nonempty(text)


def _groq(model: str, prompt: str, system: str, temperature: float, max_tokens: int) -> str:
    messages = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": prompt}
    ]
    resp = http.post(
        GROQ_URL,
        headers={"Authorization": f"Bearer {_require('GROQ_API_KEY')}"},
        json={"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens},
        timeout=LLM_TIMEOUT,
        retries=LLM_RETRIES,
        backoff=LLM_BACKOFF,
    )
    return _nonempty(resp.json()["choices"][0]["message"]["content"] or "")


def _anthropic(model: str, prompt: str, system: str, temperature: float, max_tokens: int) -> str:
    body: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        body["system"] = system
    resp = http.post(
        ANTHROPIC_URL,
        headers={"x-api-key": _require("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01"},
        json=body,
        timeout=LLM_TIMEOUT,
        retries=LLM_RETRIES,
        backoff=LLM_BACKOFF,
    )
    blocks = resp.json().get("content", [])
    return _nonempty("".join(b.get("text", "") for b in blocks if b.get("type") == "text"))


def _nonempty(text: str) -> str:
    text = text.strip()
    if not text:
        raise LLMError("LLM returned an empty response")
    return text
