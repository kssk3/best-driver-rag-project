"""공용 실행 기록(RunRecord)을 화면용 응답으로 바꾸는지와 실행 모드 화면을 확인한다. 합성 자료만 사용한다."""

from datetime import datetime, timezone
from pathlib import Path

import pytest
import streamlit as st
from screen_helpers import button, new_app
from streamlit.testing.v1 import AppTest

import src.demo
from src.config import load_settings
from src.contracts import (
    Chunk,
    Citation,
    PipelineOptions,
    PipelineRequest,
    PipelineResponse,
    PlaceLookupResult,
    ResolvedQuery,
    RunRecord,
    SearchCandidate,
)
from src.demo import create_demo_pipeline
from src.infrastructure.embeddings import DemoHashEmbeddings
from src.infrastructure.stores import save_index
from src.ingestion.chunking import chunk_documents
from src.ingestion.indexing import build_index
from src.ingestion.loaders import load_source_documents
from src.interface.adapter import run_record_to_view

ROOT = Path(__file__).parent.parent.parent.parent
APP_PATH = ROOT / "app.py"


def make_chunk(chunk_id: str, districts: list[str]) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        source_document_id="doc-1",
        source_document_version="v1",
        title="[가상] 문서",
        content_format="html",
        content=f"[가상] 본문 {chunk_id}",
        source_url="https://example.invalid/doc-1",
        source_location="별표 1",
        scope_type="district" if districts else "common",
        districts=districts,
        chunking_version="cv-1",
    )


def make_record(
    status: str = "answered",
    resolved: ResolvedQuery | None = None,
    run_kind: str = "demo",
    places: PlaceLookupResult | None = None,
) -> RunRecord:
    chunk = make_chunk("c1", ["서대문구"])
    citation = Citation(
        chunk_id="c1",
        document_id="doc-1",
        document_version="v1",
        source_url="https://example.invalid/doc-1",
        source_location="별표 1",
        title="[가상] 문서",
    )
    answered = status == "answered"
    return RunRecord(
        run_id="run-1",
        request_id="req-1",
        run_kind=run_kind,
        started_at=datetime.now(timezone.utc),
        request=PipelineRequest(question="질문", district="서대문구"),
        options=PipelineOptions(),
        resolved_query=resolved,
        candidates=[SearchCandidate(chunk=chunk, rank=1, score=0.9)]
        if answered
        else [],
        model_input_chunk_ids=["c1"] if answered else [],
        response=PipelineResponse(
            request_id="req-1",
            run_id="run-1",
            status=status,
            answer="[가상] 답변",
            citations=[citation] if answered else [],
            places=places or PlaceLookupResult(),
        ),
        duration_ms=1.0,
    )


def test_answered_record_keeps_candidates_inputs_and_citations() -> None:
    view = run_record_to_view(make_record())
    assert view.status == "answered"
    assert [c.chunk_id for c in view.candidates] == ["c1"]
    assert view.candidates[0].district == "서대문구"
    assert view.candidates[0].score == 0.9
    assert view.model_inputs == ["c1"]
    assert [c.chunk_id for c in view.citations] == ["c1"]
    assert view.citations[0].source_location == "별표 1"
    assert view.error is None


def test_run_kind_decides_view_kind() -> None:
    assert run_record_to_view(make_record(run_kind="demo")).kind == "demo"
    assert run_record_to_view(make_record(run_kind="rag")).kind == "real"


def test_clarification_without_district_asks_for_district() -> None:
    resolved = ResolvedQuery(
        search_query="질문",
        status="needs_clarification",
        clarification_question="어느 구인가요?",
    )
    view = run_record_to_view(make_record("needs_clarification", resolved))
    assert view.required_fields == ["district"]


def test_clarification_with_ambiguous_dong_asks_for_dong() -> None:
    resolved = ResolvedQuery(
        search_query="질문",
        district="서대문구",
        status="needs_clarification",
        clarification_question="어느 동인가요?",
        region_status="ambiguous",
    )
    view = run_record_to_view(make_record("needs_clarification", resolved))
    assert view.required_fields == ["dong"]
    assert view.region_status == "ambiguous"


def test_unsupported_region_guidance_carries_region_status_and_no_fields() -> None:
    resolved = ResolvedQuery(
        search_query="질문",
        district="강남구",
        status="needs_clarification",
        region_status="unsupported",
    )
    view = run_record_to_view(make_record("needs_clarification", resolved))
    assert view.required_fields == []
    assert view.region_status == "unsupported"


