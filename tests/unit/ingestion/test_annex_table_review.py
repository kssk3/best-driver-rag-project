"""별표 검수 후보가 원문 행·셀과 기존 검수 상태를 보존하는지 확인한다."""

import json
from pathlib import Path

import pytest

from scripts.review_annex_tables import review_annex_tables

_ANNEX_FOLDER = (
    Path(__file__).resolve().parents[3]
    / "data/handoff/jungeun/ordinance-handoff-2026-11-24/processed/annex"
)
_MANIFEST = _ANNEX_FOLDER / "annex_manifest.json"


def _rows(finding):
    return [cell["row"] for cell in finding["cells"]]


def test_review_reports_candidates_without_superseding_human_review():
    report = review_annex_tables(_MANIFEST)

    assert report["use"] == "manual_review_only"
    assert report["coordinate_base"] == 0
    assert report["attachments_scanned"] == 19
    assert report["tables_scanned"] == 32
    assert report["already_reviewed_row_groups"] == 8
    assert all(
        finding["status"] == "needs_source_review"
        and finding["source_url"]
        and finding["raw_sha256"]
        for finding in report["candidates"]
    )
    continuations = [
        finding
        for finding in report["candidates"]
        if finding["kind"] == "first_column_continuation"
    ]
    assert not any(f["attachment_id"] == "121237861" for f in continuations)
    assert not any(
        f["attachment_id"] == "160561049"
        and f["table_id"] == "table-1"
        and set(_rows(f)) & {10, 11}
        for f in continuations
    )
    assert any(
        f["attachment_id"] == "121237861"
        and f["kind"] == "merged_header_unit"
        and f["cells"][0]["cell_id"] == "table-3-r0-c1"
        for f in report["candidates"]
    )
    assert any(
        f["attachment_id"] == "154690991"
        and f["kind"] == "nearby_source_note"
        and f["block_index"] == 6
        for f in report["candidates"]
    )


def test_original_reward_rows_are_review_candidates_without_overlay(tmp_path):
    filename = "1481479_121237861.json"
    original = json.loads((_ANNEX_FOLDER / filename).read_text(encoding="utf-8"))
    groups = original.pop("table_row_continuations")["table-3"]
    record_path = tmp_path / filename
    record_path.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
    manifest_path = tmp_path / "annex_manifest.json"
    source_data = {
        field: original[field]
        for field in ("parent_mst", "attachment_id", "raw_sha256")
    }
    manifest_path.write_text(
        json.dumps({"records": [{**source_data, "output_file": filename}]}),
        encoding="utf-8",
    )
    original_bytes = record_path.read_bytes()

    report = review_annex_tables(manifest_path)

    assert record_path.read_bytes() == original_bytes
    matches = [
        finding
        for finding in report["candidates"]
        if finding["table_id"] == "table-3"
        and finding["kind"] == "first_column_continuation"
    ]
    assert [_rows(finding) for finding in matches] == [
        group["source_rows"] for group in groups
    ]
    assert [[cell["cell_id"] for cell in finding["cells"]] for finding in matches] == [
        group["source_cell_ids"] for group in groups
    ]
    assert matches[0]["cells"][2]["text"] == "자(법 제8조제1항 또는 제2항)"


@pytest.mark.parametrize(
    ("filename", "table_id", "stored_rows", "error_field"),
    [
        ("2053883_154690991.json", "table-1", "missing", None),
        ("2053883_154690991.json", "table-1", "invalid_log", "normalization_changes"),
        ("1481479_121237861.json", "table-3", "invalid_rows", "rows_for_search"),
    ],
)
def test_review_checks_persisted_search_history_but_accepts_old_tables(
    tmp_path, filename, table_id, stored_rows, error_field
):
    original = json.loads((_ANNEX_FOLDER / filename).read_text(encoding="utf-8"))
    table = next(table for table in original["tables"] if table["table_id"] == table_id)
    if stored_rows == "missing":
        del table["rows_for_search"]
    elif stored_rows == "invalid_log":
        table["rows_for_search"][0]["cell_values"][0]["normalization_changes"] = None
    else:
        table["rows_for_search"] = None
    (tmp_path / filename).write_text(json.dumps(original), encoding="utf-8")
    manifest_path = tmp_path / "annex_manifest.json"
    source_data = {
        field: original[field]
        for field in ("parent_mst", "attachment_id", "raw_sha256")
    }
    manifest_path.write_text(
        json.dumps({"records": [{**source_data, "output_file": filename}]}),
        encoding="utf-8",
    )

    if error_field is None:
        assert review_annex_tables(manifest_path)["tables_scanned"] == 1
    else:
        with pytest.raises(ValueError, match=f"{filename} {table_id}.*{error_field}"):
            review_annex_tables(manifest_path)
