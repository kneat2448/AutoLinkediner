import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def load_fixture():
    def _load(name: str):
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return _load


@pytest.fixture
def tmp_state(tmp_path, monkeypatch):
    """Point state/ at a temp dir so tests never touch the real state files."""
    from src import config, state
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    monkeypatch.setattr(state, "STATE_DIR", tmp_path)
    monkeypatch.setattr(state, "DRY_RUN", False)
    return tmp_path
