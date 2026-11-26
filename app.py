"""Streamlit 진입점.

담당: 이승주
상태: 구현 전 파일 뼈대. 세부 구현 항목은 Notion 구조 문서를 참고한다.
공용 입출력과 함수 규격은 사용하는 담당자와 합의한 뒤 추가한다.
"""

from os import getenv
from pathlib import Path

import streamlit as st

from src.common.env import MissingEnvironmentError
from src.config import RuntimeSettings, load_settings
from src.contracts import PipelineRequest
from src.demo import create_demo_pipeline
from src.evaluation.answer_experiments.answer_evaluation_runtimes import (
    MissingEvaluationModelError,
    create_a_catalog_runtime,
)
from src.interface import langfuse_scores
from src.interface.adapter import (
    run_record_to_places,
    run_record_to_view,
)
from src.interface.chat import render_response
from src.interface.comparison import format_summary
from src.interface.inspection import render_inspection
from src.interface.map import render_places
from src.interface.theme import (
    FOOTER_HTML,
    HERO_HTML,
    HERO_IMAGE,
    SECTIONS_HTML,
    brand_html,
    inject_theme,
)
from src.pipeline import PipelineConfigurationError
from src.rewrite_dictionary import catalog

# 색인 안내 문구
INDEX_COMMAND = (
    "uv run --locked python -m scripts.index --documents tests/fixtures/handoff_documents.json "
    "--output data/indexes/demo.json --demo --dimensions 128"
)


PROJECT_ROOT = Path(__file__).resolve().parent
TEAM_INDEX_MODE = "실행"
TEAM_SETTINGS_PATH = getenv("RAG_CHAT_SETTINGS", "").strip()


class TeamSettingsFileError(ValueError):
    """팀 실행 설정 파일을 읽거나 해석할 수 없는 경우."""


class TeamResourceChangedError(RuntimeError):
    """런타임을 가져오는 도중 팀 색인이나 품목 사전이 갱신된 경우."""


type FileVersion = tuple[int, int, int, int, int]
type TeamFileVersions = tuple[FileVersion | None, FileVersion | None]


def _file_version(path: Path) -> FileVersion | None:
    try:
        info = path.stat()
    except OSError:
        # 실제 로더가 파일과 실행 설정 오류를 구분해서 보고한다.
        return None
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _team_file_versions(settings: RuntimeSettings) -> TeamFileVersions:
    return (
        _file_version(settings.index_path),
        _file_version(catalog.CATALOG_PATH)
        if settings.pipeline.rewrite_enabled
        else None,
    )


def read_team_settings(path: str) -> RuntimeSettings:
    try:
        return load_settings(PROJECT_ROOT / path, project_root=PROJECT_ROOT)
    except (OSError, ValueError) as error:
        raise TeamSettingsFileError(
            "팀 실행 설정 파일을 불러오지 못했습니다."
        ) from error


@st.cache_resource(
    max_entries=2, hash_funcs={RuntimeSettings: RuntimeSettings.model_dump_json}
)
def _build_pipeline(
    team_settings: RuntimeSettings | None = None,
    file_versions: TeamFileVersions | None = None,
):
    if team_settings is not None:
        pipeline = create_a_catalog_runtime(team_settings)
        # 로드 중에 파일이 교체되면 이전 키로 새 결과를 캐시하지 않는다.
        if _team_file_versions(team_settings) != file_versions:
            raise TeamResourceChangedError
        return pipeline
    settings = load_settings(
        PROJECT_ROOT / "configs" / "demo.json", project_root=PROJECT_ROOT
    )
    return create_demo_pipeline(settings)


def load_pipeline(team_settings: RuntimeSettings | None = None):
    if team_settings is None:
        return _build_pipeline()
    file_versions = _team_file_versions(team_settings)
    pipeline = _build_pipeline(team_settings, file_versions)
    # 캐시를 재사용할 때도 조회 중 교체된 파일이 있는지 확인한다.
    if _team_file_versions(team_settings) != file_versions:
        raise TeamResourceChangedError
    return pipeline


