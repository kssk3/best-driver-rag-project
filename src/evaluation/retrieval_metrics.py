"""검색 지표.

담당: 이명지
상태: Hit@k 계산. A/B/C 검색, 질문 정제 ON/OFF, OpenSearch를 같은 기준으로 비교한다.

Hit@k: 검색 상위 k개 안에 정답 근거(allowed_chunk_ids)가 하나라도 있으면 1, 없으면 0.
여러 문항의 Hit@k 평균이 그 검색 구성의 Hit@k 점수다 (예: 17문항 중 12개 → 12/17).

정답 근거 목록은 채점에만 쓰고 검색 입력에 넣지 않는다 (docs/problem.md).
"""

from collections.abc import Collection

from src.common.errors import ApplicationError, ErrorCategory
from src.contracts import SearchCandidate


class RetrievalMetricError(ApplicationError, ValueError):
    """Hit@k를 계산할 수 없는 입력. 0점으로 숨기면 지표가 틀어지므로 오류로 알린다."""

    code = "evaluation.invalid_retrieval_metric_input"
    category = ErrorCategory.INVALID_INPUT


def hit_at_k(
    candidates: list[SearchCandidate],
    allowed_chunk_ids: Collection[str],
    k: int,
) -> int:
    """상위 k개 후보 안에 정답 근거가 하나라도 있으면 1, 없으면 0.

    candidates는 rank 순서라고 가정하지 않고 rank로 다시 정렬해서 본다.

    Raises:
        RetrievalMetricError: k가 1보다 작거나 정답 근거 목록이 비어 있을 때.
            정답 근거가 없는 문항("근거 없음" 문항)은 Hit@k 계산 대상이 아니다.
    """
    if k < 1:
        raise RetrievalMetricError("k는 1 이상이어야 합니다.")
    if not allowed_chunk_ids:
        raise RetrievalMetricError(
            "정답 근거가 없는 문항은 Hit@k를 계산할 수 없습니다."
        )

    # candidates를 rank가 작은 순서(1위부터)로 정렬하고 앞에서 k개만 남기기
    top: list[SearchCandidate] = sorted(candidates, key=lambda c: c.rank)[:k]

    # top 안에 chunk_id가 allowed_chunk_ids에 들어 있는 후보가 하나라도 있으면 1
    for c in top:
        if c.chunk.chunk_id in allowed_chunk_ids:
            return 1
    return 0


def mean_hit_rate(hits: list[int]) -> float:
    """여러 문항의 Hit@k(0 또는 1) 평균. 예: [1, 0, 1, 1] → 0.75

    Raises:
        RetrievalMetricError: 문항이 하나도 없을 때 (0으로 나눌 수 없다).
    """
    # 빈 목록이면 RetrievalMetricError, 아니면 합계 ÷ 개수
    if not hits:
        raise RetrievalMetricError("문항이 없어 평균을 낼 수 없습니다.")
    return sum(hits) / len(hits)
