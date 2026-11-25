"""저장된 답변과 생성기에 전달한 근거를 이용한 사후 Faithfulness 평가."""

import csv
import json
import math
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from pydantic import ValidationError

from src.contracts import RunRecord

FIELDS = (
    "evaluation_id attempt_index dataset_id case_id configuration run_id run_kind "
    "run_started_at_utc versions_json metric ragas_version judge_model status score "
    "reason scored_at_utc duration_ms"
).split()


class InputError(ValueError):
    """원문을 포함하지 않는 평가 입력 오류 코드."""


def metric_input(record: RunRecord) -> dict:
    ids = record.model_input_chunk_ids
    if not ids:
        raise InputError("missing_model_input_chunk_ids")
    chunks = {}
    for candidate in record.candidates:
        chunk = candidate.chunk
        if chunk.chunk_id in chunks and chunks[chunk.chunk_id] != chunk.content:
            raise InputError("ambiguous_chunk_id")
        chunks[chunk.chunk_id] = chunk.content
    if any(chunk_id not in chunks for chunk_id in ids):
        raise InputError("unresolved_chunk_id")
    contexts = [chunks[chunk_id] for chunk_id in ids]
    if not all(text.strip() for text in contexts):
        raise InputError("empty_context")
    if not record.request.question.strip() or not record.response.answer.strip():
        raise InputError("empty_question_or_answer")
    return {
        "user_input": record.request.question,
        "response": record.response.answer,
        "retrieved_contexts": contexts,
    }


async def _score(row, attempt, case, scorer):
    if not case:
        raise InputError("unknown_case")
    if attempt.get("record") is None:
        row.update(status="skipped", reason="no_run_record")
        return
    record = RunRecord.model_validate(attempt["record"])
    if (
        not record.run_id
        or record.run_id != row["run_id"]
        or record.response.run_id != record.run_id
        or record.response.status != attempt.get("status")
        or record.request.question != case["question"]
    ):
        raise InputError("record_mismatch")
    # The case CSV serializes an unspecified district or dong as an empty cell.
    if case.get("district") != (record.request.district or ""):
        raise InputError("snapshot_district_mismatch")
    if case.get("dong") != (record.request.dong or ""):
        raise InputError("snapshot_dong_mismatch")
    try:
        conditions = json.loads(case["conditions_json"])
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise InputError("invalid_snapshot_conditions") from error
    if not isinstance(conditions, dict):
        raise InputError("invalid_snapshot_conditions")
    if conditions != record.request.conditions:
        raise InputError("snapshot_conditions_mismatch")
    row.update(
        run_kind=record.run_kind,
        versions_json=json.dumps(
            record.options.versions, sort_keys=True, ensure_ascii=False
        ),
        run_started_at_utc=record.started_at.astimezone(UTC).isoformat()
        if record.started_at.utcoffset() is not None
        else "",
    )
    if record.response.status != "answered":
        row.update(status="skipped", reason="response_" + record.response.status)
        return
    sample = metric_input(record)
    if scorer is None:
        row.update(status="skipped", reason="validate_only")
        return
    try:
        result = await scorer(**sample)
    except Exception:
        row.update(status="scorer_error", reason="judge_failed")
        return
    value = getattr(result, "value", None)
    if value is None:
        row.update(status="no_score", reason="missing_value")
    elif isinstance(value, bool) or not isinstance(value, (float, int)):
        row.update(status="no_score", reason="invalid_value")
    elif not math.isfinite(value):
        row.update(status="no_score", reason="non_finite_value")
    elif not 0 <= value <= 1:
        row.update(status="no_score", reason="out_of_range")
    else:
        row.update(status="scored", score=float(value))


async def score_archive(
    archive: Path,
    cases_csv: Path,
    output: Path,
    *,
    judge_model="",
    scorer=None,
    case_id=None,
) -> bool:
    """하나의 새 평가에 속한 각 시도와 지표를 기록한다. 오류가 있으면 False."""
    attempts = json.loads(archive.read_text(encoding="utf-8"))
    if not isinstance(attempts, list) or not all(isinstance(a, dict) for a in attempts):
        raise ValueError("evaluation.json must contain a list of attempts")
    with cases_csv.open(encoding="utf-8-sig", newline="") as stream:
        cases = list(csv.DictReader(stream))
    by_id = {case["case_id"]: case for case in cases}
    datasets = {case["dataset_id"] for case in cases}
    if len(by_id) != len(cases) or len(datasets) != 1 or "" in datasets:
        raise ValueError("expected unique cases from one dataset")
    dataset_id = datasets.pop()
    if case_id is not None and not any(a.get("case_id") == case_id for a in attempts):
        raise ValueError("no matching attempt")
    evaluation_id = uuid4().hex
    ragas_version = version("ragas")
    output.mkdir(parents=True, exist_ok=False)
    ok = True
    with (output / "scores.csv").open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        for index, attempt in enumerate(attempts, 1):
            if case_id is not None and attempt.get("case_id") != case_id:
                continue
            start = perf_counter()
            row = {
                "evaluation_id": evaluation_id,
                "attempt_index": index,
                "case_id": attempt.get("case_id"),
                "configuration": attempt.get("configuration"),
                "run_id": attempt.get("run_id"),
                "dataset_id": dataset_id,
                "metric": "faithfulness",
                "ragas_version": ragas_version,
                "judge_model": judge_model,
            }
            try:
                await _score(row, attempt, by_id.get(row["case_id"]), scorer)
            except InputError as error:
                row.update(status="input_error", reason=str(error))
            except ValidationError:
                row.update(status="input_error", reason="invalid_run_record")
            row["scored_at_utc"] = datetime.now(UTC).isoformat()
            row["duration_ms"] = round((perf_counter() - start) * 1000, 3)
            writer.writerow(row)
            stream.flush()
            if (
                row["status"] not in {"scored", "skipped"}
                or row.get("reason") == "no_run_record"
            ):
                ok = False
    return ok
