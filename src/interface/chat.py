"""질문과 답변 화면.

담당: 이승주
상태: 구현 전 파일 뼈대. 세부 구현 항목은 Notion 구조 문서를 참고한다.
공용 입출력과 함수 규격은 사용하는 담당자와 합의한 뒤 추가한다.
"""


import streamlit as st

from src.interface.adapter import ViewResponse


REQUIRED_FIELD_LABELS = {
    'district': '지역(구)',
    'dong': '지역(동)',
    'housing_type': '주택 유형',
    'item': '품목'
}


def build_followup_request(
    question: str, district: str, extra_conditions: dict[str, str]
) -> dict:

    # 조건
    conditions = {
        key: value.strip() for key, value in extra_conditions.items() if value.strip()
    }
    return {'question': question, 'district': district, 'conditions': conditions}


# 링크는 특정 접두사로 시작해야만 한다. (아무거나 링크되지 않도록 방어)
def is_safe_url(url: str | None) -> bool:

    # 우선 값이 있는지 확인하고 접두사 튜플을 받아 구분
    return bool(url) and url.startswith(('https://', 'http://'))


def render_response(view: ViewResponse, question: str = '', district: str = '') -> None:

    if view.kind == 'fixture':
        st.caption('예시(합성) 응답입니다. 실제 RAG 실행이 아닙니다. ')

    if view.status == 'answered':
        _render_answered(view)

    elif view.status == 'needs_clarification':
        _render_clarification(view, question, district)

    elif view.status == 'insufficient_evidence':
        _render_insufficient_evidence(view)

    elif view.status == 'error':
        _render_error()

    else:
        raise ValueError(f'알 수 없는 상태: {view.status!r}')


def _render_answered(view: ViewResponse) -> None:

    st.success(view.answer or '(답변 내용 없음)')
    st.markdown('근거')

    if not view.citations:
        st.warning('인용된 근거가 없습니다.')
        return 
    
    for citation in view.citations:
        if is_safe_url(citation.source_url):
            st.markdown(f'- [{citation.chunk_id}]({citation.source_url})')
        else:
            st.markdown(f'- {citation.chunk_id} (원문 링크 없음)')


def _render_clarification(view: ViewResponse, question: str, district: str) -> None:

    st.warning('질문하신 내용은 추가 정보가 필요합니다.')

    with st.form('followup'):
        extra_conditions = {
            field: st.text_input(REQUIRED_FIELD_LABELS.get(field, field), key=field) for field in view.required_fields
        }

        submitted = st.form_submit_button('다시 질문하기')

    if submitted:
        request = build_followup_request(question, district, extra_conditions)
        st.caption('다시 보낼 요청입니다. 실제 전송이 아닌 예시입니다.')
        st.json(request)


def _render_insufficient_evidence(view: ViewResponse) -> None:

    st.info('질문하신 내용은 답변이 어렵습니다.')


def _render_error() -> None:

    # 사용자 화면 오류: 오류 원문은 사용자 화면이 아닌 검증 패널에서만 확인
    st.error('처리 중 오류가 발생했습니다. 다시 시도해주세요.')