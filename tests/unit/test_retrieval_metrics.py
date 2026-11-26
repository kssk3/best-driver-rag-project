"""Hit@k 단위 테스트. 실제 검색 없이 순위만 정한 합성 후보를 쓴다."""

import pytest

from src.common.errors import ErrorCategory
from src.contracts import (
    Chunk,
    EvaluationCase,
    GenerationResult,
    PipelineOptions,
    ResolvedQuery,
    SearchCandidate,
)
from src.evaluation.retrieval_metrics import (
    RetrievalMetricError,
    hit_at_k,
    hit_rate_by_configuration,
    mean_hit_rate,
)
from src.evaluation.runner import evaluate_cases
from src.pipeline import RAGPipeline


def candidate(chunk_id: str, rank: int) -> SearchCandidate:
    chunk = Chunk(
        chunk_id=chunk_id,
        source_document_id=f"synthetic-{chunk_id}",
        source_document_version="v1",
        title="합성 안내",
        content_format="html",
        content="합성 본문",
        source_url="https://example.org/guide",
        source_location="합성 별표 1",
        scope_type="district",
        districts=["송파구"],
        chunking_version="synthetic-v1",
    )
    return SearchCandidate(chunk=chunk, rank=rank, score=1.0 / rank)


# 1위 row-1, 2위 row-2, ... 5위 row-5
RANKED = [candidate(f"row-{n}", n) for n in range(1, 6)]


# --- hit_at_k ---------------------------------------------------------------


def test_hit_when_answer_is_first():
    assert hit_at_k(RANKED, {"row-1"}, k=5) == 1


def test_hit_when_answer_is_exactly_at_k():
    # 정답이 5위 → Hit@5는 성공, Hit@3은 실패.
    assert hit_at_k(RANKED, {"row-5"}, k=5) == 1
    assert hit_at_k(RANKED, {"row-5"}, k=3) == 0


def test_miss_when_answer_not_in_candidates():
    assert hit_at_k(RANKED, {"row-99"}, k=5) == 0


def test_hit_when_any_of_several_answers_is_in_top_k():
    # 허용 근거가 여러 개면 그중 하나만 있어도 성공.
    assert hit_at_k(RANKED, {"row-99", "row-2"}, k=3) == 1


def test_uses_rank_not_list_order():
    # 목록 순서가 섞여 있어도 rank 기준으로 상위 k개를 본다.
    shuffled = list(reversed(RANKED))  # row-5(5위)가 목록 맨 앞
    assert hit_at_k(shuffled, {"row-5"}, k=3) == 0
    assert hit_at_k(shuffled, {"row-1"}, k=1) == 1


def test_miss_when_no_candidates():
    # 검색 결과가 0건이면 실패(0). 검색 오류는 이 함수까지 오지 않는다.
    assert hit_at_k([], {"row-1"}, k=5) == 0


def test_hit_when_fewer_candidates_than_k():
    # 후보가 k개보다 적어도 그 안에 정답이 있으면 성공.
    assert hit_at_k(RANKED[:2], {"row-2"}, k=5) == 1


def test_accepts_allowed_ids_as_list():
    # 실제 문항 파일의 allowed_chunk_ids는 list다.
    assert hit_at_k(RANKED, ["row-99", "row-3"], k=3) == 1


def test_skipped_rank_beyond_k_is_not_a_hit():
    # rank가 건너뛰어도(1,2,3,4,9) 9위는 Hit@5가 아니다. 목록 앞 5개가 아니라 rank로 판단.
    gapped = [candidate(f"row-{n}", n) for n in (1, 2, 3, 4, 9)]
    assert hit_at_k(gapped, {"row-9"}, k=5) == 0
    assert hit_at_k(gapped, {"row-4"}, k=5) == 1


def test_tied_rank_counts_all_tied_candidates():
    # 같은 rank가 여러 개면 목록 순서와 관계없이 모두 k 안으로 본다.
    tied = [candidate("row-a", 1), candidate("row-b", 1), candidate("row-c", 2)]
    assert hit_at_k(tied, {"row-b"}, k=1) == 1
    assert hit_at_k(list(reversed(tied)), {"row-b"}, k=1) == 1
    assert hit_at_k(tied, {"row-c"}, k=1) == 0


def test_rejects_non_positive_k():
    with pytest.raises(RetrievalMetricError):
        hit_at_k(RANKED, {"row-1"}, k=0)


@pytest.mark.parametrize("bad_k", [True, "5", 5.0])
def test_rejects_non_int_k(bad_k):
    # True는 int의 하위 타입이라 막지 않으면 Hit@1로 계산된다.
    with pytest.raises(RetrievalMetricError):
        hit_at_k(RANKED, {"row-1"}, k=bad_k)


def test_rejects_single_string_as_allowed_ids():
    # 문자열이면 `in`이 부분 문자열 비교가 되어 "row-1"이 "row-12"에 맞는다.
    with pytest.raises(RetrievalMetricError):
        hit_at_k([candidate("row-12", 1)], "row-1", k=5)


def test_rejects_question_without_allowed_evidence():
    # "근거 없음" 문항은 Hit@k 계산 대상이 아니다. 0점으로 세면 지표가 틀어진다.
    with pytest.raises(RetrievalMetricError):
        hit_at_k(RANKED, set(), k=5)


