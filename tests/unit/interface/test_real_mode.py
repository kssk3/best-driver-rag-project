"""화면의 세 번째 응답 방식(실행(실제 검색))을 가짜 파이프라인으로 확인한다. 외부 호출은 하지 않는다."""

import importlib
from datetime import datetime, timezone
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from src.contracts import (
    Chunk,
    Citation,
    PipelineOptions,
    PipelineRequest,
    PipelineResponse,
    ResolvedQuery,
    RunRecord,
    SearchCandidate,
)

APP_PATH = Path(__file__).parent.parent.parent.parent / "app.py"
RUNTIMES = "src.evaluation.answer_experiments.answer_evaluation_runtimes"
REAL_MODE = "실행(실제 검색)"


@pytest.fixture(autouse=True)
def _clear_pipeline_cache():
    st.cache_resource.clear()  # load_pipeline의 캐시가 테스트끼리 새지 않게 한다
    yield
    st.cache_resource.clear()


def _real_record() -> RunRecord:
    chunk = Chunk(
        chunk_id="c1",
        source_document_id="doc-1",
        source_document_version="v1",
        title="[가상] 문서",
        content_format="html",
        content="[가상] 본문",
        source_url="https://example.invalid/doc-1",
        source_location="별표 1",
        scope_type="district",
        districts=["서대문구"],
        chunking_version="cv-1",
    )
    citation = Citation(
        chunk_id="c1",
        document_id="doc-1",
        document_version="v1",
        source_url="https://example.invalid/doc-1",
        source_location="별표 1",
        title="[가상] 문서",
    )
    return RunRecord(
        run_id="run-1",
        request_id="req-1",
        run_kind="rag",
        started_at=datetime.now(timezone.utc),
        request=PipelineRequest(question="질문", district="서대문구"),
        options=PipelineOptions(),
        candidates=[SearchCandidate(chunk=chunk, rank=1, score=0.9)],
        model_input_chunk_ids=["c1"],
        response=PipelineResponse(
            request_id="req-1",
            run_id="run-1",
            status="answered",
            answer="[가상] 실제 검색 답변",
            citations=[citation],
        ),
        duration_ms=1.0,
    )


class _FakePipeline:
    def run(self, request):
        return _real_record()


def _ask_in_real_mode(question: str) -> AppTest:
    app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
    app.radio[0].set_value(REAL_MODE).run()
    app.text_input[0].set_value(question)
    return app.button[0].click().run()


def test_radio_offers_three_modes_and_starts_on_the_fixture() -> None:
    app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()

    assert app.radio[0].options == ["예시 응답", "실행(합성 데모)", REAL_MODE]
    assert app.radio[0].value == "예시 응답"


def test_real_mode_uses_the_real_runtime_with_its_own_runs_path_and_shows_a_notice(
    monkeypatch,
) -> None:
    seen = {}

    def fake_create(settings):
        seen["runs_path"] = settings.runs_path
        return _FakePipeline()

    monkeypatch.setattr(
        importlib.import_module(RUNTIMES), "create_a_runtime", fake_create
    )
    app = _ask_in_real_mode("피자박스는 어디에 버려요?")

    assert not app.exception
    assert app.session_state["view"].kind == "real"
    assert seen["runs_path"].name == "screen-runs"  # 평가 실행 기록과 섞이지 않는다
    assert any("외부 모델로 전송" in caption.value for caption in app.caption)


def test_real_mode_failure_shows_the_error_type_but_never_the_raw_error(
    monkeypatch,
) -> None:
    def boom(settings):
        raise RuntimeError("sk-secret-key")

    monkeypatch.setattr(importlib.import_module(RUNTIMES), "create_a_runtime", boom)
    app = _ask_in_real_mode("질문")

    texts = [error.value for error in app.error]
    assert not app.exception
    assert any("RuntimeError" in text and "prepare_data" in text for text in texts)
    assert not any("sk-secret-key" in text for text in texts)
    assert "view" not in app.session_state


class _AskThenAnswer:
    """되묻기를 먼저 돌려주고, 구를 확정한 요청에는 답변을 돌려준다."""

    def __init__(self, fail_on_followup: bool = False):
        self.requests: list[PipelineRequest] = []
        self.fail_on_followup = fail_on_followup

    def run(self, request):
        self.requests.append(request)
        record = _real_record()
        if not request.district_confirmed:
            clarification = PipelineResponse(
                request_id="req-1",
                run_id="run-1",
                status="needs_clarification",
                answer="어느 구 기준으로 알려 드릴까요?",
            )
            return record.model_copy(update={"response": clarification})
        if self.fail_on_followup:
            raise RuntimeError("sk-secret-key")
        return record


def _ask_clarification(monkeypatch, pipeline: _AskThenAnswer) -> AppTest:
    monkeypatch.setattr(
        importlib.import_module(RUNTIMES), "create_a_runtime", lambda s: pipeline
    )
    app = _ask_in_real_mode("송파구에서 대형폐기물은 어떻게 버려요?")
    assert any("어느 구 기준" in w.value for w in app.warning)
    return app


def test_followup_in_real_mode_is_actually_sent_with_the_confirmed_district(
    monkeypatch,
) -> None:
    pipeline = _AskThenAnswer()
    app = _ask_clarification(monkeypatch, pipeline)

    app.text_input[1].set_value("송파구")
    app.button[1].click().run()

    assert not app.exception
    second = pipeline.requests[1]
    assert (second.district, second.district_confirmed) == ("송파구", True)
    assert second.question == "송파구에서 대형폐기물은 어떻게 버려요?"
    assert any("[가상] 실제 검색 답변" in s.value for s in app.success)
    assert not app.json  # 예시 미리보기가 아니라 실제로 보냈다
    assert (
        app.session_state["asked_district"] == "송파구"
    )  # 이어지는 되묻기도 이 구를 기준으로 한다


def test_followup_failure_keeps_the_form_and_hides_the_raw_error(monkeypatch) -> None:
    pipeline = _AskThenAnswer(fail_on_followup=True)
    app = _ask_clarification(monkeypatch, pipeline)

    app.text_input[1].set_value("송파구")
    app.button[1].click().run()

    texts = [error.value for error in app.error]
    assert not app.exception
    assert any("RuntimeError" in text for text in texts)
    assert not any("sk-secret-key" in text for text in texts)
    assert any("어느 구 기준" in w.value for w in app.warning)  # 다시 시도할 수 있다


class _Unsupported:
    """지원 밖 구 안내를 돌려준다. 채울 값이 없는 되묻기다."""

    def run(self, request):
        record = _real_record()
        response = PipelineResponse(
            request_id="req-1",
            run_id="run-1",
            status="needs_clarification",
            answer="강남구는 아직 지원하지 않아요. 서대문구·송파구의 동이나 구를 알려 주세요.",
        )
        resolved = ResolvedQuery(
            search_query="질문",
            status="needs_clarification",
            region_status="unsupported",
            district="강남구",
        )
        return record.model_copy(
            update={"response": response, "resolved_query": resolved}
        )


def test_unsupported_guidance_has_no_resend_form_and_points_back_to_the_inputs(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        importlib.import_module(RUNTIMES), "create_a_runtime", lambda s: _Unsupported()
    )
    app = _ask_in_real_mode("강남구 삼성동에서 대형폐기물은 어떻게 버려요?")

    assert not app.exception
    assert any("아직 지원하지 않아요" in w.value for w in app.warning)
    assert [b.label for b in app.button] == [
        "질문하기"
    ]  # 같은 요청을 다시 보내는 버튼이 없다
    assert any("바꿔서 다시 질문" in c.value for c in app.caption)
