import pytest
import requests

from src import config, llm


def _http_error(status: int) -> requests.HTTPError:
    resp = requests.Response()
    resp.status_code = status
    return requests.HTTPError(response=resp)


def test_fallback_model_used_after_main_fails(monkeypatch):
    calls = []

    def fake_call(model, *args):
        calls.append(model)
        if model == "main":
            raise _http_error(503)
        return "ok from fallback"

    monkeypatch.setattr(config, "LLM_MODEL", "main")
    monkeypatch.setattr(config, "LLM_FALLBACK_MODEL", "backup")
    monkeypatch.setattr(llm, "_call", fake_call)
    assert llm.complete("hi") == "ok from fallback"
    assert calls == ["main", "backup"]


def test_no_fallback_reraises(monkeypatch):
    monkeypatch.setattr(config, "LLM_MODEL", "main")
    monkeypatch.setattr(config, "LLM_FALLBACK_MODEL", "")
    monkeypatch.setattr(llm, "_call", lambda *a: (_ for _ in ()).throw(_http_error(503)))
    with pytest.raises(requests.HTTPError):
        llm.complete("hi")


def test_extract_json_tolerates_fences_and_prose():
    assert llm.extract_json('```json\n{"index": 2}\n```') == {"index": 2}
    assert llm.extract_json('Sure! {"index": 3, "reason": "x"} hope that helps') == {"index": 3, "reason": "x"}
