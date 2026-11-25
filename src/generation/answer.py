"""Answer generation contract and response policy for supplied evidence."""

import re
from collections.abc import Callable
from copy import deepcopy
from html import unescape
from typing import Literal, NotRequired, TypedDict, TypeGuard

# Source links travel in citations. The response body contains prose and excerpts.
_LINK_MARKUP = re.compile(
    r"""[a-z][a-z0-9+.-]*:// | mailto: | tel: | www\.(?=[a-z0-9]) | //[a-z0-9\[]
        | \]\( | ^[ \t>]*\[[^\]\n]+\][ \t]*:
        | </?[a-z][a-z0-9-]*(?=[\s/>])""",
    re.IGNORECASE | re.MULTILINE | re.VERBOSE,
)
_SOURCE_ALIASES = {"document_id", "attachment_id", "pdf_sha256", "source_url"}
_SOURCE_QUALIFIERS = {"attachment_id", "parent_mst", "pdf_sha256", "document_version"}


class Evidence(TypedDict):
    source: dict[str, str]
    text: str
    chunk_id: str | None
    chunk_id_status: NotRequired[str]
    scope_type: NotRequired[Literal["district", "common", "unknown"]]
    districts: NotRequired[list[str]]
    conditions: NotRequired[list[str]]


class AnswerInput(TypedDict):
    original_question: str
    conditions: dict[str, object]
    evidence: list[Evidence] | None
    required_conditions: NotRequired[dict[str, str]]


class GenerationInput(TypedDict):
    original_question: str
    conditions: dict[str, object]
    evidence: list[Evidence]


class ConflictSide(TypedDict):
    evidence_index: int
    excerpt: str


class AnswerDraft(TypedDict):
    """The provider drafts link-free prose and describes conflicts with exact excerpts."""

    status: Literal["answered", "insufficient_evidence", "source_conflict"]
    message: NotRequired[str]
    citation_indices: NotRequired[list[int]]
    conflict_sides: NotRequired[list[ConflictSide]]


class AnswerOutput(TypedDict):
    status: Literal["answered", "needs_clarification", "insufficient_evidence", "error"]
    message: str
    citations: list[dict[str, str | None]]
    error_kind: NotRequired[str]


def generate_answer(
    request: AnswerInput,
    draft_answer: Callable[[GenerationInput], AnswerDraft],
) -> AnswerOutput | None:
    """Return None while waiting for evidence and an answer after search.

    Completed requests may declare required condition keys and display labels
    in required_conditions. The provider receives the question verbatim, its
    conditions, and the eligible evidence. Citation indices are zero-based
    indices into that evidence list. Callers keep None out of answer scoring.
    """
    if not isinstance(request, dict) or "evidence" not in request:
        return _error("invalid_input")
    question = request.get("original_question")
    conditions = request.get("conditions")
    required = request.get("required_conditions", {})
    if (
        not _nonempty_text(question)
        or not isinstance(conditions, dict)
        or not isinstance(required, dict)
        or not all(
            _nonempty_text(key) and _nonempty_text(label)
            for key, label in required.items()
        )
    ):
        return _error("invalid_input")

    evidence = request["evidence"]
    if evidence is None:
        return None
    if not isinstance(evidence, list) or not all(
        _valid_evidence(entry) for entry in evidence
    ):
        return _error("invalid_input")

    missing_labels = [
        label
        for key, label in required.items()
        if _condition_missing(conditions.get(key))
    ]
    if missing_labels:
        return {
            "status": "needs_clarification",
            "message": f"다음 정보를 알려 주세요. {', '.join(missing_labels)}",
            "citations": [],
        }
    if not evidence:
        return _insufficient_evidence()

    generation_input: GenerationInput = {
        "original_question": question,
        "conditions": conditions,
        "evidence": evidence,
    }
    model_input = deepcopy(generation_input)
    # Resolve citations from the input snapshot even if the adapter edits its copy.
    try:
        draft = draft_answer(deepcopy(model_input))
    except Exception:
        return _error("generation_failed")

    if not isinstance(draft, dict):
        return _error("invalid_draft")
    status = draft.get("status")
    if status == "source_conflict":
        return _respond_to_conflict(
            draft.get("conflict_sides"), model_input["evidence"]
        )
    if status == "insufficient_evidence":
        return _insufficient_evidence()

    message = draft.get("message")
    indices = draft.get("citation_indices")
    # 답변 형식을 먼저 확인하고, 인용 문제는 평가에서 '잘못된 인용'으로 나눌 수 있게
    # 별도 이유로 남긴다.
    if status != "answered" or not _link_free_prose(message):
        return _error("invalid_draft")
    if not isinstance(indices, list) or not indices:
        return _error("missing_citation")
    if not all(_valid_index(index, model_input["evidence"]) for index in indices):
        return _error("invalid_citation")
    return {
        "status": "answered",
        "message": message,
        "citations": [
            _citation(model_input["evidence"][index])
            for index in dict.fromkeys(indices)
        ],
    }


