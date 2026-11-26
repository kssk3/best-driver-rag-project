"""Write local answer experiment records as a pair of UTF-8 CSV files."""

import csv
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from os.path import lexists
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from src.generation.answer import AnswerOutput, Evidence


@dataclass(frozen=True)
class Candidate:
    rank: int
    evidence: Evidence
    score: float | None = None


@dataclass(frozen=True)
class ModelInput:
    rank: int
    evidence: Evidence


@dataclass(frozen=True, kw_only=True)
class Run:
    run_id: str
    question_id: str
    attempt: int
    experiment_kind: Literal["synthetic", "actual"]
    case_group: Literal["development", "observation"]
    original_question: str
    conditions: dict[str, object]
    candidates: Sequence[Candidate] | None
    model_inputs: Sequence[ModelInput]
    answer: AnswerOutput | None
    retriever: str | None = None
    corpus_snapshot_id: str | None = None
    config_version: str | None = None
    retrieval_ms: float | None = None
    response_ms: float | None = None
    evaluation_ms: float | None = None
    evaluation_score: float | None = None
    retrieval_only: bool = False
    retrieval_error_kind: str | None = None


_RUN_COLUMNS = (
    "run_id",
    "question_id",
    "attempt",
    "experiment_kind",
    "case_group",
    "original_question",
    "conditions_json",
    "district",
    "retriever",
    "corpus_snapshot_id",
    "config_version",
    "run_state",
    "candidate_count",
    "status",
    "answer",
    "model_inputs_json",
    "citations_json",
    "error_kind",
    "retrieval_ms",
    "response_ms",
    "evaluation_ms",
    "evaluation_score",
)
_SOURCE_COLUMNS = (
    "document_id",
    "parent_mst",
    "attachment_id",
    "source_type",
    "source_url",
    "evidence_file",
    "pdf_sha256",
    "source_location",
)
_CANDIDATE_COLUMNS = (
    "run_id",
    "question_id",
    "case_group",
    "experiment_kind",
    "rank",
    "chunk_id",
    *_SOURCE_COLUMNS,
    "source_json",
    "text",
    "retrieval_score",
    "used_in_model_input",
    "cited_in_answer",
)
_ANSWER_STATUSES = {"answered", "needs_clarification", "insufficient_evidence", "error"}


def save_experiment_csv(directory: Path, runs: Iterable[Run]) -> None:
    """Write both CSVs to a new directory dedicated to one export batch.

    Supply one unique run_id per attempt and the original ranked candidates.
    Use candidates=None when retrieval produced no candidate list and [] when
    it completed with zero rows. Use answer=None for pending input. Pass only
    the evidence actually sent to generation in model_inputs, in its input
    order, and use original candidate ranks to link it to the retrieval rows.
    Model input text can be a verbatim excerpt of the recorded candidate.
    For retrieval-only runs, provide the completed candidate list, or an
    error kind with no candidate list when retrieval failed. Leave answer
    and generation or evaluation fields empty.
    """
    directory = Path(directory)
    if lexists(directory):
        raise FileExistsError(directory)

    run_rows = []
    candidate_rows = []
    seen_run_ids = set()
    for run in runs:
        if run.run_id in seen_run_ids:
            raise ValueError(f"Duplicate run_id {run.run_id!r}")
        seen_run_ids.add(run.run_id)
        run_row, rows = _build_rows(run)
        run_rows.append(run_row)
        candidate_rows.extend(rows)

    directory.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=directory.parent) as temp:
        staging = Path(temp)
        _write_rows(staging / "runs.csv", _RUN_COLUMNS, run_rows)
        _write_rows(staging / "candidates.csv", _CANDIDATE_COLUMNS, candidate_rows)
        if lexists(directory):
            raise FileExistsError(directory)
        staging.rename(directory)


