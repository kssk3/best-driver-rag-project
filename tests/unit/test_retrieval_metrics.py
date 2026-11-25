"""Hit@k 단위 테스트. 실제 검색 없이 순위만 정한 합성 후보를 쓴다."""

import pytest

from src.common.errors import ErrorCategory
from src.contracts import Chunk, SearchCandidate
from src.evaluation.retrieval_metrics import (
    RetrievalMetricError,
    hit_at_k,
    mean_hit_rate,
)


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
