"""외부 API 없이 실제 CLI와 공통 런타임의 인계 경로를 검증한다."""

import csv
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from textwrap import dedent

import pytest
from pydantic import ValidationError

from scripts import evaluate
from src.config import load_settings
from src.contracts import GenerationResult, PipelineRequest, ResolvedQuery
from src.demo import create_demo_pipeline
from src.evaluation.csv_export import write_evaluation_csv
from src.infrastructure.embeddings import DemoHashEmbeddings
from src.infrastructure.stores import save_index
from src.ingestion.chunking import chunk_documents
from src.ingestion.indexing import build_index
from src.ingestion.loaders import load_source_documents
from src.runtime import create_runtime

ROOT = Path(__file__).resolve().parents[2]


def csv_rows(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def cli(
    *arguments: str, env: dict | None = None, stdin: str | None = None
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-X", "utf8", "-m", *arguments],
        cwd=ROOT,
        env=env,
        capture_output=True,
        input=stdin,
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
    runs = csv_rows(output / "runs.csv")
    assert {row["run_id"] for row in runs} == {
        row["run_id"] for row in summary["results"]
    }
    assert {row["case_id"] for row in csv_rows(output / "cases.csv")} == {
        row["case_id"] for row in runs
    }
    assert {row["run_id"] for row in csv_rows(output / "candidates.csv")} == {
        answered["run_id"]
    }
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
    cases = {row["case_id"]: row for row in csv_rows(output / "cases.csv")}
    runs = {row["case_id"]: row for row in csv_rows(output / "runs.csv")}
    candidates = csv_rows(output / "candidates.csv")
    assert set(cases) == set(runs) == {row["case_id"] for row in rows}
    assert runs["demo-clarification"]["candidate_count"] == ""
    assert runs["demo-insufficient"]["candidate_count"] == "0"
    for result in rows:
        run = runs[result["case_id"]]
        case = cases[result["case_id"]]
        record = result["record"]
        assert case["dataset_id"] and run["dataset_id"] == case["dataset_id"]
        assert run["configuration"] == result["configuration"]
        assert (
            run["original_question"]
            == case["question"]
            == record["request"]["question"]
        )
        assert run["run_id"] == result["run_id"]
        assert run["status"] == result["status"]
        assert run["answer"] == result["response"]["answer"]
        assert json.loads(run["versions_json"]) == record["options"]["versions"]
        assert datetime.fromisoformat(run["started_at_utc"]) == datetime.fromisoformat(
            record["started_at"]
        )
        kst = datetime.fromisoformat(run["started_at_kst"])
        assert kst.utcoffset() == timedelta(hours=9) and kst == datetime.fromisoformat(
            record["started_at"]
        )
        recorded = record["candidates"]
        exported = [
            candidate
            for candidate in candidates
            if candidate["run_id"] == run["run_id"]
        ]
        assert len(exported) == len(recorded)
        by_id = {candidate["chunk_id"]: candidate for candidate in exported}
        for candidate in recorded:
            chunk = candidate["chunk"]
            actual = by_id[chunk["chunk_id"]]
            assert int(actual["rank"]) == candidate["rank"]
            assert actual["text"] == chunk["content"]
            assert actual["source_url"] == chunk["source_url"]
            assert actual["source_location"] == chunk["source_location"]
        for position, chunk_id in enumerate(record["model_input_chunk_ids"], 1):
            assert by_id[chunk_id]["model_input_position"] == str(position)
        for position, citation in enumerate(record["response"]["citations"], 1):
            assert by_id[citation["chunk_id"]]["citation_position"] == str(position)
    artifacts = [
        path,
        *(output / name for name in ("cases.csv", "runs.csv", "candidates.csv")),
    ]
    before = {artifact: artifact.read_bytes() for artifact in artifacts}
    assert cli(*arguments).returncode != 0
    assert all(artifact.read_bytes() == content for artifact, content in before.items())


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
    assert all(
        row["retrieval_status"] == "error" and row["candidate_count"] == ""
        for row in csv_rows(output / "runs.csv")
    )
    assert csv_rows(output / "candidates.csv") == []


def test_factory_csv_keeps_attempts_and_identifies_equivalent_stdin_datasets(tmp_path):
    module = tmp_path / "comparison_factory.py"
    module.write_text(
        dedent("""\
        from src.contracts import GenerationResult, ResolvedQuery
        from src.pipeline import RAGPipeline

        def make(settings):
            def resolve(request):
                return ResolvedQuery(search_query="실제 검색어", district="서대문구")
            def generate(request, chunks):
                return GenerationResult(status="insufficient_evidence", answer='근거, "없음"\\n다음 줄')
            def fail(request):
                raise RuntimeError("no record")
            def configured():
                return RAGPipeline(resolver=resolve, retriever=lambda *args, **kw: [], generator=generate)
            broken = configured()
            broken.run = fail
            return {"before": configured(), "after": configured(), "failed": broken}
        """),
        encoding="utf-8",
    )
    env = dict(os.environ, PYTHONPATH=str(tmp_path))

    def evaluate_payload(payload, output):
        source = Path("/dev/stdin")
        data = json.dumps(payload, ensure_ascii=False)
        if not source.exists():
            source = tmp_path / "cases.json"
            source.write_text(data, encoding="utf-8")
            data = None
        return cli(
            "scripts.evaluate",
            "--cases",
            str(source),
            "--factory",
            "comparison_factory:make",
            "--output-dir",
            str(output),
            env=env,
            stdin=data,
        )

    case = {
        "case_id": "quoted",
        "question": '원질문, "인용"\n다음 줄',
        "conditions": {"조건": '공동, "주택"'},
        "reference_answer": "정답, 확인",
        "expected_status": "answered",
        "allowed_chunk_ids": ["z", "a"],
    }
    dataset_ids = set()
    equivalent = {**case, "allowed_chunk_ids": ["a", "z"]}
    for folder, payload in [
        ("original", [case]),
        ("repeat", {"is_synthetic": True, "cases": [equivalent]}),
    ]:
        output = tmp_path / folder
        result = evaluate_payload(payload, output)
        assert result.returncode == 1, result.stderr
        [exported] = csv_rows(output / "cases.csv")
        assert exported["question"] == case["question"]
        assert exported["reference_answer"] == case["reference_answer"]
        assert json.loads(exported["conditions_json"]) == case["conditions"]
        assert (
            json.loads(exported["allowed_chunk_ids_json"])
            == (case if folder == "original" else equivalent)["allowed_chunk_ids"]
        )
        dataset_ids.add(exported["dataset_id"])
        runs = {row["configuration"]: row for row in csv_rows(output / "runs.csv")}
        assert set(runs) == {"before", "after", "failed"}
        assert all(
            row["dataset_id"] == exported["dataset_id"]
            and row["case_id"] == case["case_id"]
            for row in runs.values()
        )
        failed = runs["failed"]
        assert failed["status"] == "error" and "no record" in failed["error"]
        assert all(
            failed[key] == ""
            for key in (
                "answer",
                "run_id",
                "started_at_utc",
                "candidate_count",
                "variant",
            )
        )
        for name in ("before", "after"):
            row = runs[name]
            assert row["variant"] == "A" and row["candidate_count"] == "0"
            assert (
                row["district"] == "서대문구" and row["search_query"] == "실제 검색어"
            )
            assert row["answer"] == '근거, "없음"\n다음 줄'
        assert not csv_rows(output / "candidates.csv")
    assert len(dataset_ids) == 1

    output = tmp_path / "empty"
    result = evaluate_payload([], output)
    assert result.returncode == 0, result.stderr
    for name in ("cases", "runs", "candidates"):
        with (output / f"{name}.csv").open(encoding="utf-8", newline="") as stream:
            header, *rows = csv.reader(stream)
        assert "case_id" in header and rows == []


@pytest.mark.parametrize("failure_stage", ["writing", "reservation_close"])
def test_csv_write_failure_preserves_raw_evidence_and_publishes_no_partial_tables(
    tmp_path, monkeypatch, capsys, failure_stage
):
    output = tmp_path / "failed-export"

    def factory(settings):
        return create_runtime(
            settings,
            resolver=lambda req: ResolvedQuery(search_query=req.question),
            retriever=lambda *args, **kwargs: [],
            generator=lambda *args: GenerationResult(
                status="insufficient_evidence", answer="없음"
            ),
        )

    if failure_stage == "writing":
        write_row = csv.DictWriter.writerow

        def fail_on_run(writer, row):
            if row.get("configuration") == "synthetic-demo":
                raise OSError("simulated storage failure")
            return write_row(writer, row)

        monkeypatch.setattr(csv.DictWriter, "writerow", fail_on_run)
    else:
        close = os.close
        target = output / "runs.csv"

        def fail_on_target_close(fd):
            reserved_run = target.exists() and os.path.samestat(
                os.fstat(fd), target.stat()
            )
            close(fd)
            if reserved_run:
                raise OSError("simulated storage failure")

        monkeypatch.setattr(os, "close", fail_on_target_close)

    monkeypatch.setattr(evaluate, "create_demo_pipeline", factory)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "evaluate",
            "--demo",
            "--cases",
            str(ROOT / "tests/fixtures/handoff_eval.json"),
            "--output-dir",
            str(output),
        ],
    )
    with pytest.raises(OSError, match="simulated storage failure"):
        evaluate.main()
    assert capsys.readouterr().out == ""
    raw = json.loads((output / "evaluation.json").read_text(encoding="utf-8"))
    assert len(raw) == 3
    assert all((output / "runs" / f"{row['run_id']}.json").exists() for row in raw)
    assert list(output.glob("*.csv")) == []


def test_export_on_filesystem_without_hard_links_preserves_existing_files(
    tmp_path, monkeypatch
):
    def unsupported(*args, **kwargs):
        raise OSError("hard links unavailable")

    monkeypatch.setattr(os, "link", unsupported)
    existing = tmp_path / "runs.csv"
    existing.write_bytes(b"existing")
    with pytest.raises(FileExistsError):
        write_evaluation_csv(tmp_path, [], [])
    assert (
        list(tmp_path.iterdir()) == [existing] and existing.read_bytes() == b"existing"
    )

    fresh = tmp_path / "fresh"
    fresh.mkdir()
    write_evaluation_csv(fresh, [], [])
    assert {path.name for path in fresh.iterdir()} == {
        "cases.csv",
        "runs.csv",
        "candidates.csv",
    }


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
