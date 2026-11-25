"""검색용 단어 복원과 병합 셀의 행별 연결 검사."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from src.ingestion.search_preparation import normalize_search_text, prepare_table_rows


def test_restores_explicit_chemical_term_and_keeps_source_text():
    original = "6. 무색 폴리\n   에틸렌테레프\n   탈레이트   \n   (PET)병"
    result = normalize_search_text(original)
    assert result["text"] == "6. 무색 폴리에틸렌테레프탈레이트 (PET)병"
    assert result["changes"][0] == {
        "kind": "join_known_term",
        "before": "폴리\n   에틸렌테레프\n   탈레이트",
        "after": "폴리에틸렌테레프탈레이트",
    }
    assert "폴리\n   에틸렌테레프\n   탈레이트" in original


def test_does_not_glue_unlisted_paragraph_boundaries():
    result = normalize_search_text("주소\n전화 : 1234\n다만, 공동\n주택에 적용")
    assert result["text"] == "주소 전화 : 1234 다만, 공동주택에 적용"
    assert "주소전화" not in result["text"]
    assert "다만," in result["text"]
    term_changes = [c for c in result["changes"] if c["kind"] == "join_known_term"]
    assert term_changes == [
        {"kind": "join_known_term", "before": "공동\n주택", "after": "공동주택"}
    ]


@pytest.mark.parametrize("text", ["", "신문지", "종이 또는 종이팩"])
def test_already_normalized_text_has_no_change_log(text):
    assert normalize_search_text(text) == {"text": text, "changes": []}


def test_repeated_merge_uses_parent_item_in_newspaper_row_without_mutation():
    path = Path(__file__).resolve().parents[3] / (
        "data/handoff/jungeun/ordinance-handoff-2026-11-24/processed/annex/2101297_160319453.json"
    )
    table = json.loads(path.read_text(encoding="utf-8"))["tables"][0]
    original = deepcopy(table)
    rows = prepare_table_rows(table)
    row = next(row for row in rows if "신문지" in row["search_text"])
    parent = next(c for c in row["cell_values"] if c["origin_col"] == 0)
    assert parent["text"] == "2. 골판지 외 종이류"
    assert parent["cell_id"] == "table-1-r2-c0"
    assert parent["origin_row"] == 2
    assert parent["columns"] == [0]
    assert parent["inherited_from_previous_row"] is True
    assert "2. 골판지 외 종이류 | · 신문지" in row["search_text"]
    assert row["context_ref"] == "attachment.blocks"
    assert row["context_required"] is True
    assert table == original


def merged_table():
    return {
        "table_id": "table-1",
        "rows": 2,
        "cols": 3,
        "cells": [
            {
                "cell_id": "parent",
                "row": 0,
                "col": 0,
                "rowspan": 2,
                "colspan": 1,
                "text": "합성\n수지류",
                "paragraphs": ["합성\n수지류"],
            },
            {
                "cell_id": "wide",
                "row": 0,
                "col": 1,
                "rowspan": 1,
                "colspan": 2,
                "text": "공동\n주택",
            },
            {
                "cell_id": "note",
                "row": 1,
                "col": 1,
                "rowspan": 1,
                "colspan": 1,
                "text": "주소\n전화",
            },
        ],
        "row_cell_ids": [["parent", "wide", "wide"], ["parent", "note", None]],
    }


def test_colspan_deduplicates_source_cell_and_keeps_missing_coordinates():
    table = merged_table()
    original = deepcopy(table)
    rows = prepare_table_rows(table)
    assert len(rows[0]["cell_values"]) == 2
    assert rows[0]["cell_values"][1]["columns"] == [1, 2]
    assert rows[0]["search_text"] == "합성수지류 | 공동주택"
    assert rows[1]["missing_columns"] == [2]
    assert rows[1]["cell_values"][0]["text"] == "합성\n수지류"
    assert rows[1]["search_text"] == "합성수지류 | 주소 전화"
    assert table == original


@pytest.mark.parametrize("replacement", ["missing-cell", "wide"])
def test_bad_row_reference_fails_instead_of_silently_losing_context(replacement):
    table = merged_table()
    table["row_cell_ids"][1][0] = replacement
    with pytest.raises(ValueError):
        prepare_table_rows(table)
