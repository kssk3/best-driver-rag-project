"""합성 콜백으로 호출 경계, 근거 보존과 평가 입력 분리를 검증한다."""

import json
from pathlib import Path

import pytest

from src.contracts import (
    Chunk, EvaluationCase, GenerationResult, PipelineOptions, PipelineRequest,
    PlaceLookupResult, ResolvedQuery, RunRecord, SearchCandidate,
)
from src.evaluation.runner import EvaluationCaseError, evaluate_cases, load_evaluation_cases
from src.observability.records import RunRecorder
from src.pipeline import RAGPipeline


def chunk(chunk_id="sample", *, scope="district", district="송파구", content=None):
    return Chunk(
        chunk_id=chunk_id, source_document_id=f"synthetic-{chunk_id}", source_document_version="v1",
        title="합성 안내", content_format="html", content=content or "<p>합성 안내</p><p>예외 조건</p>",
        source_url="https://example.org/guide", source_location="합성 별표 1",
        scope_type=scope, districts=[district] if scope == "district" else [],
        chunking_version="synthetic-v1",
    )


def candidate(value, rank=1):
    return SearchCandidate(chunk=value, rank=rank, score=1.0 / rank, stage_scores={"synthetic": 0.5})


def resolve(request):
    return ResolvedQuery(search_query=request.question, district=request.district, dong=request.dong)


def retrieve(query, *, variant, top_k):
    return [candidate(chunk())]


def generate(request, evidence):
    if not evidence:
        return GenerationResult(status="insufficient_evidence", answer="합성 근거 없음")
    return GenerationResult(status="answered", answer="합성 답변", cited_chunk_ids=[evidence[0].chunk_id])


def pipeline(**overrides):
    return RAGPipeline(**{"resolver": resolve, "retriever": retrieve, "generator": generate, **overrides})


def statuses(record):
    return {stage.name: stage.status for stage in record.stages}


def test_original_question_candidates_input_and_citations_are_distinct():
    request = PipelineRequest(question="이걸 어디에 버려요?", district="송파구", conditions={"주택": "단독"})
    originals = [
        candidate(chunk("wrong", district="서대문구"), 1),
        candidate(chunk("unknown", scope="unknown"), 2),
        candidate(chunk("common", scope="common"), 3),
        candidate(chunk("local"), 4),
    ]
    observed = {}

    def rewriter(query):
        query.district = "서대문구"
        return "송파구 합성 검색어"

    def retriever(query, *, variant, top_k):
        observed["search"] = (query.search_query, query.district, variant, top_k)
        query.search_query = "콜백 내부 수정"
        return originals

    def generator(raw_request, evidence):
        observed["generation"] = raw_request.model_dump()
        observed["evidence"] = [item.chunk_id for item in evidence]
        raw_request.question = "콜백 내부 수정"
        raw_request.conditions["주택"] = "수정"
        evidence[0].content = "콜백 내부 수정"
        return GenerationResult(status="answered", answer="합성 답변", cited_chunk_ids=["local"])

    options = PipelineOptions(variant="B", rewrite_enabled=True, versions={"data": "synthetic-v1"})
    runner = pipeline(retriever=retriever, generator=generator, rewriter=rewriter, options=options)
    options.versions["data"] = "outside-mutation"
    record = runner.run(request)

    assert record.response.status == "answered"
    assert observed["search"] == ("송파구 합성 검색어", "송파구", "B", 5)
    assert observed["generation"]["question"] == request.question == record.request.question
    assert observed["evidence"] == record.model_input_chunk_ids == ["common", "local"]
    assert [item.chunk.chunk_id for item in record.candidates] == ["wrong", "unknown", "common", "local"]
    assert [item.rank for item in record.candidates] == [1, 2, 3, 4]
    assert record.candidates[2].chunk.content == originals[2].chunk.content
    assert record.response.citations[0].chunk_id == "local"
    assert record.response.citations[0].source_location == "합성 별표 1"
    assert record.options.versions == {"data": "synthetic-v1"}
    assert record.request.conditions == {"주택": "단독"}
    assert record.response.places.status == "unavailable"


def test_context_limit_excludes_whole_chunk_without_losing_note():
    large = chunk("large", content="표 내용" * 30 + "반드시 보존할 각주")
    small = chunk("small", content="짧은 본문과 각주")
    record = pipeline(
        retriever=lambda *args, **kwargs: [candidate(large), candidate(small, 2)],
        options=PipelineOptions(max_context_chars=20),
    ).run(PipelineRequest(question="합성 질문", district="송파구"))
    assert record.model_input_chunk_ids == ["small"]
    assert record.candidates[0].chunk.content == large.content
    assert record.response.citations[0].chunk_id == "small"
    assert record.warnings


