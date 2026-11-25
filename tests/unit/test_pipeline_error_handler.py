"""파이프라인이 실패를 error_code와 안전한 안내 문구로 기록하는지 확인한다."""

import json

import pytest

from src.common.errors import ApplicationError, ErrorCategory
from src.contracts import (
    Chunk,
    GenerationResult,
    PipelineOptions,
    PipelineRequest,
    PipelineResponse,
    PlaceLookupResult,
    ResolvedQuery,
    RunRecord,
    SearchCandidate,
    StageRecord,
)
from src.generation.pipeline_adapter import make_answer_generator
from src.pipeline import RAGPipeline
from src.query.errors import RewriteCallError

DEFAULT_ANSWER = "요청을 처리하는 중 오류가 발생했습니다."


class _QuotaError(ApplicationError):
    code = "generation.quota_exceeded"
    category = ErrorCategory.EXTERNAL_SERVICE
    user_message = "잠시 후 다시 시도해 주세요."


def chunk(chunk_id="sample"):
    return Chunk(
        chunk_id=chunk_id,
        source_document_id=f"synthetic-{chunk_id}",
        source_document_version="v1",
        title="합성 안내",
        content_format="html",
        content="<p>합성 안내</p>",
        source_url="https://example.org/guide",
        source_location="합성 별표 1",
        scope_type="district",
        districts=["송파구"],
        chunking_version="synthetic-v1",
    )


def resolve(request):
    return ResolvedQuery(search_query=request.question, district=request.district)


def retrieve(query, *, variant, top_k):
    return [SearchCandidate(chunk=chunk(), rank=1)]


def generate(request, evidence):
    return GenerationResult(
        status="answered", answer="합성 답변", cited_chunk_ids=[evidence[0].chunk_id]
    )


def pipeline(**overrides):
    return RAGPipeline(
        **{"resolver": resolve, "retriever": retrieve, "generator": generate}
        | overrides
    )


def request():
    return PipelineRequest(question="합성 질문", district="송파구")


# --- 규격 필드 ---------------------------------------------------------------


def test_error_code_fields_default_to_none():
    response = PipelineResponse(
        request_id="r", run_id="x", status="answered", answer="a"
    )
    stage = StageRecord(name="resolve", status="ok", duration_ms=0)

    assert response.error_code is None
    assert stage.error_code is None


def test_saved_run_record_without_error_code_still_validates():
    payload = json.loads(pipeline().run(request()).model_dump_json())
    payload["response"].pop("error_code", None)
    for stage in payload["stages"]:
        stage.pop("error_code", None)

    restored = RunRecord.model_validate(payload)

    assert restored.response.error_code is None
    assert all(stage.error_code is None for stage in restored.stages)


# --- 응답과 단계 기록 ---------------------------------------------------------


def stage_of(record, name):
    return next(stage for stage in record.stages if stage.name == name)


def raise_quota(request, evidence):
    raise _QuotaError("429 from provider")


def test_application_error_sets_code_user_message_and_keeps_detail():
    record = pipeline(generator=raise_quota).run(request())

    assert record.response.status == "error"
    assert record.response.error_code == "generation.quota_exceeded"
    assert record.response.answer == "잠시 후 다시 시도해 주세요."
    assert "429 from provider" in record.response.error


def test_foreign_exception_is_recorded_as_unexpected_error():
    def boom(request, evidence):
        raise RuntimeError("boom")

    record = pipeline(generator=boom).run(request())

    assert record.response.error_code == "common.unexpected_error"
    assert record.response.answer == DEFAULT_ANSWER
    assert "boom" in record.response.error


def test_only_the_failing_stage_carries_the_code():
    record = pipeline(generator=raise_quota).run(request())

    codes = {stage.name: stage.error_code for stage in record.stages}
    assert codes.pop("generate") == "generation.quota_exceeded"
    assert set(codes.values()) == {None}


def _cite_unknown(request, evidence):
    return GenerationResult(status="answered", answer="a", cited_chunk_ids=["unknown"])


def _cite_nothing(request, evidence):
    return GenerationResult(status="answered", answer="a", cited_chunk_ids=[])


def _duplicate_candidates(query, *, variant, top_k):
    return [
        SearchCandidate(chunk=chunk(), rank=1),
        SearchCandidate(chunk=chunk(), rank=2),
    ]


def _other_district(request):
    return ResolvedQuery(search_query=request.question, district="서대문구")


def _blank_search_query(request):
    return ResolvedQuery(search_query="   ", district=request.district)


def _blank_clarification(request):
    return ResolvedQuery(
        search_query=request.question,
        status="needs_clarification",
        clarification_question="   ",
    )