def test_metric_error_has_common_code_and_category():
    # 공통 에러 규칙(docs/ERRORS.md): 실행 기록에 남을 코드와 분류.
    with pytest.raises(RetrievalMetricError) as caught:
        hit_at_k(RANKED, {"row-1"}, k=0)
    assert caught.value.code == "evaluation.invalid_retrieval_metric_input"
    assert caught.value.category == ErrorCategory.INVALID_INPUT
    assert isinstance(caught.value, ValueError)


# --- mean_hit_rate ----------------------------------------------------------


def test_mean_hit_rate():
    assert mean_hit_rate([1, 0, 1, 1]) == pytest.approx(0.75)


def test_mean_hit_rate_rejects_empty():
    with pytest.raises(RetrievalMetricError):
        mean_hit_rate([])


def test_mean_hit_rate_rejects_values_other_than_zero_or_one():
    # [1, 5]를 받아 3.0을 돌려주면 Hit 비율이 1을 넘는다.
    with pytest.raises(RetrievalMetricError, match="5"):
        mean_hit_rate([1, 5])


# --- hit_rate_by_configuration ----------------------------------------------


def case(case_id: str, allowed: list[str]) -> EvaluationCase:
    return EvaluationCase(
        case_id=case_id, question="합성 질문", allowed_chunk_ids=allowed
    )


def result(case_id: str, configuration: str, top_ids: list[str] | None) -> dict:
    """evaluate_cases 결과 한 줄. top_ids=None이면 실행 오류(record 없음)."""
    if top_ids is None:
        return {"case_id": case_id, "configuration": configuration, "record": None}
    candidates = [
        candidate(chunk_id, rank).model_dump(mode="json")
        for rank, chunk_id in enumerate(top_ids, start=1)
    ]
    return {
        "case_id": case_id,
        "configuration": configuration,
        "record": {"candidates": candidates},
    }


CASES = [case("q1", ["row-1"]), case("q2", ["row-9"])]


def test_rate_is_grouped_by_configuration():
    results = [
        result("q1", "A", ["row-1", "row-2"]),  # 정답 1위 → 1
        result("q2", "A", ["row-1", "row-2"]),  # 정답 없음 → 0
        result("q1", "B", ["row-2", "row-1"]),  # 정답 2위 → 1
        result("q2", "B", ["row-9"]),  # 정답 1위 → 1
    ]
    assert hit_rate_by_configuration(results, CASES) == {"A": 0.5, "B": 1.0}


def test_failed_run_counts_as_miss_and_keeps_denominator():
    results = [
        result("q1", "C", ["row-1"]),  # 1
        result("q2", "C", None),  # 실행 오류 → 0 (빼지 않음)
    ]
    assert hit_rate_by_configuration(results, CASES) == {"C": 0.5}


def test_case_without_evidence_is_skipped():
    cases = [*CASES, case("no-evidence", [])]
    results = [
        result("q1", "A", ["row-1"]),
        result("no-evidence", "A", ["row-1"]),  # 근거 없는 문항 → 계산에서 뺌
    ]
    assert hit_rate_by_configuration(results, cases) == {"A": 1.0}


def test_answer_outside_k_is_miss():
    results = [result("q1", "A", ["x-1", "x-2", "row-1"])]  # 정답 3위
    assert hit_rate_by_configuration(results, CASES, k=2) == {"A": 0.0}


def test_unknown_case_id_is_rejected():
    with pytest.raises(RetrievalMetricError):
        hit_rate_by_configuration([result("other", "A", ["row-1"])], CASES)


def test_rate_from_real_evaluate_cases_output():
    # 손으로 만든 dict가 아니라 공용 실행기(evaluate_cases)가 실제로 내놓는 결과 모양으로 확인한다.
    # 구성마다 검색 결과를 다르게: A는 정답이 6위(5위 밖), B는 정답이 1위
    ranked_ids = {
        "A": [f"x-{n}" for n in range(1, 6)] + ["row-1"],
        "B": ["row-1", "x-1"],
    }

    def retrieve(query, *, variant, top_k):
        ids = ranked_ids[variant][:top_k]
        return [candidate(chunk_id, rank) for rank, chunk_id in enumerate(ids, 1)]

    def make_pipeline(variant):
        return RAGPipeline(
            resolver=lambda request: ResolvedQuery(
                search_query=request.question, district=request.district
            ),
            retriever=retrieve,
            generator=lambda request, evidence: GenerationResult(
                status="answered",
                answer="합성 답변",
                cited_chunk_ids=[evidence[0].chunk_id],
            ),
            options=PipelineOptions(variant=variant, top_k=5, run_kind="demo"),
        )

    class BrokenPipeline:
        def run(self, request):
            raise RuntimeError("합성 실행 실패")

    cases = [
        EvaluationCase(
            case_id="q1",
            question="합성 질문",
            district="송파구",
            allowed_chunk_ids=["row-1"],
        )
    ]
    results = evaluate_cases(
        cases,
        {"A": make_pipeline("A"), "B": make_pipeline("B"), "broken": BrokenPipeline()},
    )

    assert hit_rate_by_configuration(results, cases, k=5) == {
        "A": 0.0,  # top_k=5라 6위 정답은 검색 결과에 없다
        "B": 1.0,
        "broken": 0.0,  # 실행 오류는 0점
    }
