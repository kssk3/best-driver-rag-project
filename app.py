"""Streamlit 진입점.

담당: 이승주
상태: 구현 전 파일 뼈대. 세부 구현 항목은 Notion 구조 문서를 참고한다.
공용 입출력과 함수 규격은 사용하는 담당자와 합의한 뒤 추가한다.
"""


import json
from pathlib import Path

import streamlit as st

from src.interface.adapter import to_view_response
from src.interface.chat import render_response


# [임시] 예시(합성) 응답을 읽는다. 
SAMPLE_PATH = Path(__file__).parent / 'tests' / 'fixtures' / 'sample_responses.json'


def load_samples() -> dict:
    data = json.loads(SAMPLE_PATH.read_text(encoding='utf-8'))
    return {key: value for key, value in data.items() if not key.startswith('_')}


samples = load_samples()


FAVICON_PATH = Path(__file__).parent / '.streamlit' / 'favicon.png'

st.set_page_config(page_title='분리당', page_icon=str(FAVICON_PATH), layout='wide')
st.title('분리당 -- 서울시 분리배출 안내 시스템')


user_tab, inspection_tab, comparison_tab = st.tabs(['사용자 화면', '검증 패널', '비교 패널'])


with user_tab:
    district = st.selectbox('지역', ['서대문구', '송파구'])
    question = st.text_input('질문')
    sample_name = st.selectbox('예시 응답 고르기 (합성)', list(samples))
    st.caption('지금은 입력한 구와 질문에 상관없이 선택한 예시가 표현됩니다.')
    if st.button('질문하기'):
        render_response(to_view_response(samples[sample_name], kind='fixture'))


with inspection_tab:
    st.info('나중에 구현합니다~~~')


with comparison_tab:
    st.info('나중에 구현합니다~~~')