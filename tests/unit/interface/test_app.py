"""app.py가 오류 없이 실행되고 응답 방식을 알맞게 보여 주는지 확인한다."""

import json
from hashlib import sha256
from os import utime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from streamlit.testing.v1 import AppTest

from src.contracts import Chunk, GenerationResult
from src.evaluation.answer_experiments import answer_evaluation_runtimes
from src.infrastructure.stores import save_index
from src.ingestion.indexing import build_index
from src.retrieval.regions import resolve_request
from src.rewrite_dictionary import catalog
from src.rewrite_dictionary.runtime import make_catalog_rewriter
from src.runtime import create_runtime

APP_PATH = Path(__file__).parent.parent.parent.parent / "app.py"


def test_app_without_settings_offers_only_synthetic_demo(monkeypatch) -> None:
    monkeypatch.delenv("RAG_CHAT_SETTINGS", raising=False)
    app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
    assert not app.exception
    assert app.radio[0].options == ["합성 데모"]


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
    app.radio[0].set_value("실행").run()
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
    app.radio[0].set_value("실행").run()
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
    app.radio[0].set_value("실행").run()
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
        (
            {"variant": "C", "versions": {"model": "offline-model"}},
            "pipeline.versions.reranker_model",
        ),
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
    app.radio[0].set_value("실행").run()
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
    app.radio[0].set_value("실행").run()
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


def test_app_refreshes_same_path_index_and_active_catalog(
    monkeypatch, tmp_path
) -> None:
    index_path = tmp_path / "index.json"
    catalog_path = tmp_path / "catalog.json"
    runs_path = tmp_path / "runs"
    config = tmp_path / "chat.json"
    config.write_text(
        json.dumps(
            {
                "index_path": str(index_path),
                "runs_path": str(runs_path),
                "pipeline": {
                    "rewrite_enabled": True,
                    "versions": {"model": "offline-model"},
                },
            }
        ),
        encoding="utf-8",
    )
    catalog_json = json.loads(catalog.CATALOG_PATH.read_bytes())
    catalog_path.write_text(
        json.dumps(catalog_json, ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setattr(catalog, "CATALOG_PATH", catalog_path)
    monkeypatch.setenv("RAG_CHAT_SETTINGS", str(config))
    monkeypatch.setenv("OPENAI_API_KEY", "offline-unit-test-key")
    embedder = SimpleNamespace(
        identity='{"provider":"openai","model":"offline-embedding","dimensions":1}',
        embed_documents=lambda texts: [[1.0] for _ in texts],
        embed_query=lambda _: [1.0],
    )
    monkeypatch.setattr(
        answer_evaluation_runtimes, "create_openai_embeddings", lambda *_: embedder
    )
    monkeypatch.setattr(
        answer_evaluation_runtimes,
        "make_model_draft",
        lambda _: (
            lambda request: {
                "status": "answered",
                "message": request["evidence"][0]["text"],
                "citation_indices": [0],
            }
        ),
    )

    def synthetic_index(content):
        chunk = Chunk(
            chunk_id="offline-chunk",
            source_document_id="offline-guide",
            source_document_version="v1",
            title="합성 안내",
            content_format="json",
            content=content,
            source_url="https://example.org/guide",
            source_location="합성 자료",
            scope_type="district",
            districts=["서대문구"],
            chunking_version="synthetic-v1",
        )
        return build_index([chunk], embedder)

    first = synthetic_index("이전 합성 근거")
    second = synthetic_index("최신 합성 근거")
    save_index(first, index_path)
    app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
    app.radio[0].set_value("실행").run()
    question = "우유팩은 어떻게 버려요?"
    app.text_input[0].set_value(question)

    def submit(expected_evidence):
        old_runs = set(runs_path.glob("*.json"))
        app.button[0].click().run()
        assert not app.exception
        assert not app.error
        assert any(message.value == expected_evidence for message in app.success)
        [record_path] = set(runs_path.glob("*.json")) - old_runs
        return json.loads(record_path.read_bytes())

    original_record = submit("이전 합성 근거")
    assert original_record["options"]["versions"]["index"] == first.metadata.index_id
    assert original_record["search_query"] == f"{question} (종이팩)"

    first_stat = index_path.stat()
    replacement_path = tmp_path / "replacement.json"
    save_index(second, replacement_path)
    utime(replacement_path, ns=(first_stat.st_atime_ns, first_stat.st_mtime_ns))
    replacement_path.replace(index_path)
    second_stat = index_path.stat()
    assert second_stat.st_size == first_stat.st_size
    assert second_stat.st_mtime_ns == first_stat.st_mtime_ns
    assert second_stat.st_ino != first_stat.st_ino

    new_record = submit("최신 합성 근거")
    assert new_record["options"]["versions"]["index"] == second.metadata.index_id
    assert new_record["search_query"] == f"{question} (종이팩)"

    catalog_stat = catalog_path.stat()
    catalog_json["item_aliases"]["우유팩"] = "새별칭"
    catalog_path.write_text(
        json.dumps(catalog_json, ensure_ascii=False), encoding="utf-8"
    )
    utime(catalog_path, ns=(catalog_stat.st_atime_ns, catalog_stat.st_mtime_ns))
    assert catalog_path.stat().st_ino == catalog_stat.st_ino
    assert catalog_path.stat().st_size == catalog_stat.st_size
    assert catalog_path.stat().st_mtime_ns == catalog_stat.st_mtime_ns

    catalog_record = submit("최신 합성 근거")
    versions = catalog_record["options"]["versions"]
    assert versions["index"] == second.metadata.index_id
    assert versions["rewrite_catalog"] == sha256(catalog_path.read_bytes()).hexdigest()
    assert (
        versions["rewrite_catalog"]
        != new_record["options"]["versions"]["rewrite_catalog"]
    )
    assert catalog_record["search_query"] == f"{question} (새별칭)"
