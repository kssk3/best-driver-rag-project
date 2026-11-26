"""Draft answers for the controlled, offline fixed-evidence experiment."""

import json
import re
from collections.abc import Mapping
from html import unescape
from typing import TypeGuard

from src.contracts import PipelineRequest
from src.generation.answer import AnswerDraft, ConflictSide, Evidence, GenerationInput

_COLOR_ROW = re.compile(r"[\w·]+ \w+색")
_COLOR_DOCUMENT_ID = "seodaemun-rules:attachment:160561037"
_COLOR_SCOPE = "공동주택 일반용기 설치 기준"
_IMAGE_SUMMARY = re.compile(
    r'<aside data-review-overlay="image-summary">([^<]*)</aside>\s*$'
)
_EVIDENCE_ITEMS_JSON = "evidence_items_json"


def _is_item_list(value: object) -> TypeGuard[list[str]]:
    return isinstance(value, list) and all(
        isinstance(item, str) and item.strip() for item in value
    )


def make_evidence_request(
    question: str, *, district: str, conditions: Mapping[str, object]
) -> PipelineRequest:
    """Use a reserved field for the observation's list in the string-only request."""
    encoded = {}
    for key, value in conditions.items():
        if key == _EVIDENCE_ITEMS_JSON:
            raise ValueError("The source evidence item encoding field is reserved")
        if key == "items" and _is_item_list(value):
            encoded[_EVIDENCE_ITEMS_JSON] = json.dumps(value, ensure_ascii=False)
        elif isinstance(value, str):
            encoded[key] = value
        else:
            raise ValueError(f"Unsupported source evidence condition: {key}")
    dong = encoded.pop("dong", None)
    return PipelineRequest(
        question=question, district=district, dong=dong, conditions=encoded
    )


def decode_evidence_conditions(conditions: Mapping[str, str]) -> dict[str, object]:
    """Decode the explicit source evidence item list and pass ordinary strings through."""
    decoded: dict[str, object] = dict(conditions)
    if _EVIDENCE_ITEMS_JSON in conditions:
        items = json.loads(conditions[_EVIDENCE_ITEMS_JSON])
        if "items" in conditions or not _is_item_list(items):
            raise ValueError("Invalid source evidence item list")
        del decoded[_EVIDENCE_ITEMS_JSON]
        decoded["items"] = items
    return decoded


def _reviewed_colors(evidence: Evidence) -> list[str]:
    source = evidence["source"]
    if (
        source.get("document_id") != _COLOR_DOCUMENT_ID
        or evidence.get("scope_type") != "district"
        or "서대문구" not in evidence.get("districts", [])
    ):
        return []

    try:
        if source.get("content_format") == "json":
            data = json.loads(evidence["text"])
            summary = (
                data.get("structured_image_summary") if isinstance(data, dict) else None
            )
        elif source.get("content_format") == "html":
            match = _IMAGE_SUMMARY.search(evidence["text"])
            summary = json.loads(unescape(match[1])) if match else None
        else:
            return []
    except json.JSONDecodeError:
        return []

    if (
        not isinstance(summary, dict)
        or summary.get("applicability") != _COLOR_SCOPE
        or not isinstance(summary.get("validation"), str)
        or not summary["validation"].strip()
        or not isinstance(summary.get("colors"), list)
    ):
        return []

    rows = {}
    for entry in summary["colors"]:
        if not isinstance(entry, dict):
            return []
        item, color = entry.get("item"), entry.get("color")
        if not isinstance(item, str) or not isinstance(color, str):
            return []
        if item in rows or not _COLOR_ROW.fullmatch(f"{item} {color}"):
            return []
        rows[item] = color
    return [f"{item} {color}" for item, color in rows.items()]


def draft_evidence_answer(payload: GenerationInput) -> AnswerDraft:
    """Use only passages with a scope and format recognized by the source evidence probe."""
    conditions = payload["conditions"]
    question = payload["original_question"]
    housing = conditions.get("housing_type")
    container = conditions.get("container_type")
    if isinstance(housing, str) and isinstance(container, str):
        if housing in question and container in question:
            heading = f'합성: {housing} "{container}" 기준'
            reviewed_scope = (
                conditions.get("district") == "서대문구"
                and f"{housing} {container} 설치 기준" == _COLOR_SCOPE
                and "색" in question
            )
            for index, evidence in enumerate(payload["evidence"]):
                if reviewed_scope and (reviewed_rows := _reviewed_colors(evidence)):
                    return {
                        "status": "answered",
                        "message": f"{_COLOR_SCOPE}은 {', '.join(reviewed_rows)}입니다.",
                        "citation_indices": [index],
                    }
                title, _, body = evidence["text"].partition("\n")
                rows = body.split(", ")
                if title == heading and all(_COLOR_ROW.fullmatch(row) for row in rows):
                    return {
                        "status": "answered",
                        "message": f"{housing} {container} 기준은 {', '.join(rows)}입니다.",
                        "citation_indices": [index],
                    }

    item = conditions.get("item")
    if isinstance(item, str) and item and item in question:
        heading = f"합성: {item} 배출 기준"
        for index, evidence in enumerate(payload["evidence"]):
            title, _, body = evidence["text"].partition("\n")
            if title == heading and body.strip():
                return {
                    "status": "answered",
                    "message": body.strip(),
                    "citation_indices": [index],
                }

    dong = conditions.get("dong")
    if isinstance(dong, str) and isinstance(housing, str):
        if dong in question and housing in question:
            prefix = f"합성: {dong} {housing}의 일반·음식물 배출요일은 "
            sides: list[ConflictSide] = []
            schedules = set()
            for index, evidence in enumerate(payload["evidence"]):
                text = evidence["text"]
                if text.startswith(prefix) and (
                    days := text.removeprefix(prefix).strip()
                ):
                    sides.append({"evidence_index": index, "excerpt": text})
                    schedules.add(days)
            if len(schedules) > 1:
                return {"status": "source_conflict", "conflict_sides": sides}

    return {"status": "insufficient_evidence"}
