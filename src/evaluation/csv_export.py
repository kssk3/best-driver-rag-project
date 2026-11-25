"""Write comparable case, attempt and candidate tables from evaluation records."""

import csv
import hashlib
import json
import os
from contextlib import ExitStack
from datetime import UTC
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from src.contracts import EvaluationCase, RunRecord

_CASE_FIELDS = (
    "dataset_id case_id question district dong conditions_json expected_status "
    "reference_answer allowed_chunk_ids_json"
).split()
_RUN_FIELDS = (
    "dataset_id case_id configuration run_id started_at_utc started_at_kst "
    "original_question district search_query status answer candidate_count "
    "allowed_source_ranks_json model_input_ranks_json citation_ranks_json warnings_json "
    "error duration_ms variant rewrite_enabled top_k max_context_chars model embedding "
    "index_id chunking_version versions_json run_kind retrieval_status"
).split()
_CANDIDATE_FIELDS = (
    "dataset_id case_id configuration run_id started_at_utc started_at_kst district "
    "search_query rank score document_id document_version source_location chunk_id "
    "content_chars allowed_by_case model_input_position citation_position title source_url text"
).split()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _first_positions(chunk_ids: list[str]) -> dict[str, int]:
    positions: dict[str, int] = {}
    for position, chunk_id in enumerate(chunk_ids, 1):
        positions.setdefault(chunk_id, position)
    return positions


def _record_rows(
    case: EvaluationCase, result: dict, dataset_id: str
) -> tuple[dict, list[dict]]:
    shared = {
        "dataset_id": dataset_id,
        "case_id": case.case_id,
        "configuration": result["configuration"],
        "run_id": result["run_id"],
        "district": case.district,
    }
    run = {
        **shared,
        "original_question": case.question,
        "status": result["status"],
        "error": result["error"],
    }
    if result["record"] is None:
        return run, []

    record = RunRecord.model_validate(result["record"])
    retrieve = next((s.status for s in record.stages if s.name == "retrieve"), None)
    if record.started_at.utcoffset() is not None:
        shared["started_at_utc"] = (
            record.started_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
        )
        shared["started_at_kst"] = record.started_at.astimezone(
            ZoneInfo("Asia/Seoul")
        ).isoformat()
    if record.resolved_query and record.resolved_query.district:
        shared["district"] = record.resolved_query.district
    if retrieve != "skipped":
        shared["search_query"] = record.search_query

    candidates = record.candidates
    count_known = retrieve == "ok" or bool(candidates)
    allowed = set(case.allowed_chunk_ids)
    ranks = {c.chunk.chunk_id: c.rank for c in candidates}
    inputs = record.model_input_chunk_ids
    citations = [citation.chunk_id for citation in record.response.citations]
    input_positions = _first_positions(inputs)
    citation_positions = _first_positions(citations)
    versions = record.options.versions
    run.update(
        {
            **shared,
            "answer": record.response.answer,
            "candidate_count": len(candidates) if count_known else None,
            "allowed_source_ranks_json": _json(
                [c.rank for c in candidates if c.chunk.chunk_id in allowed]
            )
            if count_known
            else None,
            "model_input_ranks_json": _json(
                [ranks.get(chunk_id) for chunk_id in inputs]
            ),
            "citation_ranks_json": _json(
                [ranks.get(chunk_id) for chunk_id in citations]
            ),
            "warnings_json": _json(record.warnings),
            "duration_ms": record.duration_ms,
            "variant": record.options.variant,
            "rewrite_enabled": _json(record.options.rewrite_enabled),
            "top_k": record.options.top_k,
            "max_context_chars": record.options.max_context_chars,
            "model": versions.get("model"),
            "embedding": versions.get("embedding"),
            "index_id": versions.get("index"),
            "chunking_version": versions.get("chunking"),
            "versions_json": _json(versions),
            "run_kind": record.run_kind,
            "retrieval_status": retrieve,
        }
    )
    candidate_rows = []
    for candidate in candidates:
        chunk = candidate.chunk
        candidate_rows.append(
            {
                **shared,
                "rank": candidate.rank,
                "score": candidate.score,
                "document_id": chunk.source_document_id,
                "document_version": chunk.source_document_version,
                "source_location": chunk.source_location,
                "chunk_id": chunk.chunk_id,
                "content_chars": len(chunk.content),
                "allowed_by_case": _json(chunk.chunk_id in allowed),
                "model_input_position": input_positions.get(chunk.chunk_id),
                "citation_position": citation_positions.get(chunk.chunk_id),
                "title": chunk.title,
                "source_url": chunk.source_url,
                "text": chunk.content,
            }
        )
    return run, candidate_rows


def _write_tables(
    directory: Path, cases: list[EvaluationCase], results: list[dict]
) -> None:
    by_id = {case.case_id: case for case in cases}
    canonical = [
        {
            **case.model_dump(mode="json"),
            "allowed_chunk_ids": sorted(set(case.allowed_chunk_ids)),
        }
        for case in sorted(cases, key=lambda case: case.case_id)
    ]
    dataset_id = hashlib.sha256(_json(canonical).encode("utf-8")).hexdigest()

    with ExitStack() as files:

        def writer(name: str, fields: list[str]) -> csv.DictWriter:
            stream = files.enter_context(
                (directory / name).open("x", encoding="utf-8", newline="")
            )
            table = csv.DictWriter(stream, fieldnames=fields)
            table.writeheader()
            return table

        case_table = writer("cases.csv", _CASE_FIELDS)
        run_table = writer("runs.csv", _RUN_FIELDS)
        candidate_table = writer("candidates.csv", _CANDIDATE_FIELDS)
        for case in cases:
            case_table.writerow(
                {
                    "dataset_id": dataset_id,
                    "case_id": case.case_id,
                    "question": case.question,
                    "district": case.district,
                    "dong": case.dong,
                    "conditions_json": _json(case.conditions),
                    "expected_status": case.expected_status,
                    "reference_answer": case.reference_answer,
                    "allowed_chunk_ids_json": _json(case.allowed_chunk_ids),
                }
            )
        for result in results:
            run, candidates = _record_rows(by_id[result["case_id"]], result, dataset_id)
            run_table.writerow(run)
            candidate_table.writerows(candidates)


def write_evaluation_csv(
    directory: Path, cases: list[EvaluationCase], results: list[dict]
) -> None:
    """Close all three tables before publishing; retain original run evidence on failure."""
    with TemporaryDirectory(dir=directory) as staging:
        staged = Path(staging)
        _write_tables(staged, cases, results)
        with ExitStack() as rollback:
            tables = ("cases.csv", "runs.csv", "candidates.csv")
            for name in tables:
                target = directory / name
                descriptor = os.open(
                    target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o666
                )
                rollback.callback(target.unlink)
                os.close(descriptor)
            for name in tables:
                (staged / name).replace(directory / name)
            rollback.pop_all()