def _build_rows(run: Run) -> tuple[dict[str, object], list[dict[str, object]]]:
    if not run.run_id.strip() or not run.question_id.strip():
        raise ValueError("Run and question IDs must be nonempty")
    if type(run.attempt) is not int or run.attempt < 1:
        raise ValueError("Attempt must be a positive integer")
    if run.case_group not in {"development", "observation"}:
        raise ValueError(f"Unknown case group for {run.run_id!r}")
    if run.experiment_kind not in {"synthetic", "actual"}:
        raise ValueError(f"Unknown experiment kind for {run.run_id!r}")

    answer = run.answer
    run_state = "pending" if answer is None else "completed"
    if run.retrieval_only:
        if (
            answer is not None
            or run.model_inputs
            or run.response_ms is not None
            or run.evaluation_ms is not None
            or run.evaluation_score is not None
        ):
            raise ValueError(
                f"Retrieval-only run {run.run_id!r} has generation or evaluation data"
            )
        if (run.candidates is None) == (run.retrieval_error_kind is None):
            raise ValueError(
                f"Retrieval-only run {run.run_id!r} requires results or an error"
            )
        run_state = (
            "retrieval_error" if run.candidates is None else "retrieval_completed"
        )
    elif run.retrieval_error_kind is not None:
        raise ValueError(f"Unexpected retrieval error for {run.run_id!r}")
    elif answer is not None:
        status = answer["status"]
        if status not in _ANSWER_STATUSES:
            raise ValueError(f"Unknown answer status for {run.run_id!r}")
        if run.candidates is None and status != "error":
            raise ValueError(f"Missing retrieval list for {run.run_id!r}")
        if status == "answered" and not answer["citations"]:
            raise ValueError(
                f"Answered run {run.run_id!r} requires a grounded citation"
            )
    elif (
        run.model_inputs
        or run.response_ms is not None
        or run.evaluation_ms is not None
        or run.evaluation_score is not None
    ):
        raise ValueError(f"Pending run {run.run_id!r} has response or evaluation data")

    candidates_by_rank = {}
    for candidate in run.candidates or ():
        rank = candidate.rank
        if type(rank) is not int or rank < 1 or rank in candidates_by_rank:
            raise ValueError(f"Invalid or duplicate candidate rank for {run.run_id!r}")
        candidates_by_rank[rank] = candidate

    inputs_by_rank = {}
    for model_input in run.model_inputs:
        rank = model_input.rank
        matched_candidate = candidates_by_rank.get(rank)
        evidence = model_input.evidence
        if (
            type(rank) is not int
            or matched_candidate is None
            or rank in inputs_by_rank
            or _citation_identity(evidence)
            != _citation_identity(matched_candidate.evidence)
            or not evidence["text"]
            or evidence["text"] not in matched_candidate.evidence["text"]
        ):
            raise ValueError(f"Model input does not match candidate rank {rank!r}")
        inputs_by_rank[rank] = evidence

    citations = []
    for citation in answer["citations"] if answer is not None else ():
        identity = dict(citation)
        identity.pop("chunk_id_status", None)
        ranks = [
            rank
            for rank, evidence in inputs_by_rank.items()
            if _citation_identity(evidence) == identity
        ]
        if len(ranks) != 1:
            raise ValueError(
                f"Citation does not identify one model input for {run.run_id!r}"
            )
        citations.append({"rank": ranks[0], "source": citation})
    cited_ranks = {citation["rank"] for citation in citations}

    run_row = {
        "run_id": run.run_id,
        "question_id": run.question_id,
        "attempt": run.attempt,
        "experiment_kind": run.experiment_kind,
        "case_group": run.case_group,
        "original_question": run.original_question,
        "conditions_json": _json(run.conditions),
        "district": run.conditions.get("district"),
        "retriever": run.retriever,
        "corpus_snapshot_id": run.corpus_snapshot_id,
        "config_version": run.config_version,
        "run_state": run_state,
        "candidate_count": None if run.candidates is None else len(run.candidates),
        "status": None if answer is None else answer["status"],
        "answer": None if answer is None else answer["message"],
        "model_inputs_json": None
        if answer is None
        else _json(
            [{**evidence, "rank": rank} for rank, evidence in inputs_by_rank.items()]
        ),
        "citations_json": None if answer is None else _json(citations),
        "error_kind": run.retrieval_error_kind
        if answer is None
        else answer.get("error_kind"),
        "retrieval_ms": run.retrieval_ms,
        "response_ms": run.response_ms,
        "evaluation_ms": run.evaluation_ms,
        "evaluation_score": run.evaluation_score,
    }
    candidate_rows: list[dict[str, object]] = []
    for rank, candidate in candidates_by_rank.items():
        evidence = candidate.evidence
        source = evidence["source"]
        candidate_rows.append(
            {
                "run_id": run.run_id,
                "question_id": run.question_id,
                "experiment_kind": run.experiment_kind,
                "case_group": run.case_group,
                "rank": rank,
                "chunk_id": evidence["chunk_id"],
                **{field: source.get(field) for field in _SOURCE_COLUMNS},
                "source_json": _json(source),
                "text": evidence["text"],
                "retrieval_score": candidate.score,
                "used_in_model_input": "true" if rank in inputs_by_rank else "false",
                "cited_in_answer": "true" if rank in cited_ranks else "false",
            }
        )
    return run_row, candidate_rows


def _citation_identity(evidence: Evidence) -> dict[str, str | None]:
    identity: dict[str, str | None] = dict(evidence["source"])
    identity.pop("chunk_id_status", None)
    identity["chunk_id"] = evidence["chunk_id"]
    return identity


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True)


def _write_rows(
    path: Path, columns: Sequence[str], rows: Iterable[dict[str, object]]
) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
