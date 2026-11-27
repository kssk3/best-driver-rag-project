"""Streamlit 진입점."""

import traceback
from html import escape
from os import getenv
from pathlib import Path

import streamlit as st

from src.common.env import MissingEnvironmentError
from src.config import RuntimeSettings, load_settings
from src.contracts import PipelineRequest
from src.evaluation.answer_experiments.answer_evaluation_runtimes import (
    MissingEvaluationModelError,
    create_a_catalog_runtime,
)
from src.interface import langfuse_scores
from src.interface.adapter import (
    run_record_to_view,
)
from src.interface.chat import render_response
from src.interface.inspection import render_inspection
from src.interface.theme import (
    FOOTER_HTML,
    HERO_HTML,
    brand_html,
    hero_html,
    inject_theme,
)
from src.pipeline import PipelineConfigurationError
from src.rewrite_dictionary import catalog

PROJECT_ROOT = Path(__file__).resolve().parent
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
    max_entries=2,
    hash_funcs={RuntimeSettings: RuntimeSettings.model_dump_json},
    show_spinner=False,  # 화면의 '답변을 찾고 있어요...'와 겹쳐 두 번 보이지 않게 한다.
)
def _build_pipeline(team_settings: RuntimeSettings, file_versions: TeamFileVersions):
    pipeline = create_a_catalog_runtime(team_settings)
    # 로드 중에 파일이 교체되면 이전 키로 새 결과를 캐시하지 않는다.
    if _team_file_versions(team_settings) != file_versions:
        raise TeamResourceChangedError
    return pipeline


def load_pipeline(team_settings: RuntimeSettings):
    file_versions = _team_file_versions(team_settings)
    pipeline = _build_pipeline(team_settings, file_versions)
    # 캐시를 재사용할 때도 조회 중 교체된 파일이 있는지 확인한다.
    if _team_file_versions(team_settings) != file_versions:
        raise TeamResourceChangedError
    return pipeline