def test_clarification_skips_retrieval_generation_and_places():
    def forbidden(*args, **kwargs):
        pytest.fail("확인 질문 단계에서 호출하면 안 됨")
    record = pipeline(
        resolver=lambda request: ResolvedQuery(
            search_query=request.question, status="needs_clarification", clarification_question="어느 구인가요?",
        ), retriever=forbidden, generator=forbidden, place_lookup=forbidden,
    ).run(PipelineRequest(question="합성 질문"))
    assert record.response.status == "needs_clarification"
    assert record.response.answer == "어느 구인가요?"
    assert statuses(record)["retrieve"] == statuses(record)["generate"] == "skipped"
    assert record.model_input_chunk_ids == []


@pytest.mark.parametrize("stage_name, callback_name", [("resolve", "resolver"), ("retrieve", "retriever"), ("generate", "generator")])
def test_pipeline_exceptions_are_errors_not_insufficient_evidence(stage_name, callback_name):
    def fail(*args, **kwargs):
        raise RuntimeError("합성 실패")
    record = pipeline(**{callback_name: fail}).run(PipelineRequest(question="질문", district="송파구"))
    assert record.response.status == "error"
    assert "합성 실패" in record.response.error
    assert statuses(record)[stage_name] == "error"


@pytest.mark.parametrize("rewriter", [None, lambda query: " ", lambda query: 10])
def test_bad_rewrite_falls_back_and_preserves_failure_stage(rewriter):
    observed = []
    def retriever(query, **kwargs):
        observed.append(query.search_query)
        return [candidate(chunk())]
    record = pipeline(
        rewriter=rewriter, retriever=retriever, options=PipelineOptions(rewrite_enabled=True),
    ).run(PipelineRequest(question="원질문", district="송파구"))
    assert observed == ["원질문"]
    assert record.search_query == "원질문"
    assert record.response.status == "answered"
    assert statuses(record)["rewrite"] == "error"
    assert record.warnings


def test_disabled_rewrite_is_not_called():
    def fail(query):
        pytest.fail("리라이트 비활성")
    record = pipeline(rewriter=fail).run(PipelineRequest(question="원질문", district="송파구"))
    assert statuses(record)["rewrite"] == "skipped"
    assert record.search_query == "원질문"


@pytest.mark.parametrize("cited_ids", [[], ["not-input"], ["sample", "not-input"]])
def test_invalid_citations_are_rejected(cited_ids):
    record = pipeline(generator=lambda request, evidence: GenerationResult(
        status="answered", answer="합성 답변", cited_chunk_ids=cited_ids,
    )).run(PipelineRequest(question="질문", district="송파구"))
    assert record.response.status == "error"
    assert statuses(record)["citations"] == "error"
    assert record.response.citations == []


def test_empty_evidence_policy_is_delegated_to_generator():
    record = pipeline(retriever=lambda *args, **kwargs: []).run(PipelineRequest(question="질문", district="송파구"))
    assert record.response.status == "insufficient_evidence"
    assert record.response.error is None
    assert statuses(record)["generate"] == "ok"


def test_place_failure_is_separate_from_document_answer():
    def fail(*args):
        raise ConnectionError("합성 장소 조회 실패")
    record = pipeline(place_lookup=fail).run(PipelineRequest(question="질문", district="송파구"))
    assert record.response.status == "answered"
    assert record.response.places.status == "error"
    assert "장소 조회 실패" in record.response.places.error
    assert statuses(record)["place_lookup"] == "error"


def test_place_empty_is_distinct_from_unavailable():
    record = pipeline(place_lookup=lambda *args: PlaceLookupResult(status="empty")).run(
        PipelineRequest(question="질문", district="송파구")
    )
    assert record.response.places.status == "empty"
    assert statuses(record)["place_lookup"] == "ok"


def test_record_roundtrip_does_not_overwrite_and_retry_has_new_run_id(tmp_path):
    recorder = RunRecorder(tmp_path / "runs")
    runner = pipeline(recorder=recorder)
    request = PipelineRequest(question="한글 합성 질문", district="송파구")
    first = runner.run(request)
    path = recorder.directory / f"{first.run_id}.json"
    original_bytes = path.read_bytes()
    restored = RunRecord.model_validate_json(original_bytes)
    assert restored.model_dump(mode="json") == first.model_dump(mode="json")
    assert "한글 합성 질문" in original_bytes.decode("utf-8")
    with pytest.raises(FileExistsError):
        recorder.write(first)
    assert path.read_bytes() == original_bytes
    second = runner.run(request)
    assert second.run_id != first.run_id
    assert second.request_id == first.request_id == request.request_id
    assert len(list(recorder.directory.glob("*.json"))) == 2


