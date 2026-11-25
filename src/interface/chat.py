import streamlit as st

from src.interface.adapter import Citation, ViewResponse

REQUIRED_FIELD_LABELS = {
    "district": "지역(구)",
    "dong": "지역(동)",
    "housing_type": "주택 유형",
    "item": "품목",
}


def build_followup_request(
    question: str, district: str, extra_conditions: dict[str, str]
) -> dict:

    # 조건
    conditions = {
        key: value.strip() for key, value in extra_conditions.items() if value.strip()
    }
    return {"question": question, "district": district, "conditions": conditions}


# 링크는 특정 접두사로 시작해야만 한다. (아무거나 링크되지 않도록 방어)
def is_safe_url(url: str | None) -> bool:

    # 우선 값이 있는지 확인하고 접두사 튜플을 받아 구분
    return bool(url) and url.startswith(("https://", "http://"))


# 인용을 명확히 전달하기 위한 포매팅
def format_citation(citation: Citation) -> str:

    # 제목에 대괄호가 있어도 마크다운 링크가 깨지지 않게 막는다.
    label = (
        (citation.title or citation.chunk_id).replace("[", "\\[").replace("]", "\\]")
    )
    if is_safe_url(citation.source_url):
        line = f"- [{label}]({citation.source_url})"
    else:
        line = f"- {label} (원문 링크 없음)"
    if citation.source_location:
        line += f" · 위치: {citation.source_location}"
    if citation.document_version:
        line += f" · 문서 버전: {citation.document_version}"
    return line


def render_response(view: ViewResponse, question: str = "", district: str = "") -> None:

    if view.kind == "fixture":
        st.caption("예시(합성) 응답입니다. 실제 RAG 실행이 아닙니다.")
    elif view.kind == "demo":
        st.caption(
            "합성 데모 실행입니다. 합성 문서만 검색하며 실제 RAG 품질이 아닙니다."
        )

    elif view.kind == "fixed_evidence":
        st.caption("고정 근거 평가 실행입니다. 검색을 거친 결과가 아닙니다.")

    if view.status == "answered":
        _render_answered(view)

    elif view.status == "needs_clarification":
        _render_clarification(view, question, district)

    elif view.status == "insufficient_evidence":
        _render_insufficient_evidence(view)

    elif view.status == "error":
        _render_error()

    else:
        raise ValueError(f"알 수 없는 상태: {view.status!r}")


def _render_answered(view: ViewResponse) -> None:

    st.success(view.answer or "(답변 내용 없음)")
    st.markdown("근거")

    if not view.citations:
        st.warning("인용된 근거가 없습니다.")
        return

    for citation in view.citations:
        st.markdown(format_citation(citation))


def _render_clarification(view: ViewResponse, question: str, district: str) -> None:

    st.warning(view.answer or "질문하신 내용은 추가 정보가 필요합니다.")

    with st.form("followup"):
        extra_conditions = {
            field: st.text_input(REQUIRED_FIELD_LABELS.get(field, field), key=field)
            for field in view.required_fields
        }

        submitted = st.form_submit_button("다시 질문하기")

    if submitted:
        request = build_followup_request(question, district, extra_conditions)
        st.caption("다시 보낼 요청입니다. 실제 전송이 아닌 예시입니다.")
        st.json(request)


def _render_insufficient_evidence(view: ViewResponse) -> None:

    st.info("질문하신 내용은 답변이 어렵습니다.")

    # 근거는 찾았지만 답을 하나로 정할 수 없는 경우(출처끼리 내용이 다름)에는
    # 안내 문장과 출처를 함께 보여 준다. 근거가 없으면 위 안내 한 줄만 보인다.
    if view.citations:
        for line in (view.answer or "").splitlines():
            if line.strip():
                st.write(line)
        st.markdown("확인한 출처")
        for citation in view.citations:
            st.markdown(format_citation(citation))


def _render_error() -> None:

    # 사용자 화면 오류: 오류 원문은 사용자 화면이 아닌 검증 패널에서만 확인
    st.error("처리 중 오류가 발생했습니다. 다시 시도해주세요.")
