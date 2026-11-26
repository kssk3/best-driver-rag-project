import json

import pytest

from src.ingestion.embedding_text import (
    collapse_spaced_hangul,
    row_embedding_text,
    search_text,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("세   탁   기", "세탁기"),
        ("안 마  의 자", "안마의자"),
        ("가\n전\n제\n품\n류", "가전제품류"),
        ("비 고", "비고"),  # 칸 전체가 두 글자
        ("(입)간 판", "(입)간 판"),  # 두 글자는 칸 전체일 때만
        ("책 장 (책 꽂 이)", "책장 (책꽂이)"),
        ("세탁기", "세탁기"),  # 이미 합쳐진 글은 그대로
    ],
)
def test_collapse_joins_letter_spaced_hangul(raw: str, expected: str) -> None:
    assert collapse_spaced_hangul(raw) == expected
    assert collapse_spaced_hangul(expected) == expected  # 두 번 해도 같다


def test_collapse_leaves_normal_sentences_and_numbers_alone() -> None:
    for text in (
        "이 조례에서 사용하는 용어",
        "수거 및 이송",
        "10kg 이상",
        "오후 6시 부터 11시 까지",
        "배출요령은 제1호",
        "제2항 및 제3항",
        "법 제6조에 따라 할 수 있다",
    ):
        assert collapse_spaced_hangul(text) == text


def table_row(cells: list[str], paragraphs: list[str]) -> str:
    def make(texts: list[str], row: int) -> dict:
        return {
            "cells": [
                {"origin_col": i, "colspan": 1, "text": t} for i, t in enumerate(texts)
            ],
            "row": row,
        }

    return json.dumps(
        {
            "header_rows": [make(["용 량 (ℓ)", "용 도"], 0)],
            "paragraphs": paragraphs,
            "row": make(cells, 4),
            "section_title": "[별표 2]",
            "table_id": "table-1",
        },
        ensure_ascii=False,
    )


def test_row_text_pairs_labels_and_adds_table_context_without_amendment_history() -> (
    None
):
    content = table_row(
        ["20", "생활폐기물용, 공공용"],
        [
            "[별표 2] <개정 98․6․12, 2020.03.19.> ",
            "규격봉투 용량별 용도(제4조제2호 관련) ",
        ],
    )
    assert row_embedding_text(content) == (
        "규격봉투 용량별 용도(제4조제2호 관련)\n"
        "용량 (ℓ): 20\n"
        "용도: 생활폐기물용, 공공용"
    )


def test_row_text_collapses_spaced_item_names_and_skips_empty_cells() -> None:
    content = table_row(["세   탁   기", "", "10kg 이상"], [])
    text = row_embedding_text(content)
    assert text is not None
    assert "용량 (ℓ): 세탁기" in text
    assert "10kg 이상" in text
    assert text.count("\n") == 1  # 빈 셀 줄은 없다


@pytest.mark.parametrize(
    "content",
    [
        '{"text": "제1조(목적) 이 조례는", "unit_type": "article"}',
        "<p>html</p>",
        "[]",
        "{}",
    ],
)
def test_non_table_chunks_are_not_converted(content: str) -> None:
    assert row_embedding_text(content) is None


def test_search_text_only_collapses_for_table_row_chunks() -> None:
    row = table_row(["세   탁   기"], [])
    assert search_text("세   탁   기", row) == "세탁기"
    article = '{"text": "가 나 다 라", "unit_type": "article"}'
    assert search_text("가 나 다 라", article) == "가 나 다 라"


def test_search_text_joins_two_letter_cells_inside_the_flattened_chunk() -> None:
    content = table_row(["책 장", "10ℓ"], [])
    assert "책장" in search_text("용도 책 장 10ℓ", content)
    assert search_text("제2항 및 제3항", content) == "제2항 및 제3항"
