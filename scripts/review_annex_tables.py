"""전처리 별표에서 원문 대조가 필요한 표 후보를 JSON으로 출력한다."""

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from src.ingestion.search_preparation import (
    PreparedCell,
    PreparedRow,
    prepare_table_rows,
    validate_table_row_continuations,
)

_NEW_ENTRY = re.compile(r"^(?:[0-9]+[.)]|[가-힣][.)]|[※＊*○●]|비\s*고\s*[:：])")
_HANGUL_BREAK = re.compile(r"(?<=[가-힣])[ \t]*\r?\n[ \t]*(?=[가-힣])")
_UNIT_LABEL = re.compile(
    r"\(?\s*단\s*위\s*[:：]|\(\s*(?:천\s*원|원|[kK][gG]|㎏|ℓ|[lL]|㎡|㎥|[%％])\s*\)"
)
_NOTE_LABEL = re.compile(r"^(?:[※＊*]|비\s*고\s*(?:[:：]|[0-9]+[.)]))")


def _cell_location(row: PreparedRow, cell: PreparedCell) -> dict:
    return {
        "row": row["row"],
        "row_id": row["row_id"],
        "cell_id": cell["cell_id"],
        "origin_row": cell["origin_row"],
        "origin_col": cell["origin_col"],
        "rowspan": cell["rowspan"],
        "colspan": cell["colspan"],
        "text": cell["text"],
    }


def _row_boundary_candidates(
    rows: list[PreparedRow], header_count: int, reviewed_rows: set[int]
) -> list[dict]:
    candidates = []
    group = []
    anchor_other_ids = set()
    for row in [*rows[header_count:], None]:
        first = None
        other_ids = set()
        if row is not None and row["row"] not in reviewed_rows:
            first = next(
                (
                    cell
                    for cell in row["cell_values"]
                    if cell["origin_col"] == 0
                    and not cell["inherited_from_previous_row"]
                    and cell["rowspan"] == cell["colspan"] == 1
                    and cell["text"].strip()
                ),
                None,
            )
            other_ids = {
                cell["cell_id"]
                for cell in row["cell_values"]
                if cell["origin_col"] != 0 and cell["text"].strip()
            }
        if (
            row is not None
            and first is not None
            and group
            and other_ids <= anchor_other_ids
            and not _NEW_ENTRY.match(first["text"].lstrip())
        ):
            group.append(_cell_location(row, first))
            continue
        if len(group) > 1:
            candidates.append(
                {
                    "kind": "first_column_continuation",
                    "clue": "연속된 독립 첫 열 셀, 후속 행에 새 비어 있지 않은 열 없음",
                    "cells": group,
                }
            )
        group = (
            [_cell_location(row, first)]
            if row is not None and first is not None
            else []
        )
        anchor_other_ids = other_ids
    return candidates


def _cell_candidates(rows: list[PreparedRow], header_count: int) -> list[dict]:
    candidates = []
    for row in rows:
        for cell in row["cell_values"]:
            if cell["inherited_from_previous_row"] or not cell["text"].strip():
                continue
            text = cell["text"]
            for change in cell["normalization_changes"]:
                if change["kind"] == "join_known_term":
                    text = text.replace(change["before"], change["after"], 1)
            if _HANGUL_BREAK.search(text):
                candidates.append(
                    {
                        "kind": "cell_line_break",
                        "clue": "확인된 복원 용어 외 한글 사이 줄바꿈",
                        "cells": [_cell_location(row, cell)],
                    }
                )
            if (
                row["row"] < header_count
                and (cell["rowspan"] > 1 or cell["colspan"] > 1)
                and _UNIT_LABEL.search(cell["text"])
            ):
                candidates.append(
                    {
                        "kind": "merged_header_unit",
                        "clue": "병합 머리글의 단위가 각 하위 열에 적용되는지 원문 대조",
                        "cells": [_cell_location(row, cell)],
                    }
                )
    return candidates