def _respond_to_conflict(sides: object, evidence: list[Evidence]) -> AnswerOutput:
    if not isinstance(sides, list) or len(sides) < 2:
        return _error("invalid_draft")

    excerpts: list[str] = []
    citations: list[dict[str, str | None]] = []
    identities: list[dict[str, str]] = []
    for side in sides:
        if not isinstance(side, dict):
            return _error("invalid_draft")
        index = side.get("evidence_index")
        excerpt = side.get("excerpt")
        if not isinstance(excerpt, str):
            return _error("invalid_draft")
        if not _valid_index(index, evidence):
            return _error("invalid_citation")
        entry = evidence[index]
        excerpt = excerpt.strip()
        identity = _source_identity(entry["source"])
        if (
            any(_same_source(identity, previous) for previous in identities)
            or not _link_free_prose(excerpt)
            or excerpt not in entry["text"]
        ):
            return _error("invalid_draft")
        identities.append(identity)
        excerpts.append(excerpt)
        citations.append(_citation(entry))

    if len(set(excerpts)) < 2:
        return _error("invalid_draft")

    details = "\n".join(
        f"[{number}] {excerpt}" for number, excerpt in enumerate(excerpts, start=1)
    )
    return {
        "status": "insufficient_evidence",
        "message": (
            "확인한 출처의 안내가 서로 다릅니다.\n"
            f"{details}\n"
            "현재 적용되는 내용을 하나로 확정하기 어렵습니다."
        ),
        "citations": citations,
    }


def _source_identity(source: dict[str, str]) -> dict[str, str]:
    identity = {}
    for field in _SOURCE_ALIASES | _SOURCE_QUALIFIERS | {"evidence_file"}:
        value = source.get(field, "").strip()
        if field == "source_url":
            # Fragment identifiers locate passages in the same source.
            value = value.partition("#")[0]
        if field == "pdf_sha256":
            value = value.lower()
        if value:
            identity[field] = value
    return identity


def _same_source(left: dict[str, str], right: dict[str, str]) -> bool:
    """Compare supplied identities across metadata shapes and qualified versions."""
    shared_fields = left.keys() & right.keys()
    if any(
        field in shared_fields and left[field] != right[field]
        for field in _SOURCE_QUALIFIERS
    ):
        return False
    if any(
        field in shared_fields and left[field] == right[field]
        for field in _SOURCE_ALIASES
    ):
        return True
    if left.keys() & _SOURCE_ALIASES and right.keys() & _SOURCE_ALIASES:
        return False
    # Use a filename as a fallback when at least one record lacks a stronger alias.
    return (
        "evidence_file" in shared_fields
        and left["evidence_file"] == right["evidence_file"]
    )


def _condition_missing(value: object) -> bool:
    return (
        value is None or value == [] or (isinstance(value, str) and not value.strip())
    )


def _valid_evidence(entry: object) -> bool:
    if not isinstance(entry, dict) or "chunk_id" not in entry:
        return False
    source = entry.get("source")
    chunk_id = entry["chunk_id"]
    return (
        isinstance(source, dict)
        and _nonempty_text(source.get("source_location"))
        and all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in source.items()
        )
        and bool(
            _source_identity(source).keys() & (_SOURCE_ALIASES | {"evidence_file"})
        )
        and _nonempty_text(entry.get("text"))
        and (chunk_id is None or _nonempty_text(chunk_id))
    )


def _link_free_prose(value: object) -> TypeGuard[str]:
    return _nonempty_text(value) and _LINK_MARKUP.search(unescape(value)) is None


def _nonempty_text(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and bool(value.strip())


def _valid_index(index: object, evidence: list[Evidence]) -> TypeGuard[int]:
    return type(index) is int and 0 <= index < len(evidence)


def _citation(evidence: Evidence) -> dict[str, str | None]:
    citation: dict[str, str | None] = dict(evidence["source"])
    citation["chunk_id"] = evidence["chunk_id"]
    citation.pop("chunk_id_status", None)
    if evidence["chunk_id"] is None:
        citation["chunk_id_status"] = "unconfirmed"
    return citation


def _insufficient_evidence() -> AnswerOutput:
    return {
        "status": "insufficient_evidence",
        "message": "현재 확인한 자료로는 답변하기 어렵습니다.",
        "citations": [],
    }


def _error(kind: str) -> AnswerOutput:
    return {
        "status": "error",
        "message": "답변을 준비하는 중 오류가 발생했습니다.",
        "citations": [],
        "error_kind": kind,
    }
