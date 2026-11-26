"""Streamlit 진입점.

담당: 이승주
상태: 구현 전 파일 뼈대. 세부 구현 항목은 Notion 구조 문서를 참고한다.
공용 입출력과 함수 규격은 사용하는 담당자와 합의한 뒤 추가한다.
"""

import json
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
from src.interface.adapter import (
    run_record_to_places,
    run_record_to_view,
    to_place_result,
    to_view_response,
)
from src.interface.chat import render_response
from src.interface.comparison import (
    format_summary,
    summarize_scores,
)
from src.interface.inspection import render_inspection
from src.interface.map import render_places
from src.pipeline import PipelineConfigurationError
from src.rewrite_dictionary import catalog

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


PROJECT_ROOT = Path(__file__).resolve().parent
TEAM_INDEX_MODE = "실행"
TEAM_SETTINGS_PATH = getenv("RAG_CHAT_SETTINGS", "").strip()
# 비교 패널이 읽을 scores.csv 경로. 평가마다 새 폴더에 만들어지므로 고정 경로가 없다.
SCORES_CSV_PATH = getenv("RAG_SCORES_CSV", "").strip()


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
                '팀 색인 모드의 실행 설정에서 pipeline.variant를 "A"로 지정하세요.'
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

st.set_page_config(page_title="분리당", page_icon=str(FAVICON_PATH), layout="wide")
st.title("분리당 -- 서울시 분리배출 안내 시스템")


user_tab, inspection_tab, comparison_tab = st.tabs(
    ["사용자 화면", "검증 패널", "비교 패널"]
)


with user_tab:
    modes = ["예시 응답", "합성 데모"]
    if TEAM_SETTINGS_PATH:
        modes.append(TEAM_INDEX_MODE)
    mode = st.radio("응답 방식", modes, horizontal=True)
    district = st.selectbox("지역", ["서대문구", "송파구"])
    question = st.text_input("질문")

    if mode == "예시 응답":
        sample_name = st.selectbox("예시 응답 고르기 (합성)", list(samples))
        st.caption("지금은 입력한 구와 질문에 상관없이 선택한 예시가 표현됩니다.")
    elif mode == TEAM_INDEX_MODE:
        st.caption("설정한 팀 색인에서 검색해 답변합니다.")
    else:
        st.caption("합성 문서만 검색하는 데모 실행입니다. 실제 RAG 품질이 아닙니다.")

    if st.button("질문하기"):
        # 새 요청이 실패하거나 비어도 이전 응답이 남아 보이지 않게 지운다.
        for key in ("view", "places", "asked_question", "asked_district", "asked_mode"):
            st.session_state.pop(key, None)
        # 이전 되묻기에서 입력한 값이 다음 되묻기에 미리 채워지지 않게 한다.
        for key in [k for k in st.session_state if k.startswith("followup:")]:
            del st.session_state[key]
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
            ask_pipeline(mode, PipelineRequest(question=question, district=district))

    # 응답 방식을 바꾸면 다른 방식으로 만든 이전 응답은 사용자 화면과 검증 패널 모두에서 숨긴다.
    view = st.session_state.get("view")
    if st.session_state.get("asked_mode") != mode:
        view = None
    if view is not None:
        # 입력창이 아니라 제출 당시의 질문·지역으로 그린다.
        def send_followup(fields: dict) -> None:
            # 되묻기에 답한 요청을 같은 방식으로 실제 실행한다. 성공하면 새 응답으로 다시 그린다.
            if ask_pipeline(mode, PipelineRequest(**fields)):
                st.rerun()

        render_response(
            view,
            question=st.session_state.get("asked_question", ""),
            district=st.session_state.get("asked_district", ""),
            on_followup=None if mode == "예시 응답" else send_followup,
        )

    st.divider()
    st.subheader("장소")
    if mode == "예시 응답":
        place_name = st.selectbox("예시 장소 고르기 (합성)", list(place_samples))
        render_places(to_place_result(place_samples[place_name], kind="fixture"))
    elif "places" in st.session_state:
        render_places(st.session_state["places"])


with inspection_tab:
    render_inspection(view, st.session_state.get("asked_district"))


with comparison_tab:
    st.subheader("답변 근거 충실도")
    st.caption(
        "같은 평가의 scores.csv에서 비교할 수 있는 행(comparison_eligible=true)만 "
        "방식별로 집계합니다. 검색 적중률(Hit@k)은 다른 지표라 섞지 않습니다."
    )
    if not SCORES_CSV_PATH:
        st.info(
            "평가 결과를 보려면 RAG_SCORES_CSV에 scores.csv 경로를 지정하고 다시 실행하세요."
        )
    else:
        try:
            summaries = summarize_scores(PROJECT_ROOT / SCORES_CSV_PATH)
        except (OSError, ValueError):
            # 파일 경로와 내용(질문·답변)이 섞일 수 있어 오류 원문은 보이지 않는다.
            st.error(
                "점수 파일을 읽지 못했습니다. RAG_SCORES_CSV 경로와 파일의 열을 확인하세요."
            )
        else:
            for column, summary in zip(st.columns(len(summaries)), summaries):
                column.metric(f"방식 {summary.variant}", format_summary(summary))