def _nearby_context(blocks: list[dict], table_block: int) -> list[dict]:
    section = blocks[table_block].get("section_title")
    candidates = []
    for direction in (-1, 1):
        for position in range(
            table_block + direction, table_block + 5 * direction, direction
        ):
            if not 0 <= position < len(blocks):
                break
            block = blocks[position]
            if block.get("section_title") != section or block.get("type") == "table":
                break
            text = block.get("text", "").strip()
            if _NOTE_LABEL.match(text) or _UNIT_LABEL.match(text):
                candidates.append(
                    {
                        "kind": "nearby_source_note",
                        "clue": "인접 문단의 각주·단위가 표에 적용되는지 원문 대조",
                        "block_index": position,
                        "text": block["text"],
                    }
                )
    return sorted(candidates, key=lambda candidate: candidate["block_index"])


def review_annex_tables(manifest_path: Path) -> dict:
    """원문·검수 기록·전처리 데이터를 읽기 전용으로 검사한다."""
    manifest_path = manifest_path.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or not isinstance(manifest.get("records"), list):
        raise ValueError("첨부 처리 manifest의 records 목록 필요")

    attachments = tables = reviewed_groups = 0
    counts: Counter[str] = Counter()
    candidates = []
    seen = set()
    for entry in manifest["records"]:
        if not isinstance(entry, dict):
            raise ValueError("첨부 처리 manifest의 record는 객체여야 합니다.")
        filename = entry.get("output_file")
        if filename is None:
            continue
        if (
            not isinstance(filename, str)
            or Path(filename).name != filename
            or Path(filename).suffix != ".json"
            or filename in seen
        ):
            raise ValueError("첨부 output_file은 중복 없는 JSON 파일명이어야 합니다.")
        seen.add(filename)
        path = manifest_path.parent / filename
        if path.resolve().parent != manifest_path.parent:
            raise ValueError(f"{filename}: 첨부 처리 폴더 밖의 파일 참조")
        record = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(record, dict) or any(
            not record.get(field) or record[field] != entry.get(field)
            for field in ("parent_mst", "attachment_id", "raw_sha256")
        ):
            raise ValueError(f"{filename}: 첨부 식별자 또는 원본 해시 불일치")
        attachments += 1
        reviewed_tables = record.get("table_row_continuations", {})
        if reviewed_tables:
            try:
                validate_table_row_continuations(record["tables"], reviewed_tables)
            except ValueError as error:
                raise ValueError(f"{filename}: {error}") from error
        blocks = record["blocks"]
        table_blocks = {
            block["table_id"]: position
            for position, block in enumerate(blocks)
            if block["type"] == "table"
        }
        for table in record["tables"]:
            tables += 1
            table_id = table["table_id"]
            try:
                rows = prepare_table_rows(table)
            except ValueError as error:
                raise ValueError(f"{filename} {table_id}: {error}") from error
            header_count = max(
                (cell["rowspan"] for cell in rows[0]["cell_values"]), default=1
            )
            reviewed = reviewed_tables.get(table_id, [])
            reviewed_groups += len(reviewed)
            reviewed_rows = {row for group in reviewed for row in group["source_rows"]}
            location = {
                "file": filename,
                "parent_mst": record["parent_mst"],
                "attachment_id": record["attachment_id"],
                "district": record.get("district"),
                "source_url": record.get("source_url"),
                "raw_path": record.get("raw_path"),
                "raw_sha256": record["raw_sha256"],
                "extracted_xml": record.get("extracted_xml"),
                "table_id": table_id,
                "table_block_index": table_blocks.get(table_id),
                "section_title": table.get("section_title"),
            }
            findings = [
                *_row_boundary_candidates(rows, header_count, reviewed_rows),
                *_cell_candidates(rows, header_count),
            ]
            if table_id in table_blocks:
                findings.extend(_nearby_context(blocks, table_blocks[table_id]))
            for finding in findings:
                counts[finding["kind"]] += 1
                candidates.append(
                    {**location, "status": "needs_source_review", **finding}
                )
    return {
        "use": "manual_review_only",
        "coordinate_base": 0,
        "attachments_scanned": attachments,
        "tables_scanned": tables,
        "already_reviewed_row_groups": reviewed_groups,
        "candidate_counts": dict(sorted(counts.items())),
        "candidates": candidates,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="전처리 annex_manifest.json 경로")
    args = parser.parse_args()
    try:
        report = review_annex_tables(args.manifest)
    except (OSError, ValueError) as error:
        parser.exit(1, f"별표 검수 후보 확인 실패: {error}\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