# 팀 색인으로 파이프라인을 돌려 결과를 session_state에 둔다. 실패하면 안내를 보이고 False.
def ask_pipeline(request: PipelineRequest) -> bool:
    try:
        record = load_pipeline(read_team_settings(TEAM_SETTINGS_PATH)).run(request)
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
        if (
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
            traceback.print_exc()  # 안내문은 뭉뚱그려 보이므로 실제 원인은 서버 로그에 남긴다
            st.error(
                "팀 색인을 불러오지 못했습니다. 실행 설정의 index_path와 색인 파일을 확인하세요."
            )
    else:
        st.session_state["view"] = run_record_to_view(record)
        st.session_state["asked_question"] = request.question
        st.session_state["asked_district"] = request.district or ""
        return True
    return False


FAVICON_PATH = Path(__file__).parent / ".streamlit" / "favicon.png"
DISTRICTS = ["서대문구", "송파구"]
# (칩에 보이는 이름, 실제로 묻는 질문)
EXAMPLES = [
    ("🧴페트병 라벨", "페트병 라벨은 어떻게 버려요?"),
    ("🍕피자박스", "기름 묻은 피자박스는 어디에 버려요?"),
    ("🔋폐건전지", "폐건전지는 어디에 버려요?"),
]
SETTINGS_GUIDE = (
    "실행 설정이 지정되지 않아 질문에 답할 수 없습니다. `RAG_CHAT_SETTINGS`에 실행 설정 파일을 "
    "지정해 화면을 띄우세요. 색인이 없으면 먼저 만들고 C 설정으로 띄우는 한 줄: "
    "`uv run --locked --env-file .env python -m scripts.run_chat` "
    "(또는 `RAG_CHAT_SETTINGS=configs/team-c-rewrite-chat.json uv run --locked --env-file .env streamlit run app.py`). "
    "`.env`의 `OPENAI_API_KEY`가 필요합니다."
)


def ask(question, district) -> bool:
    """질문을 접수한다. 접수했으면 True(호출한 쪽이 st.rerun()으로 결과 화면을 그린다).

    실제 검색은 다음 실행에서 한다. 이 실행에서 바로 검색하면 몇 초 동안 랜딩이 그대로 남기 때문이다.
    """
    # 새 요청이 실패하거나 비어도 이전 응답이 남아 보이지 않게 지운다.
    for key in ("view", "asked_question", "asked_district", "pending"):
        st.session_state.pop(key, None)
    # 이전 되묻기에서 입력한 값이 다음 되묻기에 미리 채워지지 않게 한다.
    for key in [k for k in st.session_state if k.startswith("followup:")]:
        del st.session_state[key]

    if not TEAM_SETTINGS_PATH:
        return False  # 설정 안내는 화면 위에 이미 보이고 있다.
    if not question.strip():
        st.warning("질문을 입력하세요.")
        return False
    st.session_state["pending"] = {"question": question, "district": district}
    return True


def run_pending() -> None:
    """접수한 질문을 실제로 실행한다. 성공하면 결과 화면으로 다시 그린다."""
    pending = st.session_state["pending"]
    with st.spinner("답변을 찾고 있어요..."):  # 실제 검색은 몇 초 걸린다
        done = ask_pipeline(PipelineRequest(**pending))
    # 검색 중에 같은 입력이 한 번 더 들어와(엔터가 두 번 전달되는 경우) 이 실행이 끊기면 여기까지 못 온다.
    # 접수 기록을 먼저 지우면 다음 실행이 랜딩으로 돌아가므로, 끝난 뒤에 지운다.
    st.session_state.pop("pending", None)
    if done:
        st.rerun()


def send_followup(fields: dict) -> None:
    # 되묻기에 답한 요청을 같은 방식으로 실행한다. 성공하면 새 응답으로 다시 그린다.
    with st.spinner("답변을 찾고 있어요..."):
        sent = ask_pipeline(PipelineRequest(**fields))
    if sent:
        # 되묻기에서 다른 구를 확정했을 수 있다. 이미 그려진 드롭다운은 지금 바꿀 수 없어서 다음 실행에서 맞춘다.
        st.session_state["sync_district"] = True
        st.rerun()


def current_view():
    return st.session_state.get("view")


def pick_district():
    return st.pills(
        "지역",
        DISTRICTS,
        key="pick_district",  # 처음에는 아무것도 고르지 않는다(고르지 않고 묻으면 안내)
        label_visibility="collapsed",
    )


def search_form(button_label):
    if "prefill" in st.session_state:
        # 위젯을 그리기 전에만 값을 넣을 수 있다. 예시 칩으로 넘어온 질문을 검색창에 보여 준다.
        st.session_state["question"] = st.session_state.pop("prefill")
    with st.form("search", border=False):
        text_col, button_col = st.columns([4, 1.5])
        question = text_col.text_input(
            "질문",
            key="question",
            placeholder="예) 기름 묻은 피자박스는 어디에 버려요?",
            label_visibility="collapsed",
        )
        return question, button_col.form_submit_button(button_label)


def current_district() -> str:
    pending = st.session_state.get("pending") or {}
    district = pending.get("district") or st.session_state.get("asked_district")
    return district if district in DISTRICTS else DISTRICTS[0]


def search_bar(compact=False) -> None:
    if compact:
        # 대화 화면: 지역은 검색창 왼쪽의 드롭다운이다.
        select_col, form_col = st.columns([1.3, 6], vertical_alignment="center")
        if st.session_state.pop("sync_district", False):
            st.session_state["district_compact"] = current_district()
        district = select_col.selectbox(
            "지역",
            DISTRICTS,
            index=DISTRICTS.index(current_district()),
            key="district_compact",
            label_visibility="collapsed",
        )
        with form_col:
            question, submitted = search_form("다시 묻기")
    else:
        question, submitted = search_form("물어보기")
        with st.container(key="region_row"):  # 라벨과 칩을 한 줄에
            st.html('<span class="lbl">어느 지역에 계세요?</span>')
            district = pick_district()
    if submitted:
        if not district:
            st.warning("지역을 선택하세요.")
        elif ask(question, district):
            st.rerun()  # 랜딩에서 대화 화면으로 바꿔 그린다


def render_header() -> None:
    st.html(brand_html())


def render_landing() -> None:
    copy_col, image_col = st.columns([21, 19], vertical_alignment="center")
    with copy_col:
        st.html(HERO_HTML)
        search_bar()
        with st.container(key="examples"):  # 라벨과 칩을 한 줄에
            st.html('<span class="lbl">이런 질문이 많아요!</span>')
            for index, (label, question) in enumerate(EXAMPLES):
                if st.button(label, key=f"example_{index}"):
                    district = st.session_state.get("pick_district")
                    if not district:
                        st.warning("지역을 선택하세요.")
                    elif ask(question, district):
                        st.session_state["prefill"] = (
                            question  # 대화 화면 검색창에 채운다
                        )
                        st.rerun()
    image_col.html(hero_html())


def render_result(view) -> None:
    # 입력창이 아니라 제출 당시의 질문·지역으로 그린다.
    render_response(
        view,
        question=st.session_state.get("asked_question", ""),
        district=st.session_state.get("asked_district", ""),
        on_followup=None if view.kind == "fixture" else send_followup,
    )


@st.cache_data(ttl=60, show_spinner=False)
def cached_scores():
    # 질문할 때마다 다시 그려지므로 서버 조회는 잠시 재사용한다. 실패(오류 코드)도 같이 재사용해서
    # 서버가 느릴 때 화면을 그릴 때마다 시간 초과를 기다리지 않게 한다.
    try:
        return langfuse_scores.load_langfuse_scores()
    except langfuse_scores.LangfuseReadError as error:
        return error.code


LANGFUSE_MESSAGES = {
    "not_configured": "Langfuse 주소와 키(LANGFUSE_BASE_URL, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY)를 설정하고 다시 실행하세요.",
    "unreachable": "Langfuse 서버에 연결하지 못했습니다. 주소와 네트워크를 확인하세요.",
    "timeout": "Langfuse 서버가 제때 응답하지 않습니다(서버가 바쁜 것 같습니다). 잠시 후 새로고침하세요.",
    "bad_response": "Langfuse 응답이 올바르지 않거나 중간에 끊겼습니다. 잠시 후 새로고침하세요.",
    "too_many_pages": "Langfuse 기록이 너무 많아 일부만 읽을 수 있어 집계하지 않았습니다.",
}


def metrics_html(group) -> str:
    """데이터셋 하나의 RAGAS 4대 지표를 카드 4장으로 그린다(값은 모두 우리 코드가 만든 문자열)."""
    cards = []
    for name, label, english in langfuse_scores.METRICS:
        rows = []
        for item in group.metrics[name]:
            width = 0 if item.mean is None else max(0.0, min(1.0, item.mean)) * 100
            value = "—" if item.mean is None else f"{item.mean:.3f}"
            rows.append(
                f'<div class="mx-row"><b class="v{item.variant}">{item.variant}</b>'
                f'<div class="mx-bar"><i class="v{item.variant}" style="width:{width:.0f}%"></i></div>'
                f'<span class="mx-val">{value}</span><span class="mx-n">{item.count}건</span></div>'
            )
        cards.append(
            f'<div class="mx-card"><div class="mx-title">{label}<small>{english}</small></div>'
            f"{''.join(rows)}</div>"
        )
    return f'<div class="mx-grid">{"".join(cards)}</div>'


def render_comparison() -> None:
    st.html(
        '<div class="sec-title">RAGAS 4대 지표 <small>실행 방식(A/B/C)별 평균</small></div>'
    )
    st.caption(
        "Langfuse 점수를 같은 평가(데이터셋)끼리 묶어 보여 줍니다. 방식을 알 수 없는 점수는 평균에서 뺍니다.  \n"
        "검색 적중률(Hit@k)은 다른 지표라 섞지 않습니다. "
        "점수는 판정 모델의 편차가 있어, 같은 답변도 다시 채점하면 달라질 수 있습니다."
    )
    # st.tabs는 안 열린 탭도 바로 실행한다. 느린 Langfuse 요청이 화면 전체를 막지 않게 버튼을 누른 뒤에만 읽는다.
    if not st.session_state.get("scores_requested"):
        st.caption("Langfuse 서버가 느릴 수 있어 버튼을 누를 때만 점수를 불러옵니다.")
        if st.button("점수 불러오기", key="load_scores"):
            st.session_state["scores_requested"] = True
            st.rerun()
        return
    result = cached_scores()
    if isinstance(result, str):
        # 주소·키·응답 내용은 보이지 않고 오류 종류만 알려 준다.
        if result == "not_configured":
            st.info(LANGFUSE_MESSAGES["not_configured"])  # 설정 안내이지 오류가 아니다.
        else:
            st.error(
                LANGFUSE_MESSAGES.get(
                    result, f"Langfuse에서 점수를 읽지 못했습니다. ({result})"
                )
            )
            if st.button("새로고침", key="refresh_scores_error"):
                cached_scores.clear()
                st.rerun()
        return
    if not result.groups:
        st.info("방식별로 집계할 점수가 아직 없습니다.")
    for group in result.groups:
        st.html(
            f'<div class="mx-head">데이터셋 <b>{escape(group.dataset_id[:8])}</b>'
            f"<span>리라이트 {'ON' if group.rewrite_enabled else 'OFF'}</span>"
            f"<span>최근 실행 {escape(group.latest[:10])}</span></div>"
            + metrics_html(group)
        )
    for counts, reason in (
        (result.unlinked, "방식(A/B/C)을 알 수 없어"),
        (result.unverified, "평가 세트·리라이트 여부를 확인할 수 없어"),
        (result.ineligible, "비교 대상이 아니어서"),
    ):
        left_out = [
            f"{label} {counts[name]}건"
            for name, label, _ in langfuse_scores.METRICS
            if counts[name]
        ]
        if left_out:
            st.caption(f"※ {reason} 평균에서 뺀 점수: " + ", ".join(left_out))
    if st.button("새로고침", key="refresh_scores"):
        cached_scores.clear()
        st.rerun()


def render_dev_panel(view) -> None:
    # 내부 데모 전용: 사용자 화면 아래에 항상 보이는 검증·비교 대시보드.
    with st.container(key="devpanel"):
        st.html('<div class="dash-title">검증·비교 대시보드</div>')
        # 랜딩으로 돌아오면(빈 질문·실패로 응답이 지워짐) 이전에 보던 탭이 남지 않게 화면별로 키를 나눈다.
        inspection_tab, comparison_tab = st.tabs(
            ["검증 패널", "비교 패널"],
            key="dash_tabs_result" if view is not None else "dash_tabs_landing",
        )
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
if not TEAM_SETTINGS_PATH:
    st.error(SETTINGS_GUIDE)
view = current_view()
if view is None and "pending" not in st.session_state:
    render_landing()
else:
    if "pending" in st.session_state:
        # 랜딩에서 넘어오는 동안 검색이 끝날 때까지 옛 랜딩 요소가 흐리게 남는다. 숨긴다.
        st.html(
            '<style>[data-stale="true"],[data-testid="stLayoutWrapper"]:has(> [data-testid="stVerticalBlock"] > [data-stale="true"]),[data-testid="stLayoutWrapper"]:has(> [data-testid="stForm"] [data-stale="true"])'
            "{display:none !important}</style>"
        )
    search_bar(compact=True)
    if "pending" in st.session_state:
        run_pending()  # 성공하면 st.rerun()으로 결과를 다시 그린다. 실패하면 오류가 보인다.
    view = current_view()  # 검색바에서 새 질문이 실패하면 이전 응답이 지워져 있다
    if view is None:
        st.info("질문하면 결과가 여기에 표시됩니다.")
    else:
        render_result(view)
render_dev_panel(view)
st.html(FOOTER_HTML)
