"""검색 지표.

담당: 이명지
상태: Hit@k 계산과 구성별 집계(hit_rate_by_configuration).
    A/B/C 검색, 질문 정제 ON/OFF, OpenSearch를 같은 기준으로 비교한다.

Hit@k: 검색 상위 k개 안에 정답 근거(allowed_chunk_ids)가 하나라도 있으면 1, 없으면 0.
여러 문항의 Hit@k 평균이 그 검색 구성의 Hit@k 점수다 (예: 17문항 중 12개 → 12/17).

정답 근거 목록은 채점에만 쓰고 검색 입력에 넣지 않는다 (docs/problem.md).
"""

from collections.abc import Collection, Sequence

from src.common.errors import ApplicationError, ErrorCategory
from src.contracts import EvaluationCase, SearchCandidate


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

    candidates는 rank가 k 이하인 후보만 본다.
    같은 rank가 여러 개면 모두 포함한다.

    Raises:
        RetrievalMetricError:
            k가 1보다 작을 때,
            정답 근거 목록이 비어 있을 때,
                        정답 근거가 없는 문항("근거 없음" 문항)은 Hit@k 계산 대상이 아니다.
            k가 정수가 아닐 때,
            정답 근거가 문자열일 때
    """
    if type(k) is not int:
        raise RetrievalMetricError("k는 정수여야 합니다.")
    if k < 1:
        raise RetrievalMetricError("k는 1 이상이어야 합니다.")
    if isinstance(allowed_chunk_ids, str):
        raise RetrievalMetricError("정답 근거는 chunk_id 목록(list, set)이어야 합니다.")
    if not allowed_chunk_ids:
        raise RetrievalMetricError(
            "정답 근거가 없는 문항은 Hit@k를 계산할 수 없습니다."
        )

    # 모든 후보를 돌면서 rank <= k and c.chunk.chunk_id in allowed_chunk_ids면 1
    for c in candidates:
        if c.rank <= k and c.chunk.chunk_id in allowed_chunk_ids:
            return 1
    return 0


def mean_hit_rate(hits: list[int]) -> float:
    """여러 문항의 Hit@k(0 또는 1) 평균. 예: [1, 0, 1, 1] → 0.75

    Raises:
        RetrievalMetricError:
            문항이 하나도 없을 때 (0으로 나눌 수 없다),
            0/1 외의 값이 있을 때
    """

    # 빈 목록이면 RetrievalMetricError
    if not hits:
        raise RetrievalMetricError("문항이 없어 평균을 낼 수 없습니다.")

    # hits에 0이나 1 외의 값이 들어오면 오류
    for h in hits:
        if h not in (0, 1):
            # {h!r}: 잘못 들어온 값을 repr로 보여 준다. 숫자 1과 문자열 '1'이 따옴표로 구분된다.
            raise RetrievalMetricError(f"Hit 값은 0 또는 1이어야 합니다: {h!r}")

    return sum(hits) / len(hits)


def hit_rate_by_configuration(
    results: list[dict],
    cases: Sequence[EvaluationCase],
    k: int = 5,
) -> dict[str, float]:
    """evaluate_cases 결과를 구성(A/B/C 등)별 Hit@k 평균으로 묶는다.

    예: {"A": 0.71, "B": 0.82, "C": 0.88}

    - 정답 근거가 없는 문항("근거 없음" 문항)은 Hit@k 대상이 아니라서 뺀다.
    - 실행 오류로 record가 없으면 0점으로 센다.
      빼면 분모가 줄어 점수가 실제보다 좋게 나온다 (17문항 중 3개 실패 → 14문항 평균이 됨).

    Raises:
        RetrievalMetricError: 결과의 case_id가 cases에 없을 때 (다른 문항 세트를 섞은 실수)
    """
    known_case_ids = {case.case_id for case in cases}
    # ① case_id → 정답 근거 목록. 근거 없는 문항은 넣지 않는다
    allowed_by_case = {
        case.case_id: case.allowed_chunk_ids for case in cases if case.allowed_chunk_ids
    }

    # ② 구성별로 문항마다 Hit(0 또는 1)를 모은다. 예: {"A": [1, 0, 1], "B": [1, 1, 1]}
    hits_by_config: dict[str, list[int]] = {}
    for result in results:
        case_id = result["case_id"]
        if case_id not in known_case_ids:
            raise RetrievalMetricError(f"문항 목록에 없는 case_id입니다: {case_id!r}")
        allowed = allowed_by_case.get(case_id)
        if allowed is None:  # 근거 없는 문항 → 채점 대상 아님
            continue

        record = result["record"]
        if record is None:
            hit = 0
        else:
            # record는 JSON dict라서 후보를 다시 SearchCandidate로 바꾼다
            candidates = [
                SearchCandidate.model_validate(c) for c in record["candidates"]
            ]
            hit = hit_at_k(candidates=candidates, allowed_chunk_ids=allowed, k=k)

        hits_by_config.setdefault(result["configuration"], []).append(hit)

    # ③ 구성별 평균
    return {config: mean_hit_rate(hits) for config, hits in hits_by_config.items()}
