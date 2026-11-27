from collections.abc import Callable, Iterator
from contextlib import contextmanager
from html import escape

import streamlit as st

from src.interface.adapter import Citation, ViewResponse
from src.interface.theme import avatar_html
from src.retrieval.regions import SUPPORTED_DISTRICTS

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
        # 되묻기에서 사용자가 구를 선택 상자에서 골랐다. 해석기가 같은 되묻기를 되풀이하지 않도록
        # 확정 표시를 전용 필드로 보낸다(조건에 섞으면 생성기 입력과 W5 검증에 샌다).
        request["district"] = conditions.pop("district")
        request["district_confirmed"] = True
    request["conditions"] = conditions
    return request


# 링크는 특정 접두사로 시작해야만 한다. (아무거나 링크되지 않도록 방어)
def is_safe_url(url: str | None) -> bool:

    # 우선 값이 있는지 확인하고 접두사 튜플을 받아 구분
    return bool(url) and url.startswith(("https://", "http://"))


# shortcut: 조례 이름을 색인에서 읽지 않고 고정 표로 둔다. 지역이나 문서가 늘면 여기에 추가한다.
PARENT_TITLES = {
    "seodaemun-ordinance": "서대문구 폐기물 관리 조례",
    "seodaemun-rules": "서대문구 폐기물 관리 조례 시행규칙",
    "songpa-ordinance": "송파구 폐기물 관리 조례",
    "songpa-rules": "송파구 폐기물 관리 조례 시행규칙",
}


def _followup_placeholder(field: str) -> str:
    if field == "district":
        return "답변의 기준이 될 지역(구)를 선택해 주세요."
    return f"{REQUIRED_FIELD_LABELS.get(field, field)}을(를) 기재해 주세요."


def _followup_input(container, field: str) -> str:
    label = REQUIRED_FIELD_LABELS.get(field, field)
    key = f"followup:{field}"
    if field == "district":
        # 자유 입력이면 "강남구요"나 "서대문구는 안 돼요"가 구로 들어가므로 지원하는 구만 고르게 한다.
        return (
            container.selectbox(
                label,
                sorted(SUPPORTED_DISTRICTS),
                index=None,
                key=key,
                placeholder=_followup_placeholder(field),
                label_visibility="collapsed",
            )
            or ""
        )
    return container.text_input(
        label,
        key=key,
        placeholder=_followup_placeholder(field),
        label_visibility="collapsed",
    )


def _citation_card(citation: Citation, number: int) -> None:
    """말풍선 안의 인용 한 건. 번호 말머리가 붙은 칩 하나에 제목(링크)만 보인다."""
    label = escape(" ".join((citation.title or citation.chunk_id).split()))
    # 별표는 어느 조례의 것인지 앞에 붙인다(송파구 별표는 제목이 "별표"뿐이다).
    parent = PARENT_TITLES.get(
        (citation.document_id or "").partition(":attachment:")[0]
    )
    if parent and ":attachment:" in (citation.document_id or ""):
        label = f"{escape(parent)} › {label}"
    title = (
        f'<a href="{escape(citation.source_url)}" target="_blank" rel="noopener noreferrer">{label}</a>'
        if is_safe_url(citation.source_url)
        else f"{label} (원문 링크 없음)"
    )
    st.html(
        f'<div class="cite"><b class="cite-no">{number}</b>'
        f'<span class="cite-body">{title}</span></div>'
    )


@contextmanager
def _bubble(label: str, tone: str) -> Iterator[None]:
    """당번이 아바타 옆 말풍선. 안의 st.success/warning/info는 CSS가 말풍선 모양으로 바꾼다."""
    body, avatar = st.columns([14, 1], vertical_alignment="top")
    avatar.html(avatar_html())
    with body, st.container(key="answerbox"):
        st.html(f'<span class="badge {tone}">{label}</span>')
        yield


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

    with _bubble("근거 확인됨", "ok"):
        st.success(view.answer or "(답변 내용 없음)")
        st.html('<div class="ev-label"></div>')  # 답변과 인용 사이 실선

        if not view.citations:
            st.warning("인용된 근거가 없습니다.")
            return

        for number, citation in enumerate(view.citations, 1):
            _citation_card(citation, number)


def _render_clarification(
    view: ViewResponse,
    question: str,
    district: str,
    on_followup: Callable[[dict], None] | None,
) -> None:

    with _bubble("조금만 더 알려주세요", "warn"):
        st.warning(view.answer or "질문하신 내용은 추가 정보가 필요합니다.")

        if not view.required_fields:
            # 더 채울 값이 없다(지원 밖 안내 등). 같은 요청을 다시 보내면 같은 안내만 나오므로
            # 폼 대신 처음 입력칸에서 지역이나 질문을 바꾸도록 안내한다.
            st.caption("위의 지역이나 질문을 바꿔서 다시 질문해 주세요.")
            return

        with st.form("followup"):
            # 라벨은 숨기고 입력칸 안내 문구(placeholder)로 대신한다. 입력칸이 하나면 버튼을 옆에 둔다.
            one_field = len(view.required_fields) == 1
            input_col, button_col = (
                st.columns([5, 1.4], vertical_alignment="center")
                if one_field
                else (st.container(), st.container())
            )
            extra_conditions = {
                field: _followup_input(input_col, field)
                for field in view.required_fields
            }
            submitted = button_col.form_submit_button("다시 질문하기")

        if submitted:
            request = build_followup_request(question, district, extra_conditions)
            if on_followup is not None:
                on_followup(request)
            else:
                st.caption("다시 보낼 요청입니다. 실제 전송이 아닌 예시입니다.")
                st.json(request)


def _render_insufficient_evidence(view: ViewResponse) -> None:

    with _bubble("근거가 부족해요", "warn"):
        st.info("질문하신 내용은 답변이 어렵습니다.")

        # 근거는 찾았지만 답을 하나로 정할 수 없는 경우(출처끼리 내용이 다름)에는
        # 안내 문장과 출처를 함께 보여 준다. 근거가 없으면 위 안내 한 줄만 보인다.
        for line in (view.answer or "").splitlines():
            # 위의 고정 안내와 같은 뜻의 거절 문장은 되풀이하지 않는다.
            if line.strip() and "답변하기 어렵" not in line:
                st.write(line)
        if view.citations:
            st.html('<div class="ev-label"></div>')  # 답변과 출처 사이 실선
            for number, citation in enumerate(view.citations, 1):
                _citation_card(citation, number)


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
