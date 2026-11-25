"""관찰 검증 패널.

담당: 이승주
화면에 보인 답변이 어떤 근거에서 나왔는지, 이상한 점은 없는지 확인하는 개발자용 화면이다.
사용자 화면과 달리 오류 원문도 여기서는 보여 준다.
"""

import streamlit as st

from src.interface.adapter import ViewResponse
from src.interface.chat import format_citation
from src.validation import check_response, rank_shifts, stage_names, unchecked_rules


def _used_in_model_input(view: ViewResponse, chunk_id: str) -> str:
    if view.model_inputs is None:
        return "알 수 없음"
    return "예" if chunk_id in view.model_inputs else "아니오"


def _shift_text(shift: int | None) -> str:
    if shift is None:
        return "-"
    return f"+{shift}" if shift > 0 else str(shift)


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

    st.subheader("자동 경고")
    alerts = check_response(view, selected_district)

    if not alerts:
        st.success("경고 없음")

    for alert in alerts:
        show = st.error if alert.level == "error" else st.warning
        show(f"[{alert.code}] {alert.message}")

    # 정보가 없어 검사하지 못한 규칙은 '경고 없음'과 구별해 알려 준다.
    for rule in unchecked_rules(view):
        st.info(f"검사하지 못한 규칙: {rule}")

    st.subheader("후보 순위")

    if view.candidates:
        cited_ids = {c.chunk_id for c in view.citations}

        # 단계 점수가 둘 이상일 때만 단계 사이의 순위 이동을 계산할 수 있다.
        stages = stage_names(view.candidates)
        shifts: dict[str, int] = {}
        if len(stages) >= 2:
            stage = st.selectbox("순위 이동 비교", stages)
            shifts = rank_shifts(view.candidates, stage)

        st.dataframe(
            [
                {
                    "순위": c.rank if c.rank is not None else position,
                    "chunk_id": c.chunk_id,
                    "지역": c.district or "알 수 없음",
                    "점수": c.score,
                    "모델": _used_in_model_input(view, c.chunk_id),
                    "인용": "예" if c.chunk_id in cited_ids else "아니오",
                    "순위 이동": _shift_text(shifts.get(c.chunk_id)),
                }
                for position, c in enumerate(view.candidates, 1)
            ]
        )

        if len(stages) < 2:
            st.caption("검색 단계 점수가 하나 이하라 순위 이동을 계산할 수 없습니다.")
        else:
            st.caption("순위 이동은 +가 최종에서 올라간 것, -가 내려간 것입니다.")

    else:
        st.info("검색 후보가 없습니다.")

    st.subheader("모델 입력 근거")

    if view.model_inputs is None:
        st.info("기록이 없어 알 수 없습니다.")
    elif not view.model_inputs:
        st.info("모델에 전달된 근거가 없습니다.")
    else:
        for chunk_id in view.model_inputs:
            st.markdown(f"- {chunk_id}")

    st.subheader("인용")
    if view.citations:
        for citation in view.citations:
            st.markdown(format_citation(citation))
    else:
        st.info("인용이 없습니다.")
