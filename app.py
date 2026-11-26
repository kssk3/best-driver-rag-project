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
from src.interface.theme import (
    HERO_HTML,
    HERO_IMAGE,
    SECTIONS_HTML,
    brand_html,
    inject_theme,
)

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
DISTRICTS = ["서대문구", "송파구"]
EXAMPLES = ["페트병 라벨은?", "기름 묻은 피자박스", "폐건전지 어디에?"]
MODES = ["예시 응답", "실행(합성 데모)"]  # 일반 화면은 항상 뒤의 합성 데모 실행


def ask(question, district, mode, sample_name=None) -> bool:
    """질문을 처리해 결과를 session_state에 저장한다. 저장했으면 True."""
    # 새 요청이 실패하거나 비어도 이전 응답이 남아 보이지 않게 지운다.
    for key in ("view", "places", "asked_question", "asked_district", "asked_mode"):
        st.session_state.pop(key, None)
    # 이전 되묻기에서 입력한 값이 다음 되묻기에 미리 채워지지 않게 한다.
    for key in [k for k in st.session_state if k.startswith("followup:")]:
        del st.session_state[key]

    if mode == MODES[0]:
        st.session_state["view"] = to_view_response(
            samples[sample_name], kind="fixture"
        )
    elif not question.strip():
        st.warning("질문을 입력하세요.")
        return False
    else:
        try:
            record = load_pipeline().run(
                PipelineRequest(question=question, district=district)
            )
        except (FileNotFoundError, ValueError):
            if st.session_state["dev"]:
                st.error(
                    f"데모 색인을 불러오지 못했습니다. 먼저 색인을 만드세요: {INDEX_COMMAND}"
                )
            else:
                st.error("지금은 답변을 준비하지 못했습니다. 잠시 후 다시 시도하세요.")
            return False
        st.session_state["view"] = run_record_to_view(record)
        st.session_state["places"] = run_record_to_places(record)

    st.session_state["asked_question"] = question
    st.session_state["asked_district"] = district
    st.session_state["asked_mode"] = mode
    return True


def current_view(mode):
    # 응답 방식을 바꾸면 다른 방식으로 만든 이전 응답은 숨긴다.
    if st.session_state.get("asked_mode") != mode:
        return None
    return st.session_state.get("view")


def search_bar() -> None:
    with st.form("search", border=False):
        text_col, button_col = st.columns([5, 1])
        question = text_col.text_input(
            "질문",
            key="question",
            placeholder="예) 기름 묻은 피자박스는 어디에 버려요?",
            label_visibility="collapsed",
        )
        submitted = button_col.form_submit_button("물어보기")
    district = st.pills(
        "지역",
        DISTRICTS,
        default=DISTRICTS[0],
        key="pick_district",
        label_visibility="collapsed",
    )
    if submitted:
        if not district:
            st.warning("지역을 선택하세요.")
        elif ask(question, district, MODES[1]):
            st.rerun()  # 랜딩에서 결과 화면으로 바꿔 그린다


def toggle_dev() -> None:
    st.session_state["dev"] = not st.session_state["dev"]


def render_header() -> None:
    left, right = st.columns([6, 1], vertical_alignment="center")
    left.html(brand_html())
    right.button(
        "개발자 모드 ON" if st.session_state["dev"] else "개발자 모드",
        key="dev_btn",
        on_click=toggle_dev,
    )


def render_landing() -> None:
    copy_col, image_col = st.columns([21, 19], vertical_alignment="center")
    with copy_col:
        st.html(HERO_HTML)
        search_bar()
        with st.container(key="examples"):
            for index, (col, text) in enumerate(
                zip(st.columns(len(EXAMPLES)), EXAMPLES)
            ):
                if col.button(text, key=f"example_{index}"):
                    district = st.session_state.get("pick_district")
                    if not district:
                        st.warning("지역을 선택하세요.")
                    elif ask(text, district, MODES[1]):
                        st.rerun()
    image_col.image(str(HERO_IMAGE))
    st.html(SECTIONS_HTML)


def render_result(view) -> None:
    answer_col, place_col = st.columns([5, 3])
    with answer_col:
        if view is None:
            st.info("질문하면 결과가 여기에 나옵니다.")
        else:
            # 입력창이 아니라 제출 당시의 질문·지역으로 그린다.
            render_response(
                view,
                question=st.session_state.get("asked_question", ""),
                district=st.session_state.get("asked_district", ""),
            )
    with place_col:
        st.subheader("장소")
        if "places" in st.session_state:
            render_places(st.session_state["places"])


def render_dev() -> None:
    st.html(
        '<div class="devbar"><b>개발자 모드</b> 예시 응답, 검증 패널, 비교 패널은 여기서만 보입니다.</div>'
    )
    preview_tab, inspection_tab, comparison_tab = st.tabs(
        ["사용자 화면 미리보기", "검증 패널", "비교 패널"]
    )

    # 아래 미리보기 탭은 예전 사용자 화면을 그대로 옮긴 것이다.
    with preview_tab:
        mode = st.radio("응답 방식", MODES, horizontal=True)
        district = st.selectbox("지역", DISTRICTS)
        question = st.text_input("질문")

        if mode == MODES[0]:
            sample_name = st.selectbox("예시 응답 고르기 (합성)", list(samples))
            st.caption("지금은 입력한 구와 질문에 상관없이 선택한 예시가 표현됩니다.")
        else:
            sample_name = None
            st.caption(
                "합성 문서만 검색하는 데모 실행입니다. 실제 RAG 품질이 아닙니다."
            )

        if st.button("질문하기"):
            ask(question, district, mode, sample_name)

        view = current_view(mode)
        if view is not None:
            render_response(
                view,
                question=st.session_state.get("asked_question", ""),
                district=st.session_state.get("asked_district", ""),
            )

        st.divider()
        st.subheader("장소")
        if mode == MODES[0]:
            place_name = st.selectbox("예시 장소 고르기 (합성)", list(place_samples))
            render_places(to_place_result(place_samples[place_name], kind="fixture"))
        elif "places" in st.session_state:
            render_places(st.session_state["places"])

    with inspection_tab:
        render_inspection(view, st.session_state.get("asked_district"))

    with comparison_tab:
        st.info("나중에 구현합니다~~~~~")


st.set_page_config(
    page_title="분리당",
    page_icon=str(FAVICON_PATH),
    layout="wide",
    initial_sidebar_state="collapsed",
)
inject_theme()

if "dev" not in st.session_state:
    st.session_state["dev"] = st.query_params.get("dev") == "1"

render_header()
if st.session_state["dev"]:
    render_dev()
else:
    view = current_view(MODES[1])
    if view is None:
        render_landing()
    else:
        search_bar()
        render_result(current_view(MODES[1]))