def test_record_path_and_response_identity_are_checked(tmp_path):
    record = pipeline().run(PipelineRequest(question="질문", district="송파구"))
    recorder = RunRecorder(tmp_path)
    with pytest.raises(ValueError, match="run_id"):
        recorder.write(record.model_copy(update={"run_id": "../outside"}))
    record.response.run_id = "different"
    with pytest.raises(ValueError, match="식별자"):
        recorder.write(record)
    assert list(tmp_path.iterdir()) == []


def test_record_write_failure_is_reported(tmp_path):
    blocked = tmp_path / "file"
    blocked.write_text("existing", encoding="utf-8")
    record = pipeline(recorder=RunRecorder(blocked)).run(PipelineRequest(question="질문", district="송파구"))
    assert record.response.status == "error"
    assert "기록 저장 실패" in record.response.error
    assert statuses(record)["record"] == "error"
    assert blocked.read_text(encoding="utf-8") == "existing"


def test_synthetic_twenty_cases_four_configurations_make_eighty_runs_without_gold_leakage():
    seen = []
    def resolver(request):
        seen.append(request.model_dump())
        assert "PRIVATE-GOLD" not in str(request.model_dump())
        return resolve(request)
    pipelines = {
        name: pipeline(resolver=resolver, options=PipelineOptions(variant=variant, rewrite_enabled=rewrite, run_kind="demo"),
                       rewriter=lambda query: query.search_query + " 합성 리라이트")
        for name, variant, rewrite in [("A", "A", False), ("B", "B", False), ("C", "C", False), ("C-rewrite", "C", True)]
    }
    cases = [EvaluationCase(
        case_id=f"synthetic-{i}", question=f"합성 질문 {i}", district="송파구", conditions={"주택": "단독"},
        expected_status="answered", reference_answer="PRIVATE-GOLD-ANSWER", allowed_chunk_ids=["PRIVATE-GOLD-ID"],
    ) for i in range(20)]
    results = evaluate_cases(cases, pipelines)
    assert len(results) == len(seen) == 80
    assert len({item["run_id"] for item in results}) == 80
    assert all(item["status"] == "answered" for item in results)
    assert all(item["record"]["run_kind"] == "demo" for item in results)
    assert "PRIVATE-GOLD" not in json.dumps(results, ensure_ascii=False)
    for item in results:
        assert ("리라이트" in item["record"]["search_query"]) == (item["configuration"] == "C-rewrite")


def test_evaluation_keeps_failures_and_continues():
    class BrokenPipeline:
        def run(self, request):
            raise RuntimeError("합성 구성 실패")
    cases = [EvaluationCase(case_id="synthetic", question="질문", district="송파구")]
    results = evaluate_cases(cases, {"broken": BrokenPipeline(), "working": pipeline()})
    assert [item["status"] for item in results] == ["error", "answered"]
    assert results[0]["run_id"] is None and results[0]["record"] is None
    assert "합성 구성 실패" in results[0]["error"]


@pytest.mark.parametrize("wrapped", [False, True])
def test_load_explicit_evaluation_file(tmp_path, wrapped):
    cases = [{"case_id": "synthetic-1", "question": "합성 질문", "reference_answer": "합성 정답"}]
    payload = {"is_synthetic": True, "cases": cases} if wrapped else cases
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8-sig")
    result = load_evaluation_cases(path)
    assert result[0].case_id == "synthetic-1"
    assert result[0].reference_answer == "합성 정답"


@pytest.mark.parametrize("payload", [
    {"cases": []}, {"is_synthetic": "true", "cases": []},
    [{"case_id": "a", "question": "질문", "unknown": 1}],
    [{"case_id": "a", "question": "질문"}, {"case_id": "a", "question": "다른 질문"}],
    [{"case_id": "a", "question": " "}], [{"case_id": "a"}],
    [{"case_id": 1, "question": "질문"}], [{"case_id": "a", "question": "질문", "expected_status": "unknown"}],
])
def test_invalid_evaluation_inputs_fail_before_running(tmp_path, payload):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(EvaluationCaseError, match="bad.json"):
        load_evaluation_cases(path)


def test_duplicate_json_keys_are_rejected(tmp_path):
    path = tmp_path / "duplicate.json"
    path.write_text('[{"case_id":"a","case_id":"b","question":"Q"}]', encoding="utf-8")
    with pytest.raises(EvaluationCaseError, match="중복 JSON"):
        load_evaluation_cases(path)
