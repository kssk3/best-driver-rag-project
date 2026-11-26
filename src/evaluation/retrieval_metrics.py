"""검색 지표.

담당: 이명지
상태: Hit@k 계산과 구성별 집계(hit_rate_by_configuration).
    A/B/C 검색, 질문 정제 ON/OFF, OpenSearch를 같은 기준으로 비교한다.

Hit@k: 검색 상위 k개 안에 정답 근거(allowed_chunk_ids)가 하나라도 있으면 1, 없으면 0.
여러 문항의 Hit@k 평균이 그 검색 구성의 Hit@k 점수다 (예: 17문항 중 12개 → 12/17).

정답 근거 목록은 채점에만 쓰고 검색 입력에 넣지 않는다 (docs/problem.md).
"""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

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
    _check_k(k)
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


@dataclass(frozen=True)
class ConfigurationHitRate:
    """한 구성의 Hit@k 결과. 평균만 보면 몇 문항으로 낸 점수인지 알 수 없어 개수도 함께 둔다.

    hits: 적중한 문항 수, cases: 채점한 문항 수, rate: hits / cases.
    채점할 문항이 0개면 rate는 None (0점과 "채점할 게 없음"을 구분한다).
    """

    hits: int
    cases: int
    rate: float | None


@dataclass(frozen=True)
class ExpectedRun:
    """구성 이름이 가리켜야 하는 실제 실행 설정. 이름표와 실제 파이프라인이 맞는지 대조한다.

    예: "C-rewrite" → ExpectedRun(variant="C", rewrite_enabled=True)
    이름 문자열을 variant와 바로 비교하지 않는 이유: "C-rewrite"처럼 이름과 variant가 다를 수 있다.
    """

    variant: str
    rewrite_enabled: bool


def hit_rate_by_configuration(
    results: list[dict],
    cases: Sequence[EvaluationCase],
    configurations: Mapping[str, ExpectedRun],
    k: int = 5,
) -> dict[str, ConfigurationHitRate]:
    """evaluate_cases 결과를 구성(A/B/C 등)별 Hit@k로 묶는다. 실검색(run_kind=rag) 비교용.

    예: {"A": ConfigurationHitRate(hits=12, cases=17, rate=0.71), ...}

    configurations는 구성 이름 → 기대 설정표다.
    예: {"A": ExpectedRun("A", False), "B": ExpectedRun("B", False)}
    실행 기록의 실제 variant·rewrite_enabled가 표와 다르면 오류다
    (B 자리에 A 파이프라인을 연결하면 A 점수가 B 성능으로 집계되는 것을 막는다).

    채점 대상은 정답 근거가 있는 문항 × configurations다. 그 조합이 결과에 정확히 한 번씩
    있어야 한다. 빠지거나 겹치면 분모가 달라져 점수가 틀리므로 0점이 아니라 오류로 알린다.

    문항 하나의 점수:
    - 실행 오류로 record가 없음 → 0점 (실행했지만 실패)
    - retrieve 단계가 ok가 아님(실패·건너뜀) → 0점
    - retrieve 성공 → 기록된 검색 순위로 hit_at_k. 그 뒤 답변 생성이 실패해도 검색 점수는 센다.

    Raises:
        RetrievalMetricError:
            k가 1 이상 정수가 아닐 때, configurations가 비었을 때,
            문항 목록에 같은 case_id가 두 번 있을 때,
            결과에 모르는 case_id·configuration이 있을 때,
            (configuration, case_id)가 빠지거나 두 번 있을 때,
            실검색이 아닌 기록(demo, fixed_evidence)이 섞였을 때,
            실행 기록의 variant·rewrite_enabled가 기대 설정표와 다를 때,
            파이프라인 top_k가 k보다 작아 Hit@k를 잴 수 없을 때
    """
    _check_k(k)
    if not configurations:  # dict라서 같은 이름은 애초에 두 번 들어갈 수 없다
        raise RetrievalMetricError("비교할 구성 목록이 비었습니다.")
    case_ids = [case.case_id for case in cases]
    if len(set(case_ids)) != len(case_ids):
        raise RetrievalMetricError("문항 목록에 같은 case_id가 두 번 있습니다.")

    # ① case_id → 정답 근거 목록. 근거 없는 문항은 Hit@k 대상이 아니라서 넣지 않는다
    allowed_by_case = {
        case.case_id: case.allowed_chunk_ids for case in cases if case.allowed_chunk_ids
    }

    # ② (구성, 문항)마다 점수 한 개. 한 번씩만 있어야 한다
    hit_by_run: dict[tuple[str, str], int] = {}
    seen: set[tuple[str, str]] = set()
    for result in results:
        case_id = result["case_id"]
        configuration = result["configuration"]
        if case_id not in case_ids:
            raise RetrievalMetricError(f"문항 목록에 없는 case_id입니다: {case_id!r}")
        if configuration not in configurations:
            raise RetrievalMetricError(
                f"비교 대상이 아닌 구성입니다: {configuration!r}"
            )
        key = (configuration, case_id)
        if key in seen:
            raise RetrievalMetricError(f"같은 구성·문항 결과가 두 번 있습니다: {key!r}")
        seen.add(key)
        # 이름표(configuration)와 실제 실행 설정이 맞는지. 채점 대상이 아닌 문항도 확인한다
        _check_settings(result["record"], configuration, configurations[configuration])

        allowed = allowed_by_case.get(case_id)
        if allowed is None:  # 근거 없는 문항 → 채점 대상 아님
            continue
        hit_by_run[key] = _score_run(result["record"], allowed, k)

    # ③ 빠진 조합 찾기. 없는 줄을 조용히 넘기면 그 구성만 문제 수가 줄어든다
    missing = [
        (configuration, case_id)
        for configuration in configurations
        for case_id in allowed_by_case
        if (configuration, case_id) not in hit_by_run
    ]
    if missing:
        raise RetrievalMetricError(f"결과에 없는 구성·문항이 있습니다: {missing!r}")

    # ④ 구성별로 적중 수·문항 수·평균. 채점할 문항이 0개인 구성도 빠뜨리지 않는다
    summary: dict[str, ConfigurationHitRate] = {}
    for configuration in configurations:
        hits = [hit_by_run[(configuration, case_id)] for case_id in allowed_by_case]
        summary[configuration] = ConfigurationHitRate(
            hits=sum(hits),
            cases=len(hits),
            rate=mean_hit_rate(hits) if hits else None,
        )
    return summary