# 실행 모드에서 파이프라인을 돌려 결과를 session_state에 둔다. 실패하면 안내를 보이고 False.
def ask_pipeline(mode: str, request: PipelineRequest) -> bool:
    try:
        team_settings = (
            read_team_settings(TEAM_SETTINGS_PATH) if mode == TEAM_INDEX_MODE else None
        )
        record = load_pipeline(team_settings).run(request)
    except TeamSettingsFileError:
        st.error(
            "팀 실행 설정 파일을 불러오지 못했습니다. RAG_CHAT_SETTINGS 경로와 JSON 설정값을 확인하세요."
        )
    except MissingEvaluationModelError:
        st.error("실행 설정의 pipeline.versions.model에 답변 모델 ID를 지정하세요.")
    except MissingEnvironmentError:
        st.error("팀 색인 실행에 필요한 OPENAI_API_KEY 환경변수를 설정하세요.")
    except TeamResourceChangedError:
        st.error("팀 색인이나 품목 사전이 갱신되었습니다. 다시 질문하세요.")
    except (OSError, ValueError) as error:
        if mode != TEAM_INDEX_MODE:
            st.error(
                f"데모 색인을 불러오지 못했습니다. 먼저 색인을 만드세요: {INDEX_COMMAND}"
            )
        elif (
            isinstance(error, PipelineConfigurationError)
            and error.code == "evaluation.unsupported_configuration"
        ):
            st.error(
                '팀 색인 모드의 실행 설정에서 pipeline.variant를 "A" 또는 "C"로 지정하세요.'
            )
        elif (
            isinstance(error, PipelineConfigurationError)
            and error.code == "evaluation.missing_reranker_model"
        ):
            st.error(
                "C 검색의 실행 설정에서 pipeline.versions.reranker_model에 재정렬 모델 ID를 지정하세요."
            )
        else:
            st.error(
                "팀 색인을 불러오지 못했습니다. 실행 설정의 index_path와 색인 파일을 확인하세요."
            )
    else:
        st.session_state["view"] = run_record_to_view(record)
        st.session_state["places"] = run_record_to_places(record)
        st.session_state["asked_question"] = request.question
        st.session_state["asked_district"] = request.district or ""
        st.session_state["asked_mode"] = mode
        return True
    return False


FAVICON_PATH = Path(__file__).parent / ".streamlit" / "favicon.png"
DISTRICTS = ["서대문구", "송파구"]
# (칩에 보이는 이름, 실제로 묻는 질문)
EXAMPLES = [
    ("🧴 페트병 라벨", "페트병 라벨은 어떻게 버려요?"),
    ("🍕 피자박스", "기름 묻은 피자박스는 어디에 버려요?"),
    ("🔋 폐건전지", "폐건전지는 어디에 버려요?"),
]
DEMO_MODE = "합성 데모"
# 화면은 팀 실행 설정이 있으면 그 색인으로, 없으면 합성 데모로 답한다.
USER_MODE = TEAM_INDEX_MODE if TEAM_SETTINGS_PATH else DEMO_MODE


def ask(question, district) -> bool:
    """질문을 처리해 결과를 session_state에 저장한다. 저장했으면 True."""
    # 새 요청이 실패하거나 비어도 이전 응답이 남아 보이지 않게 지운다.
    for key in ("view", "places", "asked_question", "asked_district", "asked_mode"):
        st.session_state.pop(key, None)
    # 이전 되묻기에서 입력한 값이 다음 되묻기에 미리 채워지지 않게 한다.
    for key in [k for k in st.session_state if k.startswith("followup:")]:
        del st.session_state[key]

    if not question.strip():
        st.warning("질문을 입력하세요.")
        return False
    with st.spinner("답변을 찾고 있어요..."):  # 실제 검색은 몇 초 걸린다
        return ask_pipeline(
            USER_MODE, PipelineRequest(question=question, district=district)
        )


def send_followup(fields: dict) -> None:
    # 되묻기에 답한 요청을 같은 방식으로 실행한다. 성공하면 새 응답으로 다시 그린다.
    with st.spinner("답변을 찾고 있어요..."):
        sent = ask_pipeline(USER_MODE, PipelineRequest(**fields))
    if sent:
        st.rerun()


def current_view():
    # 응답 방식이 바뀐 뒤에는 다른 방식으로 만든 이전 응답을 숨긴다.
    if st.session_state.get("asked_mode") != USER_MODE:
        return None
    return st.session_state.get("view")


def pick_district():
    return st.pills(
        "지역",
        DISTRICTS,
        default=DISTRICTS[0],
        key="pick_district",
        label_visibility="collapsed",
    )


def search_form(button_label):
    with st.form("search", border=False):
        text_col, button_col = st.columns([4, 1.5])
        question = text_col.text_input(
            "질문",
            key="question",
            placeholder="예) 기름 묻은 피자박스는 어디에 버려요?",
            label_visibility="collapsed",
        )
        return question, button_col.form_submit_button(button_label)


def search_bar(compact=False) -> None:
    if compact:
        # 결과 화면: 지역 pill이 검색창 왼쪽에 한 줄로 붙는다.
        pill_col, form_col = st.columns([1.6, 6], vertical_alignment="center")
        with pill_col:
            district = pick_district()
        with form_col:
            question, submitted = search_form("다시 묻기")
    else:
        question, submitted = search_form("물어보기")
        label_col, pill_col = st.columns([2.2, 4.5], vertical_alignment="center")
        label_col.html('<span class="lbl">어느 지역에 계세요?</span>')
        with pill_col:
            district = pick_district()
    if submitted:
        if not district:
            st.warning("지역을 선택하세요.")
        elif ask(question, district):
            st.rerun()  # 랜딩에서 결과 화면으로 바꿔 그린다


