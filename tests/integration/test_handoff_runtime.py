"""외부 API 없이 실제 CLI와 공통 런타임의 인계 경로를 검증한다."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.config import load_settings
from src.contracts import GenerationResult, PipelineRequest, ResolvedQuery
from src.demo import create_demo_pipeline
from src.infrastructure.embeddings import DemoHashEmbeddings
from src.infrastructure.stores import save_index
from src.ingestion.chunking import chunk_documents
from src.ingestion.indexing import build_index
from src.ingestion.loaders import load_source_documents
from src.runtime import create_runtime

ROOT = Path(__file__).resolve().parents[2]


def cli(*arguments: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-X", "utf8", "-m", *arguments],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )


def test_demo_cli_produces_three_distinct_outcomes_without_api_key(tmp_path):
    output = tmp_path / "demo"
    env = {key: value for key, value in os.environ.items() if key != "OPENAI_API_KEY"}
    result = cli("scripts.demo", "--output-dir", str(output), env=env)
    assert result.returncode == 0, result.stderr
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert summary["is_synthetic"] is True
    assert (summary["manifest_documents"], summary["manifest_attachments"]) == (4, 21)
    assert summary["chunks"] == 3
    assert [row["status"] for row in summary["results"]] == [
        "answered",
        "needs_clarification",
        "insufficient_evidence",
    ]
    assert len(list((output / "runs").glob("*.json"))) == 3
    for row in summary["results"]:
        record_path = output / "runs" / f"{row['run_id']}.json"
        assert json.loads(record_path.read_text(encoding="utf-8")) == row["record"]
        assert row["record"]["run_kind"] == "demo"
    answered = summary["results"][0]["record"]
    assert answered["resolved_query"]["district"] == "서대문구"
    assert answered["response"]["citations"][0]["document_id"] == "demo-seodaemun"
    before = (output / "summary.json").read_bytes()
    assert cli("scripts.demo", "--output-dir", str(output), env=env).returncode != 0
    assert (output / "summary.json").read_bytes() == before


def test_demo_pipeline_keeps_each_district_conditions_and_citations_separate(tmp_path):
    settings = load_settings(ROOT / "configs/demo.json", project_root=tmp_path)
    documents = load_source_documents(ROOT / "tests/fixtures/handoff_documents.json")
    chunks = chunk_documents(documents, max_characters=settings.max_document_characters)
    save_index(
        build_index(chunks, DemoHashEmbeddings(settings.demo_dimensions)),
        settings.index_path,
    )
    pipeline = create_demo_pipeline(settings)
    by_id = {chunk.chunk_id: chunk for chunk in chunks}
    records = []

    # 대화 CLI를 거치지 않아도 같은 질문의 구별 조건과 근거가 섞이지 않아야 한다.
    for district, expected, excluded, document_id in (
        ("서대문구", "조건엑스", "조건와이", "demo-seodaemun"),
        ("송파구", "조건와이", "조건엑스", "demo-songpa"),
    ):
        record = pipeline.run(PipelineRequest(question="품목알파", district=district))
        records.append(record)
        assert record.run_kind == "demo"
        assert record.response.status == "answered", record.response.error
        assert expected in record.response.answer
        assert excluded not in record.response.answer
        assert record.resolved_query.district == district
        assert {citation.document_id for citation in record.response.citations} == {
            document_id
        }
        assert {citation.chunk_id for citation in record.response.citations} <= set(
            record.model_input_chunk_ids
        )
        assert {
            by_id[chunk_id].source_document_id
            for chunk_id in record.model_input_chunk_ids
        } == {document_id}

    assert len({record.request_id for record in records}) == 2
    assert len({record.run_id for record in records}) == 2


def test_index_then_evaluate_cli_with_default_index_dimensions(tmp_path):
    index = tmp_path / "index.json"
    result = cli(
        "scripts.index",
        "--documents",
        str(ROOT / "tests/fixtures/handoff_documents.json"),
        "--output",
        str(index),
        "--demo",
        "--content-format",
        "html",
    )
    assert result.returncode == 0, result.stderr
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"index_path": str(index)}), encoding="utf-8")
    output = tmp_path / "evaluation"
    arguments = (
        "scripts.evaluate",
        "--cases",
        str(ROOT / "tests/fixtures/handoff_eval.json"),
        "--settings",
        str(settings),
        "--output-dir",
        str(output),
        "--demo",
    )
    result = cli(*arguments)
    assert result.returncode == 0, result.stderr
    path = output / "evaluation.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    assert len(rows) == 3
    assert [row["status"] for row in rows] == [
        "answered",
        "needs_clarification",
        "insufficient_evidence",
    ]
    before = path.read_bytes()
    assert cli(*arguments).returncode != 0
    assert path.read_bytes() == before


def test_factory_cli_keeps_error_records_and_exits_nonzero(tmp_path):
    module = tmp_path / "handoff_factory.py"
    module.write_text(
        "from src.contracts import ResolvedQuery\n"
        "from src.runtime import create_runtime\n"
        "def make(settings):\n"
        "    def resolve(request):\n"
        "        return ResolvedQuery(search_query=request.question, district=request.district)\n"
        "    def retrieve(query, **kwargs):\n"
        "        raise RuntimeError('provider failed')\n"
        "    return create_runtime(settings, resolver=resolve, retriever=retrieve, generator=None)\n",
        encoding="utf-8",
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(tmp_path) + os.pathsep + env.get("PYTHONPATH", "")
    output = tmp_path / "failed"
    result = cli(
        "scripts.evaluate",
        "--cases",
        str(ROOT / "tests/fixtures/handoff_eval.json"),
        "--factory",
        "handoff_factory:make",
        "--output-dir",
        str(output),
        env=env,
    )
    assert result.returncode == 1, result.stderr
    rows = json.loads((output / "evaluation.json").read_text(encoding="utf-8"))
    assert len(rows) == 3 and all(row["status"] == "error" for row in rows)
    assert len(list((output / "runs").glob("*.json"))) == 3
    assert all("provider failed" in row["error"] for row in rows)


def test_settings_resolve_paths_and_reject_unknown_keys(tmp_path):
    settings = load_settings(project_root=tmp_path)
    assert settings.index_path == tmp_path / "data/indexes/demo.json"
    assert settings.runs_path == tmp_path / "results/local/runs"
    path = tmp_path / "bad.json"
    path.write_text('{"OPENAI_API_KEY": "placeholder"}', encoding="utf-8")
    with pytest.raises(ValidationError):
        load_settings(path, project_root=tmp_path)


def test_runtime_preserves_inferred_region_and_original_request(tmp_path):
    settings = load_settings(project_root=tmp_path)
    pipeline = create_runtime(
        settings,
        resolver=lambda request: ResolvedQuery(
            search_query=request.question, district="서대문구"
        ),
        retriever=lambda query, **kwargs: [],
        generator=lambda request, chunks: GenerationResult(
            status="insufficient_evidence",
            answer="근거가 없습니다.",
        ),
    )
    record = pipeline.run(PipelineRequest(question="시험 질문"))
    assert record.request.district is None
    assert record.resolved_query.district == "서대문구"
    saved = json.loads(
        (settings.runs_path / f"{record.run_id}.json").read_text(encoding="utf-8")
    )
    assert saved["resolved_query"]["district"] == "서대문구"
