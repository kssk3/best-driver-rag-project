"""UI 독립 공용 검증.

담당: 이승주
화면(streamlit)을 모르는 순수 함수만 둔다. 응답을 받아 사람이 확인할 경고 목록을 돌려준다.
재생성이나 보류 같은 결정은 하지 않는다.
"""


from dataclasses import dataclass
from typing import Literal

from src.interface.adapter import Candidate, ViewResponse


@dataclass(frozen=True)
class Alert:
    code: str
    level: Literal['warning', 'error']
    message: str


# 경고 목록 생성
def check_response(view: ViewResponse, selected_district: str | None=None) -> list[Alert]:

    alerts: list[Alert] = []
    candidate_ids = [c.chunk_id for c in view.candidates]

    # [W1] 답변에 쓰인 근거가 선택한 지역과 다른 지역인지 확인한다.
    if selected_district:
        used = candidate_ids if view.model_inputs is None else view.model_inputs
        mixed = [
            c.chunk_id for c in view.candidates
            if c.chunk_id in used and c.district and c.district != selected_district
        ]
        if mixed:
            alerts.append(Alert(
                'W1', 'warning',
                f'선택한 지역({selected_district})과 다른 지역의 근거가 쓰였습니다.: {', '.join(mixed)}',
            ))

    # [W2] 인용한 근거가 후보와 모델 입력 어디에도 없다.
    known = set(candidate_ids) | set(view.model_inputs or [])
    missing = [c.chunk_id for c in view.citations if c.chunk_id not in known]
    if missing:
        alerts.append(Alert(
            'W2', 'warning', f'후보나 모델 입력에 없는 근거를 인용했습니다.: {', '.join(missing)}'
        ))

    if view.status == 'answered':

        # [W3] 인용 없는 답변
        if not view.citations:
            alerts.append(Alert('W3', 'warning', '답변했지만 인용한 근거가 없습니다.'))

        # [W4] 후보 없는 답변
        if not view.candidates:
            alerts.append(Alert('W4', 'warning', '답변했지만 검색 후보가 없습니다.'))

    # [W5] 입력한 조건과 모델이 받은 근거의 조건이 맞지 않는다.
    mismatch = _condition_mismatch(view)
    if mismatch:
        alerts.append(Alert(
            'W5', 'warning',
            f'입력한 조건({_format_conditions(view.request_conditions)})과 모델이 받은 근거의 조건이 맞지 않습니다.: {', '.join(mismatch)}'
        ))

    # [W6] 추가 정보가 필요하다면서 물어볼 게 없다.
    if view.status == 'needs_clarification' and not view.required_fields:
        alerts.append(Alert('W6', 'warning', '추가 정보가 필요하지만 물어볼 항목이 없습니다.'))

    # [W7] 오류는 정상 거절과 다른 상태이다.
    if view.status == 'error':
        alerts.append(Alert('W7', 'error', f'오류 응답: {view.error or '오류 내용 없음'}'))

    # [W8] 모델이 받은 근거가 화면에 보이는 근거보다 많다.
    if view.model_inputs is not None and len(view.candidates) < len(view.model_inputs):
        alerts.append(Alert(
            'W8', 'warning', f'모델 입력 근거({len(view.model_inputs)}개)가 화면 후보({len(view.candidates)}개)보다 많습니다.'
        ))

    # [W9] 오류 내용이 있는데 상태는 오류가 아니다.
    if view.error and view.status != 'error':
        alerts.append(Alert('W9', 'error', f'오류 내용은 있는데 상태가 {view.status}입니다.: {view.error}'))

    return alerts


def _format_conditions(conditions: dict[str, str]) -> str:
    return ', '.join(f'{key}={value}' for key, value in conditions.items())


# 모델 입력을 모르면(None) 후보 전체를 쓴 것으로 본다. W1과 같은 방식이다.
def _used_candidates(view: ViewResponse) -> list[Candidate]:

    if view.model_inputs is None:
        return list(view.candidates)

    return [c for c in view.candidates if c.chunk_id in view.model_inputs]


# 조건 문자열 안에 입력 값이 들어 있는지만 확인 (조건을 구별하지 않아 오탐 가능성 있음)
def _condition_mismatch(view: ViewResponse) -> list[str]:
    values = [value.strip() for value in view.request_conditions.values() if value.strip()]

    if not values:
        return []

    return [
        c.chunk_id
        for c in _used_candidates(view)
        if c.conditions and not any(value in text for value in values for text in c.conditions)
    ]


# 정보가 없어 검사하지 못한 규칙 처리
def unchecked_rules(view: ViewResponse) -> list[str]:

    rules: list[str] = []
    used = _used_candidates(view)

    if view.request_conditions and used and not any(c.conditions for c in used):
        rules.append('W5(근거에 조건 정보가 없어 입력 조건을 비교하지 못했습니다)')
    return rules


# 후보들이 가진 검색 단계 이름
def stage_names(candidates: list[Candidate]) -> list[str]:

    names: list[str] = []

    for c in candidates:
        for name in c.stage_scores:
            if name not in names:
                names.append(name)
    return names


# 후보들이 가진 검색 단계의 점수만으로 매긴 순위와 최종 순위의 차이 비교
# (값이 없어 비교할 수 없는 경우에는 비교 대상으로 삼지 않는다.)
def rank_shifts(candidates: list[Candidate], stage: str) -> dict[str, int]:

    scored = [(i, c) for i, c in enumerate(candidates) if stage in c.stage_scores]
    before = sorted(scored, key=lambda pair: -pair[1].stage_scores[stage])
    after = sorted(scored, key=lambda pair: (pair[1].rank or pair[0] + 1))
    before_pos = {c.chunk_id: pos for pos, (_, c) in enumerate(before, 1)}
    after_pos = {c.chunk_id: pos for pos, (_, c) in enumerate(after, 1)}

    return {chunk_id: before_pos[chunk_id] - after_pos[chunk_id] for chunk_id in before_pos}
