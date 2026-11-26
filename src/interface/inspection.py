"""관찰 검증 패널.

담당: 이승주
화면에 보인 답변이 어떤 근거에서 나왔는지, 이상한 점은 없는지 확인하는 개발자용 화면이다.
사용자 화면과 달리 오류 원문도 여기서는 보여 준다.
"""

import pandas as pd
import streamlit as st

from src.interface.adapter import Candidate, ViewResponse
from src.validation import check_response, rank_shifts, stage_names, unchecked_rules


def _used_in_model_input(view: ViewResponse, chunk_id: str) -> str:
    if view.model_inputs is None:
        return "알 수 없음"
    return "예" if chunk_id in view.model_inputs else "아니오"


def _district_text(candidate: Candidate) -> str:
    # 공통 범위는 구 목록이 비어 있어도 "알 수 없음"이 아니다.
    if candidate.district:
        return candidate.district
    return "공통" if candidate.scope_type == "common" else "알 수 없음"


def _shift_text(shift: int | None) -> str:
    if shift is None:
        return "-"
    return f"+{shift}" if shift > 0 else str(shift)


def _shift_color(text: str) -> str:
    # +는 최종에서 올라간 것(파랑), -는 내려간 것(빨강)이다.
    if text.startswith("+"):
        return "color: #1d6fd6; font-weight: 700"
    if text.startswith("-") and text != "-":
        return "color: #d63a3a; font-weight: 700"
    return ""


def render_inspection(
    view: ViewResponse | None, selected_district: str | None = None
) -> None:

    if view is None:
        st.info("사용자 화면에서 먼저 질문하세요.")
        return

    if view.kind == "fixture":
        st.caption("예시(합성) 응답을 검사합니다. 실제 RAG 실행이 아닙니다.")
    elif view.kind == "demo":
        st.caption("합성 데모 실행을 검사합니다. 실제 RAG 품질이 아닙니다.")
    elif view.kind == "fixed_evidence":
        st.caption("고정 근거 평가 실행을 검사합니다. 검색을 거친 결과가 아닙니다.")

    with st.container(key="insp_alerts"):
        st.subheader("자동 경고")
        alerts = check_response(view, selected_district)
        unchecked = unchecked_rules(view, selected_district)

        # 검사하지 못한 규칙이 있으면 "경고 없음"이라고 하지 않는다.
        if not alerts and not unchecked:
            st.success("경고 없음")

        for alert in alerts:
            show = st.error if alert.level == "error" else st.warning
            show(f"[{alert.code}] {alert.message}")

        # 정보가 없어 검사하지 못한 규칙은 '경고 없음'과 구별해 알려 준다.
        for rule in unchecked:
            st.info(f"검사하지 못한 규칙: {rule}")

    with st.container(key="insp_rank"):
        st.subheader("후보 순위")

        if view.candidates:
            cited_ids = {c.chunk_id for c in view.citations}

            # 단계 점수가 하나라도 있으면 그 단계의 순위와 최종 순위를 비교할 수 있다.
            stages = stage_names(view.candidates)
            shifts: dict[str, int] = {}
            if len(stages) >= 2:
                # 비교할 단계는 드롭다운 대신 칩으로 고른다(다시 눌러 해제하면 첫 단계).
                stage = (
                    st.pills(
                        "순위 이동 비교",
                        stages,
                        default=stages[0],
                        key="shift_stage",
                        format_func=str.upper,
                        label_visibility="collapsed",
                    )
                    or stages[0]
                )
                shifts = rank_shifts(view.candidates, stage)
            elif len(stages) == 1:
                shifts = rank_shifts(view.candidates, stages[0])

            table = pd.DataFrame(
                [
                    {
                        "순위": c.rank if c.rank is not None else position,
                        "chunk_id": c.chunk_id,
                        "지역": _district_text(c),
                        "점수": c.score,
                        "모델": _used_in_model_input(view, c.chunk_id),
                        "인용": "예" if c.chunk_id in cited_ids else "아니오",
                        "순위 이동": _shift_text(shifts.get(c.chunk_id)),
                    }
                    for position, c in enumerate(view.candidates, 1)
                ]
            )
            # 열 제목까지 가운데로 맞추려고 HTML 표로 그린다(CSS가 chunk_id만 왼쪽 정렬).
            styled = (
                table.style.hide(axis="index")
                .map(_shift_color, subset=["순위 이동"])
                .format({"점수": "{:g}"})
                .set_table_attributes('class="rank-table"')
            )
            st.html(styled.to_html())

            if not stages:
                st.caption("검색 단계 점수가 없어 순위 이동을 계산할 수 없습니다.")
            elif len(stages) == 1:
                st.caption(
                    f"단계 점수가 하나라 그 단계({stages[0]})와 최종 순위를 비교했습니다."
                )

        else:
            st.info("검색 후보가 없습니다.")