def _check_settings(
    record: dict | None, configuration: str, expected: ExpectedRun
) -> None:
    """실행 기록의 실제 variant·rewrite_enabled가 이 구성의 기대 설정과 같은지 확인한다."""
    if (
        record is None
    ):  # 실행 자체가 실패해 설정 기록이 없다 → 대조할 것이 없음 (0점 처리)
        return
    actual = ExpectedRun(
        variant=record["options"]["variant"],
        rewrite_enabled=record["options"]["rewrite_enabled"],
    )
    if actual != expected:
        raise RetrievalMetricError(
            f"구성 {configuration!r}의 실제 실행 설정이 기대와 다릅니다: "
            f"기대 {expected}, 실제 {actual}"
        )


def _check_k(k: int) -> None:
    if type(k) is not int:
        raise RetrievalMetricError("k는 정수여야 합니다.")
    if k < 1:
        raise RetrievalMetricError("k는 1 이상이어야 합니다.")


def _score_run(record: dict | None, allowed: list[str], k: int) -> int:
    """실행 기록 하나의 Hit@k. 실패는 0점, 실검색이 아닌 기록은 오류."""
    if record is None:  # 실행 자체가 실패해 기록이 없음
        return 0
    if record["run_kind"] != "rag":
        # demo·fixed_evidence는 검색을 하지 않았거나 정해 준 근거라 검색 점수가 아니다
        raise RetrievalMetricError(
            f"실검색(rag)이 아닌 기록은 비교할 수 없습니다: {record['run_kind']!r}"
        )
    if record["options"]["top_k"] < k:
        # 후보를 3개만 받았는데 Hit@5라고 하면 실제보다 낮게 나온다
        raise RetrievalMetricError(
            f"파이프라인 top_k({record['options']['top_k']})가 k({k})보다 작습니다."
        )
    retrieve = [stage for stage in record["stages"] if stage["name"] == "retrieve"]
    if not retrieve or retrieve[0]["status"] != "ok":
        return 0  # 검색 실패·건너뜀(지역 되묻기 등) → 정답을 못 찾은 것
    # 검색은 성공했다. 뒤의 답변 생성이 실패해도 검색 순위는 기록에 남아 있다
    candidates = [SearchCandidate.model_validate(c) for c in record["candidates"]]
    return hit_at_k(candidates=candidates, allowed_chunk_ids=allowed, k=k)
