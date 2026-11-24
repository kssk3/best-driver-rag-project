"""질문과 답변 화면.

담당: 이승주
상태: 구현 전 파일 뼈대. 세부 구현 항목은 Notion 구조 문서를 참고한다.
공용 입출력과 함수 규격은 사용하는 담당자와 합의한 뒤 추가한다.
"""


import streamlit as st

from src.interface.adapter import ViewResponse


def render_response(view: ViewResponse) -> None:
    if view.kind == 'fixture':
        st.caption('예시(합성) 응답입니다. 실제 RAG 실행이 아닙니다.')
    st.markdown(f'상태: {view.status}')
    if view.answer:
        st.write(view.answer)