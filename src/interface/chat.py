from collections.abc import Callable

import streamlit as st

from src.interface.adapter import Citation, ViewResponse

# 실패해도 응답 상태와 answer를 바꾸지 않고 문서 답변을 이어 가는 단계(docs/ERRORS.md)
RECOVERABLE_STAGES = {"rewrite", "place_lookup"}

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
    # 구·동은 요청의 최상위 필드이므로 그 자리에 넣는다.
    request: dict = {"question": question, "district": district}
    if "dong" in conditions:
        request["dong"] = conditions.pop("dong")
    if "district" in conditions:
        # 되묻기에서 사용자가 구를 직접 입력했다. 해석기가 같은 되묻기를 되풀이하지 않도록
        # 확정 표시를 전용 필드로 보낸다(조건에 섞으면 생성기 입력과 W5 검증에 샌다).
        request["district"] = conditions.pop("district")
        request["district_confirmed"] = True
    request["conditions"] = conditions
    return request


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


def render_response(
    view: ViewResponse,
    question: str = "",
    district: str = "",
    on_followup: Callable[[dict], None] | None = None,
) -> None:
    # on_followup: 되묻기에 답하면 만든 요청을 실제로 보내는 함수. 없으면(예시 응답) 요청을 보여 주기만 한다.

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
        _render_clarification(view, question, district, on_followup)

    elif view.status == "insufficient_evidence":
        _render_insufficient_evidence(view)

    elif view.status == "error":
        _render_error(view)

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


def _render_clarification(
    view: ViewResponse,
    question: str,
    district: str,
    on_followup: Callable[[dict], None] | None,
) -> None:

    st.warning(view.answer or "질문하신 내용은 추가 정보가 필요합니다.")

    with st.form("followup"):
        extra_conditions = {
            field: st.text_input(
                REQUIRED_FIELD_LABELS.get(field, field), key=f"followup:{field}"
            )
            for field in view.required_fields
        }

        submitted = st.form_submit_button("다시 질문하기")

    if submitted:
        request = build_followup_request(question, district, extra_conditions)
        if on_followup is not None:
            on_followup(request)
        else:
            st.caption("다시 보낼 요청입니다. 실제 전송이 아닌 예시입니다.")
            st.json(request)


def _render_insufficient_evidence(view: ViewResponse) -> None:

    st.info("질문하신 내용은 답변이 어렵습니다.")

    # 근거는 찾았지만 답을 하나로 정할 수 없는 경우(출처끼리 내용이 다름)에는
    # 안내 문장과 출처를 함께 보여 준다. 근거가 없으면 위 안내 한 줄만 보인다.
    for line in (view.answer or "").splitlines():
        if line.strip():
            st.write(line)
    if view.citations:
        st.markdown("확인한 출처")
        for citation in view.citations:
            st.markdown(format_citation(citation))


def _render_error(view: ViewResponse) -> None:

    # 사용자 화면 오류: 파이프라인이 정리해 준 안내문(answer)을 보여 준다.
    # 오류 원문(view.error)은 사용자 화면이 아닌 검증 패널에서만 확인한다.
    # 기록 저장만 실패하면 파이프라인이 상태만 error로 바꾸고 answer는 성공한 답을 그대로 둔다.
    # 그 답을 오류 상자에 보여 주지 않는다. 복구되는 단계(질문 다듬기·장소 조회)의 실패는 상태를
    # 바꾸지 않으므로 판단 근거가 아니다. 그 밖의 단계도 실패했다면 그 안내문(answer)이 이미 들어 있다.
    # 오류 코드는 일반 예외끼리 같은 값(common.unexpected_error)일 수 있어 단계를 구분하지 못한다.
    primary_failed = any(
        e.name not in RECOVERABLE_STAGES | {"record"} for e in view.stage_errors
    )
    only_record_failed = (
        any(e.name == "record" for e in view.stage_errors) and not primary_failed
    )
    st.error(
        (None if only_record_failed else view.answer)
        or "처리 중 오류가 발생했습니다. 다시 시도해주세요."
    )
