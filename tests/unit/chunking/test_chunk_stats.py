"""청킹 현황 집계(scripts/chunk_stats.py) 테스트. 합성 청크만 사용한다."""

import csv
import json
from pathlib import Path

import pytest

from scripts.chunk_stats import (
    COLUMNS,
    append_row,
    main,
    plain_text,
    summarize,
)


def make_chunk(
    location: str,
    content: str,
    districts=None,
    conditions=None,
    doc: str = "doc-a",
    fmt: str = "html",
) -> dict:
    return {
        "content_format": fmt,
        "chunk_id": f"id-{doc}-{location}",
        "source_document_id": doc,
        "source_location": location,
        "districts": ["서대문구"] if districts is None else districts,
        "conditions": [] if conditions is None else conditions,
        "content": content,
    }


CHUNKS = [
    make_chunk("조문/조[2] (조문번호 000100)", "<p>제1조(목적) " + "가" * 150 + "</p>"),
    make_chunk(
        "조문/조[3] (조문번호 000200)", "<p>제2조 8. 삭제 &lt;2011. 8. 10.&gt;</p>"
    ),
    make_chunk(
        "table-1/row[0]",
        "<table><tr><td>" + "나" * 300 + "</td></tr></table>",
        doc="doc-b",
        districts=["송파구"],
    ),
    make_chunk(
        "table-1/row[1]",
        "<tr><td>" + "다" * 200 + "</td></tr>",
        doc="doc-b",
        districts=["송파구"],
        conditions=["일반주택"],
    ),
    make_chunk("부칙/1", "<p>" + "라" * 120 + "</p>", districts=[]),
]


def test_plain_text_removes_tags_and_unescapes() -> None:
    assert plain_text("<p>가  나\n다 &lt;삭제&gt;</p>") == "가 나 다 <삭제>"


def test_plain_text_keeps_angle_brackets_in_json_chunks() -> None:
    # JSON 청크의 <개정 …>는 원문 글자라서 태그로 지우면 안 된다.
    assert (
        plain_text('{"text":"8. 삭제 <2011. 8. 10.>"}', "json")
        == '{"text":"8. 삭제 <2011. 8. 10.>"}'
    )


def test_summarize_counts() -> None:
    row = summarize(CHUNKS, "v-test", "html")
    assert row["chunk_count"] == 5
    assert row["documents"] == 2
    assert (row["서대문구"], row["송파구"], row["공통"]) == (2, 2, 1)
    assert (row["article_chunks"], row["table_row_chunks"], row["other_chunks"]) == (
        2,
        2,
        1,
    )
    assert row["conditions_empty"] == 4


def test_summarize_finds_deleted_markers_in_both_forms() -> None:
    chunks = [
        make_chunk("a", "<p>8. 삭제 &lt;2011. 8. 10.&gt;</p>"),
        make_chunk("b", "<p>① &lt;삭제 2015.4.2&gt;</p>"),
        make_chunk("c", "<p>필요하면 서류를 삭제할 수 있다.</p>"),
    ]
    assert summarize(chunks, "v", "html")["deleted_marker_chunks"] == 2


def test_summarize_finds_deleted_markers_in_json_chunks() -> None:
    content = '{"text":"8. 삭제 <2011. 8. 10.>\\n9. 삭제 <2011. 8. 10.>"}'
    chunks = [make_chunk("a", content, fmt="json")]
    assert summarize(chunks, "v", "json")["deleted_marker_chunks"] == 1


def test_summarize_length_stats_and_short_chunks() -> None:
    row = summarize(CHUNKS, "v-test", "html")
    assert (
        row["plain_min"] < row["plain_median"] <= row["plain_p90"] <= row["plain_max"]
    )
    assert row["content_max"] > row["plain_max"]  # 태그가 길이를 늘린다
    assert row["short_chunks"] == 1  # 삭제 표시만 있는 두 번째 청크


def test_summarize_counts_chunks_with_identical_plain_text() -> None:
    same = "<p>같은 내용입니다.</p>"
    chunks = [
        make_chunk("table-1/row[0]", same),
        make_chunk("table-1/row[1]", same),
        make_chunk("table-1/row[2]", "<p>다른 내용입니다.</p>"),
        make_chunk(
            "table-2/row[0]", "<b>같은 내용입니다.</b>"
        ),  # 태그만 다르고 평문이 같다
    ]
    assert summarize(chunks, "v", "html")["duplicate_plain_chunks"] == 3
    assert summarize(CHUNKS, "v", "html")["duplicate_plain_chunks"] == 0


def test_summarize_rejects_empty_list() -> None:
    with pytest.raises(ValueError):
        summarize([], "v", "html")


def read_rows(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def test_append_row_writes_header_once(tmp_path: Path) -> None:
    target = tmp_path / "out" / "chunk_stats.csv"
    append_row(summarize(CHUNKS, "v1", "html"), target)
    append_row(summarize(CHUNKS, "v1", "json"), target)
    rows = read_rows(target)
    assert list(rows[0]) == COLUMNS
    assert [(r["chunking_version"], r["format"]) for r in rows] == [
        ("v1", "html"),
        ("v1", "json"),
    ]


def test_append_row_refuses_duplicate_chunking_version_and_format(
    tmp_path: Path,
) -> None:
    target = tmp_path / "chunk_stats.csv"
    append_row(summarize(CHUNKS, "v1", "html"), target)
    with pytest.raises(ValueError):
        append_row(summarize(CHUNKS, "v1", "html"), target)
    assert len(read_rows(target)) == 1


def write_chunks(tmp_path: Path) -> Path:
    path = tmp_path / "chunks-html.json"
    path.write_text(json.dumps(CHUNKS, ensure_ascii=False), encoding="utf-8")
    return path


def test_main_appends_row_and_returns_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    target = tmp_path / "chunk_stats.csv"
    args = [
        "--chunks",
        str(write_chunks(tmp_path)),
        "--chunking-version",
        "v1",
        "--format",
        "html",
        "--csv",
        str(target),
    ]
    assert main(args) == 0
    assert "chunk_count: 5" in capsys.readouterr().out
    assert len(read_rows(target)) == 1
    assert main(args) == 2  # 같은 기록을 두 번 쓰지 않는다


def test_main_without_csv_only_prints(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    assert (
        main(
            [
                "--chunks",
                str(write_chunks(tmp_path)),
                "--chunking-version",
                "v1",
                "--format",
                "html",
            ]
        )
        == 0
    )
    assert "chunk_count: 5" in capsys.readouterr().out


def test_main_show_prints_plain_text(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    assert (
        main(["--chunks", str(write_chunks(tmp_path)), "--show", "table-1/row[1]"]) == 0
    )
    out = capsys.readouterr().out
    assert "일치 1개" in out
    assert "다" * 200 in out
    assert "<td>" not in out


def test_main_missing_file_returns_two(tmp_path: Path) -> None:
    assert (
        main(
            [
                "--chunks",
                str(tmp_path / "none.json"),
                "--chunking-version",
                "v1",
                "--format",
                "html",
            ]
        )
        == 2
    )


def test_main_needs_chunking_version_and_format(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(["--chunks", str(write_chunks(tmp_path))])
