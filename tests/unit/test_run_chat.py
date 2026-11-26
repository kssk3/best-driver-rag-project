import json

import pytest

from scripts import run_chat


@pytest.fixture
def calls(monkeypatch):
    seen: list[tuple[list[str], dict]] = []
    monkeypatch.setattr(
        run_chat.subprocess, "run", lambda cmd, **kw: seen.append((cmd, kw))
    )
    return seen


def settings_for(tmp_path, index_name="index-json.json"):
    path = tmp_path / "chat.json"
    path.write_text(
        json.dumps({"index_path": str(tmp_path / "idx" / index_name)}),
        encoding="utf-8",
    )
    return str(path)


def test_existing_index_only_starts_the_app(tmp_path, calls, monkeypatch) -> None:
    settings = settings_for(tmp_path)
    (tmp_path / "idx").mkdir()
    (tmp_path / "idx" / "index-json.json").write_text("{}", encoding="utf-8")
    run_chat.main(["--settings", settings])
    assert len(calls) == 1
    assert calls[0][0][-3:] == ["streamlit", "run", "app.py"]
    assert calls[0][1]["env"]["RAG_CHAT_SETTINGS"] == settings


def test_missing_index_is_built_before_starting(tmp_path, calls, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    run_chat.main(["--settings", settings_for(tmp_path)])
    assert "scripts.prepare_data" in calls[0][0]
    assert str(tmp_path / "idx") in calls[0][0]
    assert calls[1][0][-3:] == ["streamlit", "run", "app.py"]


def test_missing_index_without_key_stops_before_any_call(
    tmp_path, calls, monkeypatch
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(SystemExit):
        run_chat.main(["--settings", settings_for(tmp_path)])
    assert calls == []


def test_unknown_index_name_is_not_built(tmp_path, calls, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    with pytest.raises(SystemExit):
        run_chat.main(["--settings", settings_for(tmp_path, "other.json")])
    assert calls == []
