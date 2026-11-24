"""관찰 검증 패널.

담당: 이승주
화면에 보인 답변이 어떤 근거에서 나왔는지, 이상한 점은 없는지 확인하는 개발자용 화면이다.
사용자 화면과 달리 오류 원문도 여기서는 보여 준다.
"""

import streamlit as st

from src.interface.adapter import ViewResponse
from src.interface.chat import format_citation
from src.validation import check_response


def _used_in_model_input(view: ViewResponse, chunk_id: str) -> str:
    if view.model_inputs is None:
        return '알 수 없음'
    return '예' if chunk_id in view.model_inputs else '아니오'


def render_inspection(view: ViewResponse | None, selected_district: str | None=None) -> None:

    if view is None:
        st.info('사용자 화면에서 먼저 질문하세요.')
        return 

    if view.kind == 'fixture':
        st.caption('예시(합성) 응답을 검사합니다. 실제 RAG 실행이 아닙니다.')

    st.subheader('자동 경고')
    alerts = check_response(view, selected_district)

    if not alerts:
        st.success('경고 없음')

    for alert in alerts:
        show = st.error if alert.level == 'error' else st.warning
        show(f'[{alert.code}] {alert.message}')

    st.subheader('후보 순위')

    if view.candidates:
        cited_ids = {c.chunk_id for c in view.citations}

        st.dataframe([
            {
                '순위': rank,
                'chunk_id': c.chunk_id,
                '지역': c.district or '알 수 없음',
                '점수': c.score,
                '모델': _used_in_model_input(view, c.chunk_id),
                '인용': '예' if c.chunk_id in cited_ids else '아니오',
            }
            for rank, c in enumerate(view.candidates, 1)
        ])

        st.caption('순위 이동(재정렬 전후)은 단계별 점수가 연결되는 실제 실행에서 확인합니다.')

    else:
        st.info('검색 후보가 없습니다.')

    st.subheader('모델 입력 근거')

    if view.model_inputs is None:
        st.info('기록이 없어 알 수 없습니다.')
    elif not view.model_inputs:
        st.info('모델에 전달된 근거가 없습니다.')
    else:
        for chunk_id in view.model_inputs:
            st.markdown(f'- {chunk_id}')

    st.subheader('인용')
    if view.citations:
        for citation in view.citations:
            st.markdown(format_citation(citation))
    else: st.info('인용이 없습니다.')