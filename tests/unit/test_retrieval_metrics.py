"""Hit@k 단위 테스트. 실제 검색 없이 순위만 정한 합성 후보를 쓴다."""

import pytest

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


def test_rejects_non_positive_k():
    with pytest.raises(RetrievalMetricError):
        hit_at_k(RANKED, {"row-1"}, k=0)


def test_rejects_question_without_allowed_evidence():
    # "근거 없음" 문항은 Hit@k 계산 대상이 아니다. 0점으로 세면 지표가 틀어진다.
    with pytest.raises(RetrievalMetricError):
        hit_at_k(RANKED, set(), k=5)


# --- mean_hit_rate ----------------------------------------------------------


def test_mean_hit_rate():
    assert mean_hit_rate([1, 0, 1, 1]) == pytest.approx(0.75)


def test_mean_hit_rate_rejects_empty():
    with pytest.raises(RetrievalMetricError):
        mean_hit_rate([])
