"""app.py가 오류 없이 실행되고 예시 응답임을 알리는지 확인한다."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from streamlit.testing.v1 import AppTest

from src.contracts import GenerationResult
from src.evaluation.answer_experiments import answer_evaluation_runtimes
from src.retrieval.regions import resolve_request
from src.rewrite_dictionary.runtime import make_catalog_rewriter
from src.runtime import create_runtime

APP_PATH = Path(__file__).parent.parent.parent.parent / "app.py"


def test_app_shows_fixture_notice_after_click(monkeypatch) -> None:
    monkeypatch.delenv("RAG_CHAT_SETTINGS", raising=False)
    app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
    assert not app.exception
    assert app.radio[0].options == ["예시 응답", "실행(합성 데모)"]

    app.button[0].click().run()
    assert not app.exception
    assert any("예시(합성)" in caption.value for caption in app.caption)


@pytest.mark.parametrize("use_relative_path", [False, True])
def test_app_uses_explicit_team_runtime_settings(
    monkeypatch, tmp_path, use_relative_path
) -> None:
    config = tmp_path / "chat.json"
    config.write_text(
        json.dumps(
            {
                "index_path": str(tmp_path / "team-index.json"),
                "runs_path": str(tmp_path / "runs"),
                "pipeline": {"rewrite_enabled": True},
            }
        ),
        encoding="utf-8",
    )
    elsewhere = tmp_path / "outside-project"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    selected_path = (
        "configs/team-a-rewrite-chat.json" if use_relative_path else str(config)
    )
    expected_index = (
        APP_PATH.parent / "data/processed/ordinance-v2-openai-small/index-json.json"
        if use_relative_path
        else tmp_path / "team-index.json"
    )
    monkeypatch.setenv("RAG_CHAT_SETTINGS", selected_path)
    retrieve = Mock(return_value=[])
    generate = Mock(
        return_value=GenerationResult(
            status="insufficient_evidence", answer="합성 확인"
        )
    )

    def make_runtime(settings):
        assert settings.index_path == expected_index
        assert settings.pipeline.rewrite_enabled
        settings.runs_path = tmp_path / "runs"
        return create_runtime(
            settings,
            resolver=resolve_request,
            retriever=retrieve,
            generator=generate,
            rewriter=make_catalog_rewriter(),
        )

    monkeypatch.setattr(
        answer_evaluation_runtimes, "create_a_catalog_runtime", make_runtime
    )
    app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
    app.radio[0].set_value("실행(팀 색인)").run()
    app.selectbox[0].set_value("송파구")
    question = "잠실동에서 안 씻은 우유펙은요?"
    app.text_input[0].set_value(question)
    app.button[0].click().run()

    assert not app.exception
    query = retrieve.call_args.args[0]
    assert (query.district, query.dong) == ("송파구", "잠실동")
    assert query.search_query == question + " (종이팩)"
    assert generate.call_args.args[0].question == question


@pytest.mark.parametrize(
    ("broken_input", "expected_message"),
    (
        ("missing-settings", "RAG_CHAT_SETTINGS"),
        ("invalid-settings", "RAG_CHAT_SETTINGS"),
        ("missing-index", "index_path"),
        ("invalid-index", "index_path"),
    ),
)
def test_app_distinguishes_team_settings_from_index_errors(
    monkeypatch, tmp_path, broken_input, expected_message
) -> None:
    config = tmp_path / "chat.json"
    index = tmp_path / "index.json"
    if broken_input == "invalid-settings":
        config.write_text("{", encoding="utf-8")
    if broken_input in ("missing-index", "invalid-index"):
        config.write_text(
            json.dumps(
                {
                    "index_path": str(index),
                    "pipeline": {"versions": {"model": "offline-model"}},
                }
            ),
            encoding="utf-8",
        )
    if broken_input == "invalid-index":
        index.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("RAG_CHAT_SETTINGS", str(config))

    app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
    app.radio[0].set_value("실행(팀 색인)").run()
    app.text_input[0].set_value("우유팩은 어떻게 버려요?")
    app.button[0].click().run()

    assert not app.exception
    assert len(app.error) == 1
    assert expected_message in app.error[0].value


def test_app_reports_missing_key_before_creating_embedding_provider(
    monkeypatch, tmp_path
) -> None:
    index_path = tmp_path / "team-index.json"
    config = tmp_path / "chat.json"
    config.write_text(
        json.dumps(
            {
                "index_path": str(index_path),
                "pipeline": {"versions": {"model": "offline-model"}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("RAG_CHAT_SETTINGS", str(config))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    load = Mock(
        return_value=SimpleNamespace(
            metadata=SimpleNamespace(
                embedding_identity='{"provider":"openai","model":"fake-embedding"}'
            )
        )
    )
    embedder = Mock()
    monkeypatch.setattr(answer_evaluation_runtimes, "load_index", load)
    monkeypatch.setattr(
        answer_evaluation_runtimes, "create_openai_embeddings", embedder
    )

    app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
    app.radio[0].set_value("실행(팀 색인)").run()
    app.text_input[0].set_value("우유팩은 어떻게 버려요?")
    app.button[0].click().run()

    load.assert_called_once_with(index_path)
    embedder.assert_not_called()
    assert not app.exception
    assert len(app.error) == 1
    assert "OPENAI_API_KEY" in app.error[0].value
    assert "색인을 불러오지" not in app.error[0].value


@pytest.mark.parametrize(
    ("pipeline", "expected_field"),
    (
        ({"variant": "A"}, "pipeline.versions.model"),
        ({"variant": "B", "versions": {"model": "offline-model"}}, "pipeline.variant"),
        ({"variant": "C", "versions": {"model": "offline-model"}}, "pipeline.variant"),
    ),
)
def test_app_reports_team_configuration_field_before_opening_index(
    monkeypatch, tmp_path, pipeline, expected_field
) -> None:
    config = tmp_path / "chat.json"
    config.write_text(json.dumps({"pipeline": pipeline}), encoding="utf-8")
    monkeypatch.setenv("RAG_CHAT_SETTINGS", str(config))
    load_index = Mock()
    monkeypatch.setattr(answer_evaluation_runtimes, "load_index", load_index)

    app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
    app.radio[0].set_value("실행(팀 색인)").run()
    app.text_input[0].set_value("우유팩은 어떻게 버려요?")
    app.button[0].click().run()

    load_index.assert_not_called()
    assert not app.exception
    assert len(app.error) == 1
    assert expected_field in app.error[0].value
    assert "index_path" not in app.error[0].value


def test_app_reloads_team_runtime_when_same_settings_file_changes(
    monkeypatch, tmp_path
) -> None:
    config = tmp_path / "chat.json"
    settings_payload = {
        "runs_path": str(tmp_path / "runs"),
        "pipeline": {"rewrite_enabled": True},
    }
    config.write_text(json.dumps(settings_payload), encoding="utf-8")
    monkeypatch.setenv("RAG_CHAT_SETTINGS", str(config))
    retrieve = Mock(return_value=[])
    generate = Mock(
        return_value=GenerationResult(
            status="insufficient_evidence", answer="합성 확인"
        )
    )

    def make_runtime(settings):
        return create_runtime(
            settings,
            resolver=resolve_request,
            retriever=retrieve,
            generator=generate,
            rewriter=make_catalog_rewriter(),
        )

    factory = Mock(side_effect=make_runtime)
    monkeypatch.setattr(answer_evaluation_runtimes, "create_a_catalog_runtime", factory)
    app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
    app.radio[0].set_value("실행(팀 색인)").run()
    question = "우유팩은 어떻게 버려요?"
    app.text_input[0].set_value(question)
    app.button[0].click().run()
    assert not app.exception
    assert not app.error
    assert retrieve.call_args.args[0].search_query == f"{question} (종이팩)"

    settings_payload["pipeline"]["rewrite_enabled"] = False
    config.write_text(json.dumps(settings_payload), encoding="utf-8")
    app.button[0].click().run()
    assert not app.exception
    assert not app.error
    assert retrieve.call_args.args[0].search_query == question

    app.button[0].click().run()
    assert not app.exception
    assert not app.error
    assert factory.call_count == 2
    assert retrieve.call_count == 3
