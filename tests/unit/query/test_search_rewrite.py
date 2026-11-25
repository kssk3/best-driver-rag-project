"""파이프라인에서 검색 질의 정제 연결과 실패 복귀 검사.

검색과 생성은 합성 콜백으로 검사한다.
"""

import pytest

from src.config import RuntimeSettings
from src.contracts import (
    Chunk,
    GenerationResult,
    PipelineOptions,
    PipelineRequest,
    ResolvedQuery,
    SearchCandidate,
)
from src.pipeline import RAGPipeline
from src.query import rewrite
from src.retrieval.regions import resolve_request
from src.runtime import create_runtime


@pytest.fixture
def synthetic_callbacks():
    observed = {"retrieval": [], "generation": []}
    chunk = Chunk(
        chunk_id="synthetic-carton",
        source_document_id="synthetic-guide",
        source_document_version="fixture-v1",
        title="합성 종이팩 안내",
        content_format="json",
        content='{"품목": "종이팩", "조건": "합성 일반주택"}',
        source_url="https://example.org/synthetic-guide",
        source_location="합성 표 종이팩 행",
        scope_type="district",
        districts=["송파구"],
        conditions=["합성 일반주택"],
        chunking_version="fixture-v1",
    )

    def resolver(request):
        return ResolvedQuery(
            search_query=f"송파구 마천2동 일반주택 {request.question}",
            district="송파구",
            dong="마천2동",
        )

    def retriever(query, *, variant, top_k):
        observed["retrieval"].append(
            (query.search_query, query.district, query.dong, variant, top_k)
        )
        if "종이팩" not in query.search_query:
            return []
        return [SearchCandidate(chunk=chunk, rank=1, score=1.0)]

    def generator(request, chunks):
        observed["generation"].append(request.model_dump())
        return GenerationResult(
            status="answered" if chunks else "insufficient_evidence",
            answer="합성 근거 응답" if chunks else "합성 검색 결과 없음",
            cited_chunk_ids=[item.chunk_id for item in chunks],
        )

    return {
        "resolver": resolver,
        "retriever": retriever,
        "generator": generator,
    }, observed


def test_resolved_region_and_rewrite_reach_search(synthetic_callbacks, tmp_path):
    callbacks, observed = synthetic_callbacks
    request = PipelineRequest(
        question="잠실동에서 우유팩은 어떻게 버려?", conditions={"주택": "일반주택"}
    )
    original = request.model_dump()
    records = [
        create_runtime(
            RuntimeSettings(
                runs_path=tmp_path,
                pipeline=PipelineOptions(variant="C", rewrite_enabled=enabled),
            ),
            resolver=resolve_request,
            retriever=callbacks["retriever"],
            generator=callbacks["generator"],
            rewriter=rewrite.rewrite_search_query,
        ).run(request)
        for enabled in (False, True)
    ]

    assert observed["retrieval"] == [
        ("잠실동에서 우유팩은 어떻게 버려?", "송파구", "잠실동", "C", 5),
        (
            "잠실동에서 우유팩은 어떻게 버려? (종이팩)",
            "송파구",
            "잠실동",
            "C",
            5,
        ),
    ]
    off, on = records
    assert off.search_query == request.question
    assert on.search_query == "잠실동에서 우유팩은 어떻게 버려? (종이팩)"
    assert off.response.status == "insufficient_evidence"
    assert off.model_input_chunk_ids == []
    assert on.response.status == "answered"
    assert on.model_input_chunk_ids == ["synthetic-carton"]
    assert on.response.citations[0].chunk_id == "synthetic-carton"
    generation_request = original | {"district": "송파구", "dong": "잠실동"}
    assert observed["generation"] == [generation_request, generation_request]
    assert request.model_dump() == original
    assert all(record.request.model_dump() == original for record in records)


def test_pipeline_rewrite_failure_keeps_resolved_query_and_trace(
    synthetic_callbacks, monkeypatch
):
    callbacks, observed = synthetic_callbacks

    def fail(_question):
        raise RuntimeError("synthetic rewrite failure")

    monkeypatch.setattr(rewrite, "normalize_question", fail)
    request = PipelineRequest(question="우유팩 어디에 버려?")
    original = request.model_dump()
    record = RAGPipeline(
        **callbacks,
        rewriter=rewrite.rewrite_search_query,
        options=PipelineOptions(variant="C", rewrite_enabled=True),
    ).run(request)

    assert observed["retrieval"] == [
        ("송파구 마천2동 일반주택 우유팩 어디에 버려?", "송파구", "마천2동", "C", 5),
    ]
    assert record.search_query == record.resolved_query.search_query
    stage = next(stage for stage in record.stages if stage.name == "rewrite")
    assert stage.status == "error"
    assert "RuntimeError" in stage.error
    assert any("리라이트 실패" in warning for warning in record.warnings)
    assert record.response.status == "insufficient_evidence"
    assert observed["generation"] == [
        original | {"district": "송파구", "dong": "마천2동"}
    ]
    assert request.model_dump() == original
    assert record.request.model_dump() == original