@pytest.mark.parametrize(
    ("overrides", "stage", "code"),
    [
        (
            {"generator": _cite_unknown},
            "citations",
            "pipeline.citation_outside_evidence",
        ),
        ({"generator": _cite_nothing}, "citations", "pipeline.missing_citation"),
        (
            {"retriever": _duplicate_candidates},
            "context",
            "pipeline.duplicate_chunk_id",
        ),
        ({"resolver": _other_district}, "resolve", "pipeline.region_mismatch"),
        ({"resolver": _blank_search_query}, "resolve", "pipeline.empty_search_query"),
        (
            {"resolver": _blank_clarification},
            "resolve",
            "pipeline.missing_clarification_question",
        ),
        (
            {"retriever": lambda query, *, variant, top_k: "not a list"},
            "retrieve",
            "pipeline.invalid_retrieval_result",
        ),
        (
            {"generator": lambda request, evidence: {"status": "bogus"}},
            "generate",
            "pipeline.invalid_callback_result",
        ),
    ],
)
def test_pipeline_checks_record_their_own_codes(overrides, stage, code):
    record = pipeline(**overrides).run(request())

    assert record.response.status == "error"
    assert record.response.error_code == code
    assert stage_of(record, stage).error_code == code


def test_missing_rewriter_is_recorded_on_rewrite_stage_without_failing_response():
    options = PipelineOptions(rewrite_enabled=True)

    record = pipeline(options=options).run(request())

    assert stage_of(record, "rewrite").error_code == "pipeline.rewriter_not_configured"
    assert record.response.status == "answered"
    assert record.response.error_code is None


def _rewrite_call_fails(query):
    raise RewriteCallError("호출 실패")


@pytest.mark.parametrize(
    ("rewriter", "code"),
    [
        (lambda query: "   ", "pipeline.invalid_rewrite_output"),
        (_rewrite_call_fails, "query.rewrite_call_failed"),
    ],
)
def test_rewrite_failure_keeps_answer_and_records_code_on_stage(rewriter, code):
    options = PipelineOptions(rewrite_enabled=True)

    record = pipeline(rewriter=rewriter, options=options).run(request())

    assert stage_of(record, "rewrite").error_code == code
    assert record.response.status == "answered"
    assert record.response.error_code is None


def test_place_lookup_failure_is_recorded_on_its_stage_only():
    def broken_lookup(request, resolved):
        raise RuntimeError("장소 조회 실패")

    record = pipeline(place_lookup=broken_lookup).run(request())

    assert stage_of(record, "place_lookup").error_code == "common.unexpected_error"
    assert record.response.status == "answered"
    assert record.response.error_code is None
    assert record.response.places.status == "error"


class _BrokenRecorder:
    def write(self, record):
        raise OSError("디스크 가득 참")


def test_record_write_failure_turns_answer_into_error_with_code():
    record = pipeline(recorder=_BrokenRecorder()).run(request())

    assert record.response.status == "error"
    assert record.response.error_code == "common.unexpected_error"
    assert stage_of(record, "record").error_code == "common.unexpected_error"


def test_record_write_failure_keeps_the_original_error_code():
    record = pipeline(generator=raise_quota, recorder=_BrokenRecorder()).run(request())

    assert record.response.error_code == "generation.quota_exceeded"
    assert stage_of(record, "record").error_code == "common.unexpected_error"


def test_successful_run_has_no_error_codes():
    record = pipeline().run(request())

    assert record.response.status == "answered"
    assert record.response.error_code is None
    assert all(stage.error_code is None for stage in record.stages)


def test_answer_generator_failure_reaches_response_with_generation_code():
    def bad_draft(payload):
        return {"status": "answered", "message": "m", "citation_indices": [9]}

    record = pipeline(generator=make_answer_generator(bad_draft)).run(request())

    assert record.response.error_code == "generation.invalid_citation"
    assert record.response.answer == "답변을 준비하는 중 오류가 발생했습니다."
    assert stage_of(record, "generate").error_code == "generation.invalid_citation"


def test_reported_place_lookup_error_marks_its_stage_without_failing_answer():
    def reported_failure(request, resolved):
        return PlaceLookupResult(status="error", error="getSpot 응답 시간 초과")

    record = pipeline(place_lookup=reported_failure).run(request())

    stage = stage_of(record, "place_lookup")
    assert stage.status == "error"
    assert stage.error_code == "pipeline.place_lookup_failed"
    assert "getSpot 응답 시간 초과" in stage.error
    assert record.response.status == "answered"
    assert record.response.error_code is None
    assert record.response.places.status == "error"
    assert record.response.places.error == "getSpot 응답 시간 초과"


def test_place_lookup_without_error_status_keeps_stage_ok():
    def empty(request, resolved):
        return PlaceLookupResult(status="empty")

    record = pipeline(place_lookup=empty).run(request())

    assert stage_of(record, "place_lookup").status == "ok"
    assert stage_of(record, "place_lookup").error_code is None


@pytest.mark.parametrize("reported", [None, "   "])
def test_reported_place_error_without_detail_uses_fallback_text(reported):
    def reported_failure(request, resolved):
        return PlaceLookupResult(status="error", error=reported)

    record = pipeline(place_lookup=reported_failure).run(request())

    stage = stage_of(record, "place_lookup")
    assert stage.error == "장소 조회 콜백이 실패 상태를 반환했습니다."
    assert stage.error_code == "pipeline.place_lookup_failed"
