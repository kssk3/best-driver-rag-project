import json
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from src.common.errors import ErrorCategory, describe_error
from src.config import RuntimeSettings
from src.contracts import PipelineOptions, PipelineRequest
from src.evaluation.answer_experiments import answer_evaluation_runtimes as runtimes
from src.evaluation.answer_experiments import color_top_answer


@pytest.mark.parametrize(
    ("options", "identity", "expected_code"),
    [
        ({"variant": "B"}, None, "evaluation.unsupported_configuration"),
        ({"rewrite_enabled": True}, None, "evaluation.unsupported_configuration"),
        ({}, "demo-hash-v1", "evaluation.invalid_embedding_identity"),
        ({}, "[]", "evaluation.invalid_embedding_identity"),
        ({}, '{"provider":"demo"}', "evaluation.invalid_embedding_identity"),
        ({}, '{"provider":"openai"}', "evaluation.invalid_embedding_identity"),
        (
            {},
            '{"provider":"openai","model":"  "}',
            "evaluation.invalid_embedding_identity",
        ),
        (
            {},
            '{"provider":"openai","model":"sample","dimensions":false}',
            "evaluation.invalid_embedding_identity",
        ),
    ],
)
def test_a_runtime_reports_unsupported_configuration(
    monkeypatch, options, identity, expected_code
):
    settings = RuntimeSettings(
        pipeline=PipelineOptions(**options, versions={"model": "answer-model"})
    )
    index = SimpleNamespace(metadata=SimpleNamespace(embedding_identity=identity))
    monkeypatch.setattr(runtimes, "load_index", lambda _path: index)

    with pytest.raises(ValueError) as raised:
        runtimes.create_a_runtime(settings)

    info = describe_error(raised.value)
    assert (info.code, info.category) == (expected_code, ErrorCategory.CONFIGURATION)


def test_a_runtime_requires_answer_model_before_provider_setup():
    with pytest.raises(runtimes.MissingEvaluationModelError) as raised:
        runtimes.create_a_runtime(RuntimeSettings())

    assert raised.value.code == "evaluation.missing_model"


@pytest.fixture
def observed_model(monkeypatch):
    calls = {}

    def bind(chat, **kwargs):
        calls["model"] = chat.model_name

        def invoke(messages):
            calls["prompt"] = sha256(messages[0][1].encode()).hexdigest()
            return AIMessage(
                content='{"status":"answered","message":"답변","citation_indices":[0]}'
            )

        return SimpleNamespace(invoke=invoke)

    monkeypatch.setenv("OPENAI_API_KEY", "offline-test")
    monkeypatch.setattr(ChatOpenAI, "bind", bind)
    return calls


def _settings(tmp_path):
    return RuntimeSettings(
        runs_path=tmp_path / "runs",
        pipeline=PipelineOptions(
            versions={
                "model": "  offline-model  ",
                "prompt": "stale",
                "index": "stale",
                "embedding": "stale",
                "data": "stale",
                "chunking": "stale",
                "replay_index": "stale",
            }
        ),
    )


def test_color_row_records_versions_of_actual_evidence_and_prompt(
    tmp_path, observed_model
):
    settings = _settings(tmp_path)
    record = runtimes.create_color_runtime(settings).run(
        PipelineRequest(question="수거용기 색상은?", district="서대문구")
    )
    [candidate] = record.candidates
    assert record.response.status == "answered"
    assert record.run_kind == "fixed_evidence"
    assert record.options.versions == {
        **observed_model,
        "data": candidate.chunk.source_document_version,
        "chunking": candidate.chunk.chunking_version,
    }
    assert settings.pipeline.versions["index"] == "stale"


@pytest.mark.parametrize("mixed", [False, True])
def test_color_replay_records_saved_versions_without_index_access(
    tmp_path, monkeypatch, observed_model, mixed
):
    monkeypatch.chdir(tmp_path)
    district = "서대문구"
    question = "수거용기 색상은?"
    case = {"case_id": "p04-colors-trick", "question": question, "district": district}
    Path("eval").mkdir()
    Path("eval/dev.json").write_text(json.dumps([case]))
    Path("configs").mkdir()
    Path("configs/answer-model-settings.json").write_text(
        _settings(tmp_path).model_dump_json()
    )
    matches = [
        {
            "score": 1 / (i + 1),
            "chunk": {
                "chunk_id": f"row-{i}",
                "source_document_id": f"document-{i}",
                "source_document_version": "v2" if mixed and i else "v1",
                "title": "색상표",
                "content_format": "json",
                "content": "수거용기 색상",
                "source_url": "https://example.org/guide",
                "source_location": f"row-{i}",
                "scope_type": "district",
                "districts": [district],
                "chunking_version": "rows-v2" if mixed and i else "rows-v1",
            },
        }
        for i in range(5)
    ]
    result = {"matches": matches}
    if not mixed:
        result["index_id"] = "saved-index"
    search = {"question": question, "district": district, "results": [result]}
    Path("results/local").mkdir(parents=True)
    Path("results/local/color-table-retrieval-top5.json").write_text(json.dumps(search))

    color_top_answer.main()

    [path] = Path("results/local/color-table-answers/runs").glob("*.json")
    record = json.loads(path.read_text())
    assert record["run_kind"] == "fixed_evidence"
    assert record["model_input_chunk_ids"] == [m["chunk"]["chunk_id"] for m in matches]
    versions = record["options"]["versions"]
    if mixed:
        assert "replay_index" not in versions
        assert "data" not in versions and "chunking" not in versions
        assert json.loads(versions["data_versions"]) == ["v1", "v2"]
        assert json.loads(versions["chunking_versions"]) == ["rows-v1", "rows-v2"]
    else:
        assert versions["replay_index"] == "saved-index"
        assert versions["data"] == "v1"
        assert versions["chunking"] == "rows-v1"
    assert versions["prompt"] == observed_model["prompt"]
    assert versions["model"] == observed_model["model"]
    assert "index" not in versions and "embedding" not in versions
