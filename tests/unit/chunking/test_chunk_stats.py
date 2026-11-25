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
    scope_type: str | None = None,
    chunking_version: str = "v1",
) -> dict:
    scope = scope_type or ("common" if districts == [] else "district")
    return {
        "scope_type": scope,
        "chunking_version": chunking_version,
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


def test_plain_text_decodes_all_html_entities() -> None:
    assert (
        plain_text("<p>&quot;가&quot; &#x27;나&#x27;&nbsp;다</p>") == "\"가\" '나' 다"
    )


def test_plain_text_keeps_angle_brackets_in_json_chunks() -> None:
    # JSON 청크의 <개정 …>는 원문 글자라서 태그로 지우면 안 된다.
    assert (
        plain_text('{"text":"8. 삭제 <2011. 8. 10.>"}', "json")
        == '{"text":"8. 삭제 <2011. 8. 10.>"}'
    )


def test_summarize_counts() -> None:
    row = summarize(CHUNKS)
    assert row["chunk_count"] == 5
    assert row["documents"] == 2
    assert (row["서대문구"], row["송파구"], row["공통"]) == (2, 2, 1)
    assert (row["article_chunks"], row["table_row_chunks"], row["other_chunks"]) == (
        2,
        2,
        1,
    )
    assert row["heading_chunks"] == 0
    assert row["conditions_empty"] == 4


def test_summarize_separates_article_and_heading_chunks() -> None:
    chunks = [
        make_chunk("조문/조[1] (조문번호 000000)", "<p>제1장 총칙</p>"),
        make_chunk("조문/조[2] (조문번호 000100)", "<p>제1조(목적) 내용</p>"),
        make_chunk("조문/조[3] (조문번호 000200)", "<p>제2조 내용</p>"),
        make_chunk("table-1/row[0]", "<p>표 행</p>"),
        make_chunk("부칙/1", "<p>부칙</p>"),
    ]
    row = summarize(chunks)
    assert row["article_chunks"] == 2  # 장 제목은 조문에 세지 않는다
    assert row["heading_chunks"] == 1
    assert (row["table_row_chunks"], row["other_chunks"]) == (1, 1)


def test_summarize_reads_chunking_version_and_format_from_chunks() -> None:
    row = summarize(CHUNKS)
    assert (row["chunking_version"], row["format"]) == ("v1", "html")
    json_row = summarize([make_chunk("a", "{}", fmt="json", chunking_version="v2")])
    assert (json_row["chunking_version"], json_row["format"]) == ("v2", "json")


def test_summarize_rejects_mixed_chunking_versions() -> None:
    chunks = [
        make_chunk("a", "<p>가</p>", chunking_version="v1"),
        make_chunk("b", "<p>나</p>", chunking_version="v2"),
    ]
    with pytest.raises(ValueError, match="chunking_version"):
        summarize(chunks)


def test_summarize_rejects_missing_chunking_version() -> None:
    chunk = make_chunk("a", "<p>가</p>")
    del chunk["chunking_version"]
    with pytest.raises(ValueError, match="chunking_version"):
        summarize([chunk])


def test_summarize_rejects_mixed_formats() -> None:
    chunks = [make_chunk("a", "<p>가</p>"), make_chunk("b", "{}", fmt="json")]
    with pytest.raises(ValueError, match="content_format"):
        summarize(chunks)


def test_summarize_finds_deleted_markers_in_both_forms() -> None:
    chunks = [
        make_chunk("a", "<p>8. 삭제 &lt;2011. 8. 10.&gt;</p>"),
        make_chunk("b", "<p>① &lt;삭제 2015.4.2&gt;</p>"),
        make_chunk("c", "<p>필요하면 서류를 삭제할 수 있다.</p>"),
    ]
    assert summarize(chunks)["deleted_marker_chunks"] == 2


def test_summarize_finds_deleted_markers_in_json_chunks() -> None:
    content = '{"text":"8. 삭제 <2011. 8. 10.>\\n9. 삭제 <2011. 8. 10.>"}'
    chunks = [make_chunk("a", content, fmt="json")]
    assert summarize(chunks)["deleted_marker_chunks"] == 1


def test_summarize_length_stats_and_short_chunks() -> None:
    row = summarize(CHUNKS)
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
    assert summarize(chunks)["duplicate_plain_chunks"] == 3
    assert summarize(CHUNKS)["duplicate_plain_chunks"] == 0


def test_summarize_counts_scope_by_scope_type_and_membership() -> None:
    chunks = [
        make_chunk("a", "<p>가</p>", districts=[], scope_type="common"),
        make_chunk("b", "<p>나</p>", districts=[], scope_type="unknown"),
        make_chunk("c", "<p>다</p>", districts=["서대문구", "송파구"]),
        make_chunk("d", "<p>라</p>", districts=["서대문구"]),
    ]
    row = summarize(chunks)
    assert (row["서대문구"], row["송파구"]) == (2, 1)  # 다중 구 청크는 구마다 센다
    assert (row["공통"], row["범위미상"]) == (1, 1)


def test_summarize_rejects_empty_list() -> None:
    with pytest.raises(ValueError):
        summarize([])


def read_rows(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def test_append_row_writes_header_once(tmp_path: Path) -> None:
    target = tmp_path / "out" / "chunk_stats.csv"
    append_row(summarize(CHUNKS), target)
    append_row(summarize([make_chunk("a", "{}", fmt="json")]), target)
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
    append_row(summarize(CHUNKS), target)
    with pytest.raises(ValueError):
        append_row(summarize(CHUNKS), target)
    assert len(read_rows(target)) == 1


def test_append_row_writes_header_when_file_is_empty(tmp_path: Path) -> None:
    target = tmp_path / "chunk_stats.csv"
    target.write_bytes(b"")
    append_row(summarize(CHUNKS), target)
    rows = read_rows(target)
    assert list(rows[0]) == COLUMNS
    assert len(rows) == 1


def test_append_row_refuses_csv_with_different_columns(tmp_path: Path) -> None:
    target = tmp_path / "chunk_stats.csv"
    target.write_text("label,format\nv0,html\n", encoding="utf-8")
    with pytest.raises(ValueError, match="열"):
        append_row(summarize(CHUNKS), target)


def test_append_row_refuses_csv_with_reordered_columns(tmp_path: Path) -> None:
    # 열 순서가 바뀐 파일에 이어 쓰면 값이 뒤바뀌므로 저장 전에 거부한다.
    target = tmp_path / "chunk_stats.csv"
    reordered = list(COLUMNS)
    reordered[2], reordered[3] = reordered[3], reordered[2]  # chunk_count <-> documents
    target.write_text(",".join(reordered) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="열"):
        append_row(summarize(CHUNKS), target)
    assert len(target.read_text(encoding="utf-8").splitlines()) == 1


def write_chunks(tmp_path: Path, chunks: list[dict] | None = None) -> Path:
    path = tmp_path / "chunks.json"
    path.write_text(json.dumps(chunks or CHUNKS, ensure_ascii=False), encoding="utf-8")
    return path


def test_main_appends_row_and_returns_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    target = tmp_path / "chunk_stats.csv"
    args = ["--chunks", str(write_chunks(tmp_path)), "--csv", str(target)]
    assert main(args) == 0
    assert "chunk_count: 5" in capsys.readouterr().out
    rows = read_rows(target)
    assert len(rows) == 1
    assert (rows[0]["chunking_version"], rows[0]["format"]) == ("v1", "html")
    assert main(args) == 2  # 같은 기록을 두 번 쓰지 않는다


def test_main_without_csv_only_prints(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    assert main(["--chunks", str(write_chunks(tmp_path))]) == 0
    out = capsys.readouterr().out
    assert "chunk_count: 5" in out
    assert "chunking_version: v1" in out
    assert "format: html" in out


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
    assert main(["--chunks", str(tmp_path / "none.json")]) == 2


def test_main_rejects_mixed_formats_and_versions(tmp_path: Path) -> None:
    mixed_format = [make_chunk("a", "<p>가</p>"), make_chunk("b", "{}", fmt="json")]
    assert main(["--chunks", str(write_chunks(tmp_path, mixed_format))]) == 2
    mixed_version = [
        make_chunk("a", "<p>가</p>"),
        make_chunk("b", "<p>나</p>", chunking_version="v2"),
    ]
    assert main(["--chunks", str(write_chunks(tmp_path, mixed_version))]) == 2


def test_chunk_ids_fingerprint_ignores_order_and_changes_with_any_id() -> None:
    first = summarize(CHUNKS)["chunk_ids_sha256"]
    assert summarize(list(reversed(CHUNKS)))["chunk_ids_sha256"] == first
    changed = [dict(c) for c in CHUNKS]
    changed[0]["chunk_id"] = "id-other"
    assert summarize(changed)["chunk_ids_sha256"] != first
