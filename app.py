"""Streamlit 진입점.

담당: 이승주
상태: 구현 전 파일 뼈대. 세부 구현 항목은 Notion 구조 문서를 참고한다.
공용 입출력과 함수 규격은 사용하는 담당자와 합의한 뒤 추가한다.
"""

import json
from pathlib import Path

import streamlit as st

from src.config import load_settings
from src.contracts import PipelineRequest
from src.demo import create_demo_pipeline
from src.interface.adapter import (
    run_record_to_places,
    run_record_to_view,
    to_place_result,
    to_view_response,
)
from src.interface.chat import render_response
from src.interface.inspection import render_inspection
from src.interface.map import render_places

# [임시] 예시(합성) 응답을 읽는다.
SAMPLE_PATH = (
    Path(__file__).parent / "tests" / "fixtures" / "interface" / "sample_responses.json"
)
PLACE_SAMPLE_PATH = (
    Path(__file__).parent / "tests" / "fixtures" / "interface" / "sample_places.json"
)


def load_samples(path: Path = SAMPLE_PATH) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {key: value for key, value in data.items() if not key.startswith("_")}


samples = load_samples()
place_samples = load_samples(PLACE_SAMPLE_PATH)


# 색인 안내 문구
INDEX_COMMAND = (
    "uv run --locked python -m scripts.index --documents tests/fixtures/handoff_documents.json "
    "--output data/indexes/demo.json --demo --dimensions 128"
)


# 합성 데모 파이프라인 생성 함수
@st.cache_resource
def load_pipeline():
    root = Path(__file__).parent
    settings = load_settings(root / "configs" / "demo.json", project_root=root)
    return create_demo_pipeline(settings)


FAVICON_PATH = Path(__file__).parent / ".streamlit" / "favicon.png"

st.set_page_config(page_title="분리당", page_icon=str(FAVICON_PATH), layout="wide")
st.title("분리당 -- 서울시 분리배출 안내 시스템")


user_tab, inspection_tab, comparison_tab = st.tabs(
    ["사용자 화면", "검증 패널", "비교 패널"]
)


with user_tab:
    mode = st.radio("응답 방식", ["예시 응답", "실행(합성 데모)"], horizontal=True)
    district = st.selectbox("지역", ["서대문구", "송파구"])
    question = st.text_input("질문")

    if mode == "예시 응답":
        sample_name = st.selectbox("예시 응답 고르기 (합성)", list(samples))
        st.caption("지금은 입력한 구와 질문에 상관없이 선택한 예시가 표현됩니다.")
    else:
        st.caption("합성 문서만 검색하는 데모 실행입니다. 실제 RAG 품질이 아닙니다.")

    if st.button("질문하기"):
        # 새 요청이 실패하거나 비어도 이전 응답이 남아 보이지 않게 지운다.
        for key in ("view", "places", "asked_question", "asked_district", "asked_mode"):
            st.session_state.pop(key, None)
        if mode == "예시 응답":
            st.session_state["view"] = to_view_response(
                samples[sample_name], kind="fixture"
            )
            st.session_state["asked_question"] = question
            st.session_state["asked_district"] = district
            st.session_state["asked_mode"] = mode
        elif not question.strip():
            st.warning("질문을 입력하세요.")
        else:
            try:
                record = load_pipeline().run(
                    PipelineRequest(question=question, district=district)
                )
            except (FileNotFoundError, ValueError):
                st.error(
                    f"데모 색인을 불러오지 못했습니다. 먼저 색인을 만드세요: {INDEX_COMMAND}"
                )
            else:
                st.session_state["view"] = run_record_to_view(record)
                st.session_state["places"] = run_record_to_places(record)
                st.session_state["asked_question"] = question
                st.session_state["asked_district"] = district
                st.session_state["asked_mode"] = mode

    view = st.session_state.get("view")
    # 응답 방식을 바꾸면 다른 방식으로 만든 이전 응답은 보이지 않게 한다.
    if view is not None and st.session_state.get("asked_mode") == mode:
        # 입력창이 아니라 제출 당시의 질문·지역으로 그린다.
        render_response(
            view,
            question=st.session_state.get("asked_question", ""),
            district=st.session_state.get("asked_district", ""),
        )

    st.divider()
    st.subheader("장소")
    if mode == "예시 응답":
        place_name = st.selectbox("예시 장소 고르기 (합성)", list(place_samples))
        render_places(to_place_result(place_samples[place_name], kind="fixture"))
    elif "places" in st.session_state:
        render_places(st.session_state["places"])


with inspection_tab:
    render_inspection(
        st.session_state.get("view"), st.session_state.get("asked_district")
    )


with comparison_tab:
    st.info("나중에 구현합니다~~~~~")