@pytest.fixture
def demo_pipeline(tmp_path: Path):
    settings = load_settings(ROOT / "configs" / "demo.json", project_root=ROOT)
    settings.index_path = tmp_path / "index.json"
    settings.runs_path = tmp_path / "runs"
    documents = load_source_documents(
        ROOT / "tests" / "fixtures" / "handoff_documents.json"
    )
    chunks = chunk_documents(documents, max_characters=settings.max_document_characters)
    index = build_index(chunks, DemoHashEmbeddings(dimensions=settings.demo_dimensions))
    save_index(index, settings.index_path)
    return create_demo_pipeline(settings)


def test_demo_pipeline_results_become_views(demo_pipeline) -> None:
    answered = run_record_to_view(
        demo_pipeline.run(PipelineRequest(question="품목알파", district="서대문구"))
    )
    assert answered.status == "answered"
    assert answered.kind == "demo"
    assert answered.citations and answered.model_inputs

    asked = run_record_to_view(demo_pipeline.run(PipelineRequest(question="품목알파")))
    assert asked.status == "needs_clarification"
    assert asked.required_fields == ["district"]

    none = run_record_to_view(
        demo_pipeline.run(PipelineRequest(question="없는품목오메가", district="송파구"))
    )
    assert none.status == "insufficient_evidence"
    assert none.citations == []


def run_app_in_demo_mode(question: str) -> AppTest:
    st.cache_resource.clear()  # 이전 테스트에서 만든 파이프라인이 남지 않게 한다.
    app = new_app().run()
    app.text_input[0].set_value(question)
    return button(app, "물어보기").click().run()


def test_demo_mode_runs_the_pipeline_and_shows_notice(
    demo_pipeline, monkeypatch
) -> None:
    monkeypatch.setattr(
        src.demo, "create_demo_pipeline", lambda settings: demo_pipeline
    )
    app = run_app_in_demo_mode("품목알파")
    assert not app.exception
    assert any("합성 데모 실행입니다" in c.value for c in app.caption)


def test_demo_mode_tells_how_to_build_the_index_when_missing(monkeypatch) -> None:
    def missing(settings):
        raise FileNotFoundError("index")

    monkeypatch.setattr(src.demo, "create_demo_pipeline", missing)
    app = run_app_in_demo_mode("품목알파")
    assert not app.exception
    assert any("scripts.index" in e.value for e in app.error)


def test_demo_mode_asks_for_a_question_when_empty(demo_pipeline, monkeypatch) -> None:
    monkeypatch.setattr(
        src.demo, "create_demo_pipeline", lambda settings: demo_pipeline
    )
    app = run_app_in_demo_mode("   ")
    assert not app.exception
    assert any("질문을 입력하세요" in w.value for w in app.warning)


def test_fixed_evidence_run_keeps_its_own_kind() -> None:
    assert (
        run_record_to_view(make_record(run_kind="fixed_evidence")).kind
        == "fixed_evidence"
    )


def test_failed_stages_and_scope_type_are_carried_to_the_view() -> None:
    from src.contracts import StageRecord

    record = make_record()
    record.stages.append(
        StageRecord(
            name="place_lookup",
            status="error",
            duration_ms=1.0,
            error="[가상] 장소 조회 실패",
            error_code="pipeline.place_lookup_failed",
        )
    )
    record.stages.append(StageRecord(name="search", status="ok", duration_ms=1.0))
    view = run_record_to_view(record)
    assert [(e.name, e.error_code) for e in view.stage_errors] == [
        ("place_lookup", "pipeline.place_lookup_failed")
    ]
    assert view.status == "answered"
    assert view.candidates[0].scope_type == "district"


def test_common_scope_chunk_keeps_scope_type() -> None:
    record = make_record()
    record.candidates[0] = SearchCandidate(
        chunk=make_chunk("c1", []), rank=1, score=0.9
    )
    view = run_record_to_view(record)
    assert view.candidates[0].district is None
    assert view.candidates[0].scope_type == "common"


def test_response_error_code_is_carried_to_the_view() -> None:
    record = make_record(status="error")
    record.response.error_code = "pipeline.example"
    assert run_record_to_view(record).error_code == "pipeline.example"
