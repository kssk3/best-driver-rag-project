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
    ConfigurationHitRate,
    ExpectedRun,
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


def result(
    case_id: str,
    configuration: str,
    top_ids: list[str] | None,
    *,
    run_kind: str = "rag",
    retrieve: str = "ok",
    generate: str = "ok",
    top_k: int = 5,
    variant: str | None = None,
    rewrite_enabled: bool = False,
) -> dict:
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
        "record": {
            "run_kind": run_kind,
            # 실제 실행 설정. 기본은 구성 이름과 같은 variant, 리라이트 OFF
            "options": {
                "top_k": top_k,
                "variant": variant or configuration,
                "rewrite_enabled": rewrite_enabled,
            },
            "stages": [
                {"name": "retrieve", "status": retrieve},
                {"name": "generate", "status": generate},
            ],
            "candidates": candidates,
        },
    }


CASES = [case("q1", ["row-1"]), case("q2", ["row-9"])]


def expect(*names: str) -> dict[str, ExpectedRun]:
    """기대 설정표. 이름과 같은 variant, 리라이트 OFF (기본 A/B/C 비교)."""
    return {name: ExpectedRun(variant=name, rewrite_enabled=False) for name in names}


def test_rate_is_grouped_by_configuration_with_counts():
    results = [
        result("q1", "A", ["row-1", "row-2"]),  # 정답 1위 → 1
        result("q2", "A", ["row-1", "row-2"]),  # 정답 없음 → 0
        result("q1", "B", ["row-2", "row-1"]),  # 정답 2위 → 1
        result("q2", "B", ["row-9"]),  # 정답 1위 → 1
    ]
    assert hit_rate_by_configuration(results, CASES, expect("A", "B")) == {
        "A": ConfigurationHitRate(hits=1, cases=2, rate=0.5),
        "B": ConfigurationHitRate(hits=2, cases=2, rate=1.0),
    }


def test_failed_run_counts_as_miss_and_keeps_denominator():
    results = [
        result("q1", "C", ["row-1"]),  # 1
        result("q2", "C", None),  # 실행 오류 → 0 (빼지 않음)
    ]
    assert hit_rate_by_configuration(results, CASES, expect("C"))["C"] == (
        ConfigurationHitRate(hits=1, cases=2, rate=0.5)
    )


def test_failed_retrieve_counts_as_miss():
    # 검색 단계가 실패·건너뜀이면 후보가 남아 있어도 0점
    results = [
        result("q1", "A", ["row-1"], retrieve="error"),
        result("q2", "A", ["row-9"], retrieve="skipped"),
    ]
    assert hit_rate_by_configuration(results, CASES, expect("A"))["A"].hits == 0


def test_generation_failure_after_retrieve_still_uses_search_ranks():
    # 검색은 성공하고 답변 생성만 실패 → 기록된 검색 순위로 채점
    results = [
        result("q1", "A", ["row-1"], generate="error"),
        result("q2", "A", ["row-9"], generate="error"),
    ]
    assert hit_rate_by_configuration(results, CASES, expect("A"))["A"].hits == 2


def test_case_without_evidence_is_skipped():
    cases = [*CASES, case("no-evidence", [])]
    results = [
        result("q1", "A", ["row-1"]),
        result("q2", "A", ["row-9"]),
        result("no-evidence", "A", ["row-1"]),  # 근거 없는 문항 → 계산에서 뺌
    ]
    assert hit_rate_by_configuration(results, cases, expect("A"))["A"].cases == 2


def test_configuration_without_scorable_cases_is_kept_with_no_rate():
    # 모든 문항이 근거 없음 → 구성이 사라지지 않고 "채점할 문항 0개"로 남는다
    cases = [case("no-evidence", [])]
    results = [result("no-evidence", "A", ["row-1"])]
    assert hit_rate_by_configuration(results, cases, expect("A")) == {
        "A": ConfigurationHitRate(hits=0, cases=0, rate=None)
    }


def test_answer_outside_k_is_miss():
    results = [
        result("q1", "A", ["x-1", "x-2", "row-1"]),  # 정답 3위
        result("q2", "A", ["row-9"]),
    ]
    assert hit_rate_by_configuration(results, CASES, expect("A"), k=2)["A"].hits == 1


def test_configuration_name_is_matched_by_settings_table_not_by_string():
    # "C-rewrite"는 이름과 variant("C")가 달라도 설정표와 맞으면 통과한다
    results = [
        result("q1", "C-rewrite", ["row-1"], variant="C", rewrite_enabled=True),
        result("q2", "C-rewrite", ["x"], variant="C", rewrite_enabled=True),
    ]
    expected = {"C-rewrite": ExpectedRun(variant="C", rewrite_enabled=True)}
    assert hit_rate_by_configuration(results, CASES, expected) == {
        "C-rewrite": ConfigurationHitRate(hits=1, cases=2, rate=0.5)
    }


