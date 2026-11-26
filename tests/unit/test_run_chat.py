import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import run_chat


@pytest.fixture
def team_index(tmp_path, monkeypatch):
    """기본 팀 색인 경로를 임시 폴더로 바꾼다."""
    path = tmp_path / "team" / "index-json.json"
    monkeypatch.setattr(run_chat, "TEAM_INDEX", path)
    return path


@pytest.fixture
def calls(monkeypatch):
    seen: list[tuple[list[str], dict]] = []

    def fake_run(cmd, **kwargs):
        seen.append((cmd, kwargs))
        if (
            "scripts.prepare_data" in cmd
        ):  # 지정한 출력 폴더에 색인을 만든 것처럼 흉내 낸다.
            out = Path(cmd[cmd.index("--output-dir") + 1])
            out.mkdir(parents=True)
            (out / "index-json.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(run_chat.subprocess, "run", fake_run)
    return seen


def settings_for(tmp_path, index_path):
    path = tmp_path / "chat.json"
    path.write_text(json.dumps({"index_path": str(index_path)}), encoding="utf-8")
    return str(path)


def started(call) -> bool:
    return call[0][-3:] == ["streamlit", "run", "app.py"]


def test_matching_team_index_only_starts_the_app(
    tmp_path, team_index, calls, monkeypatch
) -> None:
    team_index.parent.mkdir()
    team_index.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(run_chat, "baseline_mismatch", lambda path: None)
    settings = settings_for(tmp_path, team_index)
    run_chat.main(["--settings", settings])
    assert len(calls) == 1 and started(calls[0])
    assert calls[0][1]["env"]["RAG_CHAT_SETTINGS"] == settings


def test_team_index_that_differs_from_baseline_stops(
    tmp_path, team_index, calls, monkeypatch
) -> None:
    team_index.parent.mkdir()
    team_index.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(run_chat, "baseline_mismatch", lambda path: "기준선과 다름")
    with pytest.raises(SystemExit):
        run_chat.main(["--settings", settings_for(tmp_path, team_index)])
    assert calls == []


def test_other_settings_index_is_not_checked_or_built(
    tmp_path, team_index, calls, monkeypatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    other = tmp_path / "other" / "index-json.json"  # 파일 이름은 같지만 다른 색인
    with pytest.raises(SystemExit):
        run_chat.main(["--settings", settings_for(tmp_path, other)])
    assert calls == []  # 임베딩 호출 없음
    other.parent.mkdir()
    other.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        run_chat, "baseline_mismatch", lambda path: pytest.fail("검사하면 안 됨")
    )
    run_chat.main(["--settings", settings_for(tmp_path, other)])
    assert len(calls) == 1 and started(calls[0])


def test_missing_team_index_is_built_in_a_fresh_folder(
    tmp_path, team_index, calls, monkeypatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    run_chat.main(["--settings", settings_for(tmp_path, team_index)])
    assert "scripts.prepare_data" in calls[0][0]
    assert calls[0][0][calls[0][0].index("--output-dir") + 1] != str(team_index.parent)
    assert team_index.exists() and started(calls[1])


def test_leftover_folder_from_a_failed_build_is_moved_aside(
    tmp_path, team_index, calls, monkeypatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    team_index.parent.mkdir()
    (team_index.parent / "report.json").write_text("{}", encoding="utf-8")
    run_chat.main(["--settings", settings_for(tmp_path, team_index)])
    assert team_index.exists()
    leftovers = list(tmp_path.glob("team.incomplete-*/report.json"))
    assert len(leftovers) == 1  # 지우지 않고 보존한다.


def test_missing_team_index_without_key_stops_before_any_call(
    tmp_path, team_index, calls, monkeypatch
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(SystemExit):
        run_chat.main(["--settings", settings_for(tmp_path, team_index)])
    assert calls == []


def test_baseline_mismatch_compares_the_chunk_fingerprint(
    tmp_path, monkeypatch
) -> None:
    index = SimpleNamespace(
        metadata=SimpleNamespace(chunking_version="v-test"),
        entries=[SimpleNamespace(chunk="c1")],
    )
    monkeypatch.setattr(run_chat, "load_index", lambda path: index)
    monkeypatch.setattr(run_chat, "chunks_fingerprint", lambda chunks: "abc")
    baseline = tmp_path / "chunk_stats.csv"
    monkeypatch.setattr(run_chat, "BASELINE", baseline)
    header = "chunking_version,format,chunks_sha256\n"
    baseline.write_text(header + "v-test,json,abc\n", encoding="utf-8")
    assert run_chat.baseline_mismatch(tmp_path / "i.json") is None
    baseline.write_text(header + "v-test,json,zzz\n", encoding="utf-8")
    assert "기준선과 다릅니다" in run_chat.baseline_mismatch(tmp_path / "i.json")
    baseline.write_text(header + "v-old,json,abc\n", encoding="utf-8")  # 다른 버전
    assert run_chat.baseline_mismatch(tmp_path / "i.json") is not None
