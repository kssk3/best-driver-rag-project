"""저장된 답변과 생성기에 전달한 근거를 이용한 사후 Faithfulness 평가."""

import csv
import json
import math
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from pathlib import Path
from threading import Lock
from time import perf_counter
from uuid import uuid4

from pydantic import ValidationError

from src.contracts import RunRecord

FIELDS = (
    "evaluation_id attempt_index dataset_id case_id configuration run_id run_kind "
    "run_started_at_utc versions_json metric ragas_version judge_model status score "
    "reason scored_at_utc duration_ms variant rewrite_enabled reported_configuration "
    "comparison_eligible comparison_exclusion_reason"
).split()


_ARCHIVE_CSV_LOCK = Lock()


class InputError(ValueError):
    """원문을 포함하지 않는 평가 입력 오류 코드."""


class JudgeError(Exception):
    """채점 어댑터가 만든 원문 없는 단계·유형 코드."""


def metric_input(record: RunRecord) -> dict:
    ids = record.model_input_chunk_ids
    if not ids:
        raise InputError("missing_model_input_chunk_ids")
    chunks: dict[str, str] = {}
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


@contextmanager
def _archive_rows(path: Path, required: set[str]) -> Iterator[csv.DictReader]:
    """공식 아카이브의 장문 필드를 읽는 동안만 현재 파일 크기까지 허용한다."""
    with path.open(encoding="utf-8-sig", newline="") as stream, _ARCHIVE_CSV_LOCK:
        # csv.field_size_limit is shared by readers. Serialize archive reads and
        # restore it before yielding control to any asynchronous judge.
        previous_limit = csv.field_size_limit()
        csv.field_size_limit(max(previous_limit, os.fstat(stream.fileno()).st_size))
        try:
            reader = csv.DictReader(stream)
            missing = required.difference(reader.fieldnames or ())
            if missing:
                raise ValueError(
                    f"{path.name} 필수 열 누락: {', '.join(sorted(missing))}"
                )
            yield reader
        finally:
            csv.field_size_limit(previous_limit)


def _load_runs(archive: Path, dataset_id: str) -> dict[str, dict[str, str]]:
    path = archive.with_name("runs.csv")
    with _archive_rows(path, {"dataset_id", "case_id", "run_id"}) as reader:
        runs: dict[str, dict[str, str]] = {}
        for run in reader:
            if run["dataset_id"] != dataset_id:
                raise ValueError("cases.csv와 runs.csv의 dataset_id가 다릅니다")
            run_id = run["run_id"]
            if not run_id:
                # A failed attempt can have no saved run; its reason comes from evaluation.json.
                continue
            if run_id in runs:
                raise ValueError("runs.csv에 중복 run_id가 있습니다")
            runs[run_id] = run
    return runs


def _started_at_utc(record: RunRecord, run: dict[str, str]) -> str:
    if record.started_at.utcoffset() is not None:
        return record.started_at.astimezone(UTC).isoformat()
    try:
        started = datetime.fromisoformat(run.get("started_at_utc") or "")
    except ValueError as error:
        raise InputError("missing_run_start_utc") from error
    if started.utcoffset() != timedelta(0):
        raise InputError("missing_run_start_utc")
    return started.isoformat()


def _comparison_metadata(
    record: RunRecord, run: dict[str, str], reported_configuration: object
) -> dict[str, str]:
    """원본의 구성 이름과 검색 방식을 대조하고 실검색 비교에서 제외할 사유를 반환한다."""
    configuration = run.get("configuration") or ""
    if (
        reported_configuration is not None
        and "configuration" in run
        and configuration != reported_configuration
    ):
        raise InputError("run_configuration_mismatch")

    # 내보내기도 생략된 옵션에 기본값 A를 쓸 수 있어 원본 JSON의 명시 여부를 확인한다.
    variant = (
        record.options.variant if "variant" in record.options.model_fields_set else ""
    )
    if variant and run.get("variant") and run["variant"] != variant:
        raise InputError("run_variant_mismatch")
    rewrite = (
        json.dumps(record.options.rewrite_enabled)
        if "rewrite_enabled" in record.options.model_fields_set
        else ""
    )
    if (
        rewrite
        and run.get("rewrite_enabled")
        and run["rewrite_enabled"].lower() != rewrite
    ):
        raise InputError("run_rewrite_mismatch")
    if ("run_kind" in run and run["run_kind"] != record.run_kind) or (
        "run_kind" in record.options.model_fields_set
        and record.options.run_kind != record.run_kind
    ):
        raise InputError("run_kind_mismatch")

    retrieval = [stage.status for stage in record.stages if stage.name == "retrieve"]
    if len(retrieval) > 1:
        raise InputError("ambiguous_retrieval_stage")
    if (
        retrieval
        and "retrieval_status" in run
        and run["retrieval_status"] != retrieval[0]
    ):
        raise InputError("retrieval_status_mismatch")

    exclusion: str
    if record.run_kind != "rag":
        exclusion = record.run_kind
    elif not configuration.strip():
        exclusion = "missing_run_configuration"
    elif reported_configuration is None:
        exclusion = "missing_reported_configuration"
    elif "variant" in run and not run["variant"]:
        exclusion = "missing_run_variant"
    elif not variant:
        exclusion = "missing_recorded_variant"
    elif not rewrite or ("rewrite_enabled" in run and not run["rewrite_enabled"]):
        exclusion = "missing_recorded_rewrite"
    elif rewrite == "true":
        exclusion = "rewrite_enabled"
    elif not retrieval:
        exclusion = "missing_retrieval_stage"
    elif retrieval[0] != "ok":
        exclusion = "retrieval_" + retrieval[0]
    else:
        exclusion = ""
    return {
        "configuration": configuration,
        "variant": variant,
        "rewrite_enabled": rewrite,
        "comparison_exclusion_reason": exclusion,
    }