@pytest.mark.parametrize(
    ("results", "configurations"),
    [
        # 누락: B의 q2 결과가 없음 → 0점이 아니라 오류 (분모가 줄어 B가 좋아 보이는 것 방지)
        (
            [
                result("q1", "A", ["row-1"]),
                result("q2", "A", ["x"]),
                result("q1", "B", ["row-1"]),
            ],
            expect("A", "B"),
        ),
        # 기대한 구성 C의 결과가 아예 없음
        ([result("q1", "A", ["row-1"]), result("q2", "A", ["x"])], expect("A", "C")),
        # 중복: 같은 문항 재시도 줄이 두 번
        (
            [
                result("q1", "A", ["row-1"]),
                result("q1", "A", ["row-1"]),
                result("q2", "A", ["x"]),
            ],
            expect("A"),
        ),
        # 비교 대상이 아닌 구성
        ([result("q1", "Z", ["row-1"])], expect("A")),
        # 문항 목록에 없는 case_id
        ([result("other", "A", ["row-1"])], expect("A")),
        # 고정 근거·데모 기록 혼입
        (
            [
                result("q1", "A", ["row-1"], run_kind="fixed_evidence"),
                result("q2", "A", ["x"]),
            ],
            expect("A"),
        ),
        ([result("q1", "A", ["row-1"], run_kind="demo")], expect("A")),
        # 파이프라인 top_k(3)가 k(5)보다 작음
        ([result("q1", "A", ["row-1"], top_k=3)], expect("A")),
        # 이름표와 실제 설정 불일치: B 자리에 A 파이프라인을 연결함
        (
            [
                result("q1", "B", ["row-1"], variant="A"),
                result("q2", "B", ["row-9"], variant="A"),
            ],
            expect("B"),
        ),
        # 리라이트 불일치: 기본 비교(OFF)인데 리라이트를 켠 기록
        (
            [
                result("q1", "A", ["row-1"], rewrite_enabled=True),
                result("q2", "A", ["row-9"]),
            ],
            expect("A"),
        ),
        # 구성 목록이 비었음
        ([], {}),
    ],
)
def test_invalid_comparison_input_is_rejected(results, configurations):
    with pytest.raises(RetrievalMetricError):
        hit_rate_by_configuration(results, CASES, configurations)


def test_settings_mismatch_is_rejected_even_for_case_without_evidence():
    # 채점 대상이 아닌(근거 없는) 문항의 기록이라도 이름표와 실제 설정이 다르면 잘못 연결된 것이다
    cases = [case("no-evidence", [])]
    results = [result("no-evidence", "A", ["row-1"], variant="B")]
    with pytest.raises(RetrievalMetricError):
        hit_rate_by_configuration(results, cases, expect("A"))


def test_duplicate_case_ids_in_case_list_are_rejected():
    with pytest.raises(RetrievalMetricError):
        hit_rate_by_configuration(
            [], [case("q1", ["a"]), case("q1", ["b"])], expect("A")
        )


@pytest.mark.parametrize("k", [0, -1, 5.0, True])
@pytest.mark.parametrize(
    ("results", "cases"),
    [
        # 채점 대상 문항의 실행이 전부 실패(record 없음) → 후보 채점 분기에 안 들어가도 k를 검사
        ([result("q1", "A", None), result("q2", "A", None)], CASES),
        # 채점 대상 문항이 하나도 없음(근거 없는 문항뿐)
        ([result("no-evidence", "A", ["row-1"])], [case("no-evidence", [])]),
    ],
)
def test_invalid_k_is_rejected_regardless_of_results(results, cases, k):
    # 같은 잘못된 k가 입력 상태에 따라 오류가 되기도, 정상 점수가 되기도 하면 안 된다
    with pytest.raises(RetrievalMetricError):
        hit_rate_by_configuration(results, cases, expect("A"), k=k)


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

    def generate(request, evidence):
        if request.question == "생성 실패 질문":
            raise RuntimeError("합성 생성 실패")
        return GenerationResult(
            status="answered",
            answer="합성 답변",
            cited_chunk_ids=[evidence[0].chunk_id],
        )

    def make_pipeline(variant):
        return RAGPipeline(
            resolver=lambda request: ResolvedQuery(
                search_query=request.question, district=request.district
            ),
            retriever=retrieve,
            generator=generate,
            options=PipelineOptions(variant=variant, top_k=5, run_kind="rag"),
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
        ),
        # 검색은 성공하고 답변 생성만 실패하는 문항
        EvaluationCase(
            case_id="q2",
            question="생성 실패 질문",
            district="송파구",
            allowed_chunk_ids=["row-1"],
        ),
    ]
    results = evaluate_cases(
        cases,
        {"A": make_pipeline("A"), "B": make_pipeline("B"), "broken": BrokenPipeline()},
    )

    assert hit_rate_by_configuration(
        results,
        cases,
        {**expect("A", "B"), "broken": ExpectedRun(variant="A", rewrite_enabled=False)},
        k=5,
    ) == {
        "A": ConfigurationHitRate(hits=0, cases=2, rate=0.0),  # 정답 6위 → 5위 밖
        "B": ConfigurationHitRate(
            hits=2, cases=2, rate=1.0
        ),  # q2는 생성 실패여도 검색 1위
        "broken": ConfigurationHitRate(hits=0, cases=2, rate=0.0),  # 실행 오류 0점
    }
