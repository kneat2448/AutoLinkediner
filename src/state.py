"""JSON-file state in state/: posted history, pending draft, X queue, Telegram offset."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from src.config import STATE_DIR

log = logging.getLogger(__name__)

POSTED = "posted.json"
PENDING = "pending.json"
X_QUEUE = "x_queue.json"
TELEGRAM_OFFSET = "telegram_offset.json"
META = "meta.json"

# When True (``--dry-run``), state is read but never written.
DRY_RUN = False

_DEFAULTS: dict[str, Any] = {
    POSTED: [],
    PENDING: {},
    X_QUEUE: [],
    TELEGRAM_OFFSET: {"offset": 0},
    META: {},
}


def _path(name: str) -> Path:
    return STATE_DIR / name


def load(name: str) -> Any:
    """Load a state file, returning its default if missing or corrupt."""
    path = _path(name)
    default = json.loads(json.dumps(_DEFAULTS.get(name, {})))
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log.error("State file %s is corrupt; using default", name)
        return default


def save(name: str, data: Any) -> None:
    """Write a state file (pretty, UTF-8, trailing newline). No-op in dry-run mode."""
    if DRY_RUN:
        log.info("dry-run: not saving %s", name)
        return
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    _path(name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