async def _score(row, attempt, cases, runs, scorer, seen_run_ids: set[str]):
    if not isinstance(attempt, dict):
        raise InputError("invalid_attempt")
    if not isinstance(row["case_id"], str) or not row["case_id"].strip():
        raise InputError("invalid_case_id")
    case = cases.get(row["case_id"])
    if not case:
        raise InputError("unknown_case")
    if attempt.get("record") is None:
        row.update(status="skipped", reason="no_run_record")
        return
    record = RunRecord.model_validate(attempt["record"])
    run = runs.get(record.run_id)
    if run is None or run["case_id"] != row["case_id"]:
        raise InputError("run_case_mismatch")
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
    row.update(_comparison_metadata(record, run, attempt.get("configuration")))
    row.update(
        run_kind=record.run_kind,
        versions_json=json.dumps(
            record.options.versions, sort_keys=True, ensure_ascii=False
        ),
        run_started_at_utc=_started_at_utc(record, run),
    )
    if record.response.status != "answered":
        row.update(status="skipped", reason="response_" + record.response.status)
        return
    if run.get("status") and run["status"] != record.response.status:
        raise InputError("run_status_mismatch")
    sample = metric_input(record)
    if record.run_id in seen_run_ids:
        raise InputError("duplicate_run_id")
    seen_run_ids.add(record.run_id)
    if scorer is None:
        row.update(status="skipped", reason="validate_only")
        return
    try:
        result = await scorer(**sample)
    except JudgeError as error:
        row.update(status="scorer_error", reason=str(error))
        return
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
    if not isinstance(attempts, list):
        raise ValueError("evaluation.json must contain a list of attempts")
    required = {
        "dataset_id",
        "case_id",
        "question",
        "district",
        "dong",
        "conditions_json",
    }
    with _archive_rows(cases_csv, required) as reader:
        cases = list(reader)
    by_id = {case["case_id"]: case for case in cases}
    datasets = {case["dataset_id"] for case in cases}
    if len(by_id) != len(cases) or len(datasets) != 1 or not all(datasets):
        raise ValueError("expected unique cases from one dataset")
    dataset_id = datasets.pop()
    runs = _load_runs(archive, dataset_id)
    if case_id is not None and not any(
        isinstance(a, dict) and a.get("case_id") == case_id for a in attempts
    ):
        raise ValueError("no matching attempt")
    evaluation_id = uuid4().hex
    ragas_version = version("ragas")
    output.mkdir(parents=True, exist_ok=False)
    seen_run_ids: set[str] = set()
    ok = True
    with (output / "scores.csv").open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        for index, attempt in enumerate(attempts, 1):
            fields = attempt if isinstance(attempt, dict) else {}
            if case_id is not None and fields.get("case_id") != case_id:
                continue
            start = perf_counter()
            row = {
                "evaluation_id": evaluation_id,
                "attempt_index": index,
                "case_id": fields.get("case_id")
                if isinstance(fields.get("case_id"), str)
                else None,
                "run_id": fields.get("run_id")
                if isinstance(fields.get("run_id"), str)
                else None,
                "reported_configuration": fields.get("configuration")
                if isinstance(fields.get("configuration"), str)
                else None,
                "dataset_id": dataset_id,
                "metric": "faithfulness",
                "ragas_version": ragas_version,
                "judge_model": judge_model,
            }
            try:
                await _score(row, attempt, by_id, runs, scorer, seen_run_ids)
            except InputError as error:
                row.update(status="input_error", reason=str(error))
            except ValidationError:
                row.update(status="input_error", reason="invalid_run_record")
            if row["status"] != "scored":
                row["comparison_exclusion_reason"] = row["reason"]
            row["comparison_eligible"] = (
                "false" if row["comparison_exclusion_reason"] else "true"
            )
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