def render_header() -> None:
    st.html(brand_html())


def render_landing() -> None:
    copy_col, image_col = st.columns([21, 19], vertical_alignment="center")
    with copy_col:
        st.html(HERO_HTML)
        search_bar()
        with st.container(key="examples"):
            cols = st.columns(
                [2.2] + [1.5] * len(EXAMPLES), vertical_alignment="center"
            )
            cols[0].html('<span class="lbl">이런 질문이 많아요!</span>')
            for index, (col, (label, question)) in enumerate(zip(cols[1:], EXAMPLES)):
                if col.button(label, key=f"example_{index}"):
                    district = st.session_state.get("pick_district")
                    if not district:
                        st.warning("지역을 선택하세요.")
                    elif ask(question, district):
                        st.rerun()
    image_col.image(str(HERO_IMAGE))
    st.html(SECTIONS_HTML)


def render_result(view) -> None:
    # 입력창이 아니라 제출 당시의 질문·지역으로 그린다.
    render_response(
        view,
        question=st.session_state.get("asked_question", ""),
        district=st.session_state.get("asked_district", ""),
        on_followup=None if view.kind == "fixture" else send_followup,
    )
    # 장소는 답변 아래에 이어서 보인다. 조회할 장소가 없거나 서비스가 아직 연결되지 않았으면
    # (unavailable) 구역 자체를 그리지 않는다.
    places = st.session_state.get("places")
    if places is not None and places.status != "unavailable":
        st.subheader("장소")
        render_places(places)


@st.cache_data(ttl=60, show_spinner=False)
def cached_scores():
    # 질문할 때마다 다시 그려지므로 서버 조회는 잠시 재사용한다.
    return langfuse_scores.load_langfuse_scores()


LANGFUSE_MESSAGES = {
    "not_configured": "Langfuse 주소와 키(LANGFUSE_BASE_URL, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY)를 설정하고 다시 실행하세요.",
    "unreachable": "Langfuse 서버에 연결하지 못했습니다. 주소와 네트워크를 확인하세요.",
}


def render_comparison() -> None:
    st.subheader("답변 근거 충실도")
    st.caption(
        "Langfuse의 faithfulness 점수를 실행 방식(A/B/C)별로 집계합니다. "
        "같은 평가(데이터셋)끼리만 묶고, 방식을 알 수 없는 점수는 평균에서 뺍니다. "
        "검색 적중률(Hit@k)은 다른 지표라 섞지 않습니다. "
        "점수는 판정 모델의 편차가 있어, 같은 답변도 다시 채점하면 달라질 수 있습니다."
    )
    try:
        result = cached_scores()
    except langfuse_scores.LangfuseReadError as error:
        # 주소·키·응답 내용은 보이지 않고 오류 종류만 알려 준다.
        if error.code == "not_configured":
            st.info(LANGFUSE_MESSAGES["not_configured"])  # 설정 안내이지 오류가 아니다.
        else:
            st.error(
                LANGFUSE_MESSAGES.get(
                    error.code, f"Langfuse에서 점수를 읽지 못했습니다. ({error.code})"
                )
            )
        return
    if not result.groups:
        st.info("방식별로 집계할 점수가 아직 없습니다.")
    for group in result.groups:
        st.markdown(
            f"**데이터셋 {group.dataset_id[:8]}** · 최근 실행 {group.latest[:10]}"
        )
        for column, summary in zip(st.columns(len(group.summaries)), group.summaries):
            column.metric(f"방식 {summary.variant}", format_summary(summary))
    if result.unlinked:
        st.caption(f"방식을 알 수 없어 평균에서 뺀 점수 {result.unlinked}건")
    if st.button("새로고침", key="refresh_scores"):
        cached_scores.clear()
        st.rerun()


def render_dev_panel(view) -> None:
    # 내부 데모 전용: 사용자 화면 옆에 항상 보이는 검증·비교 패널.
    with st.container(key="devpanel"):
        inspection_tab, comparison_tab = st.tabs(["검증 패널", "비교 패널"])
        with inspection_tab:
            render_inspection(view, st.session_state.get("asked_district"))
        with comparison_tab:
            render_comparison()


st.set_page_config(
    page_title="분리당",
    page_icon=str(FAVICON_PATH),
    layout="wide",
    initial_sidebar_state="collapsed",
)
inject_theme()

render_header()
view = current_view()
if view is None:
    render_landing()
else:
    search_bar(compact=True)
    view = current_view()  # 검색바에서 새 질문이 실패하면 이전 응답이 지워져 있다
    if view is None:
        st.info("질문하면 결과가 여기에 나옵니다.")
    else:
        render_result(view)
st.html(FOOTER_HTML)
render_dev_panel(view)
