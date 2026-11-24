"""모듈 사이의 지역 범위, 응답 내용과 점수 보존 경계를 검증한다."""

import json
import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.contracts import (
    Chunk, GenerationResult, PipelineRequest, ResolvedQuery, SearchCandidate, SourceDocument,
)
from src.ingestion.chunking import chunk_documents
from src.pipeline import RAGPipeline


@pytest.fixture
def source_document():
    path = Path(__file__).parents[1] / "fixtures" / "preprocessing_variants.json"
    fixture = json.loads(path.read_text(encoding="utf-8"))
    assert fixture["is_synthetic"] is True
    return SourceDocument.model_validate(fixture["documents"][0])


@pytest.fixture
def source_chunk(source_document):
    return chunk_documents([source_document])[0]


@pytest.mark.parametrize(
    ("scope_type", "districts"),
    [("district", []), ("district", [" "]), ("common", ["송파구"]), ("unknown", ["송파구"])],
)
def test_chunk_rejects_scope_that_would_change_applicable_regions(
    source_chunk, scope_type, districts
):
    payload = source_chunk.model_dump()
    payload.update(scope_type=scope_type, districts=districts)
    with pytest.raises(ValidationError):
        Chunk.model_validate(payload)


@pytest.mark.parametrize(
    ("status", "answer"),
    [("answered", ""), ("needs_clarification", " \n"), ("insufficient_evidence", "\t")],
)
def test_generation_cannot_report_a_status_with_a_blank_answer(source_chunk, status, answer):
    with pytest.raises(ValidationError):
        GenerationResult(status=status, answer=answer, cited_chunk_ids=[source_chunk.chunk_id])


@pytest.mark.parametrize("score", [math.nan, math.inf, -math.inf])
def test_stage_scores_reject_nonfinite_values_before_json_can_change_them(source_chunk, score):
    with pytest.raises(ValidationError):
        SearchCandidate(chunk=source_chunk, rank=1, stage_scores={"dense": score})


def test_valid_source_scope_and_evidence_survive_the_handoff(source_document, source_chunk):
    candidate = SearchCandidate(
        chunk=source_chunk, rank=1, score=0.75, stage_scores={"dense": 0.0, "bm25": 1.25}
    )
    restored = SearchCandidate.model_validate_json(candidate.model_dump_json())
    chunk = restored.chunk
    assert (chunk.source_document_id, chunk.source_document_version) == (
        source_document.document_id, source_document.version,
    )
    for field in ("title", "content_format", "content", "source_url", "scope_type", "districts"):
        assert getattr(chunk, field) == getattr(source_document, field)
    assert restored.stage_scores == {"dense": 0.0, "bm25": 1.25}
    result = GenerationResult(
        status="answered", answer="합성 자료에 근거한 안내", cited_chunk_ids=[chunk.chunk_id]
    )
    assert GenerationResult.model_validate_json(result.model_dump_json()) == result


@pytest.mark.parametrize(
    ("mutation", "failed_stage"),
    [("blank_answer", "generate"), ("nan_score", "retrieve"), ("nested_scope", "retrieve")],
)
def test_callback_models_are_revalidated_after_mutation(source_chunk, mutation, failed_stage):
    candidate = SearchCandidate(chunk=source_chunk, rank=1)
    generated = GenerationResult(
        status="answered", answer="합성 자료 안내", cited_chunk_ids=[source_chunk.chunk_id]
    )
    if mutation == "blank_answer":
        generated.answer = " \t"
    elif mutation == "nan_score":
        candidate.stage_scores["dense"] = math.nan
    else:
        # 생성할 때 유효했던 중첩 청크가 콜백 내부에서 모순된 상태로 바뀐 경우다.
        candidate.chunk.scope_type = "common"
        assert candidate.chunk.districts == ["송파구"]
    generation_calls = []

    def generate(request, evidence):
        generation_calls.append(request.request_id)
        return generated

    pipeline = RAGPipeline(
        resolver=lambda request: ResolvedQuery(
            search_query=request.question, district=request.district
        ),
        retriever=lambda *args, **kwargs: [candidate],
        generator=generate,
    )
    record = pipeline.run(PipelineRequest(question="합성 질문", district="송파구"))

    assert record.response.status == "error"
    assert record.response.error is not None
    assert any(stage.name == failed_stage and stage.status == "error" for stage in record.stages)
    assert bool(generation_calls) == (failed_stage == "generate")
