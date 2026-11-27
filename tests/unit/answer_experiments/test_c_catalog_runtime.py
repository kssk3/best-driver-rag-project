"""create_a_catalog_runtime이 C(LLM 재정렬)와 질문 다듬기를 함께 쓸 수 있는지 확인한다.

외부 모델 경계(임베딩·채팅)만 대체하므로 외부 호출은 없다.
"""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import langchain_openai
import pytest
from langchain_core.messages import AIMessage

from src.config import RuntimeSettings
from src.contracts import Chunk, PipelineRequest
from src.evaluation.answer_experiments import answer_evaluation_runtimes as runtimes
from src.infrastructure import chat_models
from src.infrastructure.embeddings import create_openai_embeddings
from src.infrastructure.stores import save_index
from src.ingestion.indexing import build_index
from src.pipeline import PipelineConfigurationError


def make_settings(tmp_path, **pipeline) -> RuntimeSettings:
    return RuntimeSettings.model_validate(
        {
            "index_path": str(tmp_path / "index.json"),
            "runs_path": str(tmp_path / "runs"),
            "pipeline": {
                "rewrite_enabled": True,
                "versions": {"model": "answer-model", "reranker_model": "rank-model"},
                **pipeline,
            },
        }
    )


@pytest.fixture
def offline(tmp_path, monkeypatch):
    trace = SimpleNamespace(queries=[], reranks=[], generations=[])
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test")

    class Embeddings:
        def __init__(self, **kwargs):
            self.openai_api_base = "https://api.openai.com/v1"

        def embed_documents(self, texts):
            return [[1.0, 0.0] for _ in texts]

        def embed_query(self, text):
            trace.queries.append(text)
            return [1.0, 0.0]

    class Chat:
        def __init__(self, *, model, **kwargs):
            self.model = model

        def bind(self, **options):
            return self

        def invoke(self, messages):
            payload = json.loads(messages[-1][1])
            if self.model == "rank-model":
                passages = [p["text"] for p in payload["passages"]]
                trace.reranks.append(passages)
                # 마지막 후보를 1등으로 만들어 재정렬이 실제로 순서를 바꾸게 한다.
                scores = [10 if "EVID_5" in p else 0 for p in passages]
                return AIMessage(content=json.dumps({"scores": scores}))
            texts = [e["text"] for e in payload["evidence"]]
            trace.generations.append(texts)
            answer = {
                "status": "answered",
                "message": texts[0],
                "citation_indices": [0],
            }
            return AIMessage(content=json.dumps(answer, ensure_ascii=False))

    monkeypatch.setattr(langchain_openai, "OpenAIEmbeddings", Embeddings)
    monkeypatch.setattr(chat_models, "ChatOpenAI", Chat)
    chunks = [
        Chunk(
            chunk_id=f"id-{i}",
            source_document_id="문서",
            source_document_version="1",
            title="합성",
            content_format="html",
            content=f"EVID_{i}",
            source_url="https://example.org",
            source_location=str(i),
            scope_type="district",
            districts=["서대문구"],
            chunking_version="1",
        )
        for i in range(6)
    ]
    save_index(
        build_index(chunks, create_openai_embeddings("embed-model")),
        tmp_path / "index.json",
    )
    return trace


def ask(pipeline):
    return pipeline.run(
        PipelineRequest(question="우유팩은 어떻게 버려요?", district="서대문구")
    )


def test_c_with_rewrite_reranks_candidates_and_rewrites_the_query(tmp_path, offline):
    pipeline = runtimes.create_a_catalog_runtime(make_settings(tmp_path, variant="C"))
    record = ask(pipeline)

    assert record.response.status == "answered"
    # 질문 다듬기: 검색어 뒤에 품목 분류가 붙어 임베딩으로 간다.
    assert offline.queries == ["우유팩은 어떻게 버려요? (종이팩)"]
    # 재정렬: 재정렬 모델이 후보를 받았고 그 결과의 1등이 답변 근거가 된다.
    assert len(offline.reranks) == 1
    assert "EVID_5" in offline.generations[0][0]
    assert record.options.variant == "C" and record.options.rewrite_enabled is True


def test_c_records_the_rerank_and_rewrite_versions(tmp_path, offline):
    record = ask(
        runtimes.create_a_catalog_runtime(make_settings(tmp_path, variant="C"))
    )
    versions = record.options.versions

    assert "llm-rerank-v1" in versions["candidate_policy"]
    assert versions["reranker_model"] == "rank-model"
    assert len(versions["reranker_prompt"]) == 64
    assert versions["rewrite"] == "catalog-rules-v2"
    assert versions["model"] == "answer-model"


def test_a_with_rewrite_does_not_call_the_reranker(tmp_path, offline):
    record = ask(
        runtimes.create_a_catalog_runtime(make_settings(tmp_path, variant="A"))
    )

    assert not offline.reranks
    assert "candidate_policy" not in record.options.versions
    assert "reranker_model" not in record.options.versions


def test_c_without_a_reranker_model_fails_before_loading_the_index(monkeypatch):
    load_index = Mock()
    monkeypatch.setattr(runtimes, "load_index", load_index)
    settings = RuntimeSettings.model_validate(
        {"pipeline": {"variant": "C", "versions": {"model": "answer-model"}}}
    )

    with pytest.raises(PipelineConfigurationError) as error:
        runtimes.create_a_catalog_runtime(settings)

    assert error.value.code == "evaluation.missing_reranker_model"
    load_index.assert_not_called()


@pytest.mark.parametrize("variant", ["B", "C"])
def test_the_rewrite_off_a_runtime_still_accepts_only_a(variant):
    settings = RuntimeSettings.model_validate(
        {
            "pipeline": {
                "variant": variant,
                "rewrite_enabled": False,
                "versions": {"model": "answer-model", "reranker_model": "rank-model"},
            }
        }
    )

    with pytest.raises(PipelineConfigurationError) as error:
        runtimes.create_a_runtime(settings)

    assert error.value.code == "evaluation.unsupported_configuration"


def test_the_catalog_runtime_rejects_variant_b():
    settings = RuntimeSettings.model_validate(
        {"pipeline": {"variant": "B", "versions": {"model": "answer-model"}}}
    )

    with pytest.raises(PipelineConfigurationError) as error:
        runtimes.create_a_catalog_runtime(settings)

    assert error.value.code == "evaluation.unsupported_configuration"


def test_c_selection_query_and_policy_version_are_saved(tmp_path, offline):
    settings = make_settings(tmp_path, variant="C")
    pipeline = runtimes.create_a_catalog_runtime(settings)
    question = "우유팩이랑 유리병 중 우유팩만 버려요."
    record = pipeline.run(PipelineRequest(question=question, district="서대문구"))
    assert offline.queries == [question + " (종이팩)"]
    saved = json.loads((settings.runs_path / f"{record.run_id}.json").read_text())
    assert saved["search_query"] == question + " (종이팩)"
    assert saved["options"]["versions"]["rewrite"] == "catalog-rules-v2"
    assert len(saved["options"]["versions"]["rewrite_catalog"]) == 64
