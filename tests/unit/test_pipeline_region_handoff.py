"""해석된 구·동이 생성기까지 전달되는지 검증한다 (외부 연결 없는 합성 콜백)."""

from src.contracts import Chunk, GenerationResult, PipelineRequest, SearchCandidate
from src.pipeline import RAGPipeline
from src.retrieval.regions import resolve_request


def _seodaemun_chunk() -> Chunk:
    return Chunk(
        chunk_id="seodaemun-local", source_document_id="synthetic-seodaemun",
        source_document_version="v1", title="합성 안내", content_format="html",
        content="<p>합성 안내</p>", source_url="https://example.org/guide",
        source_location="합성 별표 1", scope_type="district", districts=["서대문구"],
        chunking_version="synthetic-v1",
    )


def _retrieve(query, *, variant, top_k):
    return [SearchCandidate(chunk=_seodaemun_chunk(), rank=1, score=1.0)]


def _capturing_generator(observed: dict):
    def generate(request, evidence):
        observed["request"] = request.model_dump()
        return GenerationResult(
            status="answered", answer="합성 답변", cited_chunk_ids=[evidence[0].chunk_id]
        )

    return generate


def test_generator_receives_district_and_dong_resolved_from_question():
    # 연희동만 입력하고 구는 고르지 않음 → 검색과 생성 모두 서대문구 기준이어야 한다.
    observed: dict = {}
    runner = RAGPipeline(
        resolver=resolve_request,
        retriever=_retrieve,
        generator=_capturing_generator(observed),
    )
    request = PipelineRequest(question="연희동 페트병 언제 버려요?")

    record = runner.run(request)

    assert record.response.status == "answered"
    assert observed["request"]["district"] == "서대문구"
    assert observed["request"]["dong"] == "연희동"
    # 원질문은 바꾸지 않는다 (생성기는 원질문 기준으로 답한다).
    assert observed["request"]["question"] == request.question


def test_run_record_keeps_original_request_unchanged():
    # 실행 기록에는 사용자가 실제로 보낸 요청(구 없음)을 그대로 남긴다.
    runner = RAGPipeline(
        resolver=resolve_request,
        retriever=_retrieve,
        generator=_capturing_generator({}),
    )

    record = runner.run(PipelineRequest(question="연희동 페트병 언제 버려요?"))

    assert record.request.district is None
    assert record.request.dong is None
    assert record.resolved_query.district == "서대문구"


def test_generator_keeps_selected_district_when_question_has_no_dong():
    # 고른 구만 있고 질문에 동이 없음 → 생성기도 고른 구를 그대로 받는다.
    observed: dict = {}
    runner = RAGPipeline(
        resolver=resolve_request,
        retriever=_retrieve,
        generator=_capturing_generator(observed),
    )

    runner.run(PipelineRequest(question="페트병 언제 버려요?", district="서대문구"))

    assert observed["request"]["district"] == "서대문구"
    assert observed["request"]["dong"] is None
