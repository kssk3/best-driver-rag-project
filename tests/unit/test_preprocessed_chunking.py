"""합성 v2 JSON/어댑터 HTML의 동일 출처, 행 병합과 문맥 보존을 검증한다."""

import copy
import json
from html import escape
from html.parser import HTMLParser

import pytest

from src.contracts import SourceDocument
from src.ingestion.preprocessed_chunking import (
    PreprocessedChunkingError,
    chunk_preprocessed_documents,
)


def document(content, content_format="json", **changes):
    return SourceDocument(
        **(
            {
                "document_id": "synthetic-annex",
                "version": "source-v2",
                "title": "합성 별표",
                "content_format": content_format,
                "content": json.dumps(content, ensure_ascii=False)
                if isinstance(content, dict)
                else content,
                "source_url": "https://example.org/annex.hwp",
                "scope_type": "district",
                "districts": ["서대문구"],
                "parent_document_id": "synthetic-law",
                "parent_document_version": "law-v3",
            }
            | changes
        )
    )


def table_fixture():
    # 첫 두 행은 병합 머리글, 마지막 두 행은 동일 상위 품목을 공유한다.
    definitions = [
        (0, 0, 2, 1, "분류"),
        (0, 1, 1, 2, "세부 기준"),
        (1, 1, 1, 1, "품목"),
        (1, 2, 1, 1, "안내"),
        (2, 0, 2, 1, "상위 재질"),
        (2, 1, 1, 1, "품목 A"),
        (2, 2, 1, 1, "원문  A\n예외 유지"),
        (3, 1, 1, 1, "품목 B"),
        (3, 2, 1, 1, "안내 B"),
    ]
    cells = [
        {
            "cell_id": f"table-1-r{r}-c{c}",
            "row": r,
            "col": c,
            "rowspan": rs,
            "colspan": cs,
            "text": text,
        }
        for r, c, rs, cs, text in definitions
    ]
    selected = [[0, 1], [0, 2, 3], [4, 5, 6], [4, 7, 8]]
    rows = []
    for number, indices in enumerate(selected):
        values = []
        for index in indices:
            cell = cells[index]
            values.append(
                {
                    "cell_id": cell["cell_id"],
                    "origin_row": cell["row"],
                    "origin_col": cell["col"],
                    "rowspan": cell["rowspan"],
                    "colspan": cell["colspan"],
                    "columns": list(range(cell["col"], cell["col"] + cell["colspan"])),
                    "inherited_from_previous_row": cell["row"] < number,
                    "text": cell["text"],
                    "search_text": "정규화 대체값은 사용하지 않음",
                    "normalization_changes": ["레이아웃 기록"],
                }
            )
        rows.append(
            {
                "table_id": "table-1",
                "row": number,
                "cell_values": values,
                "missing_columns": [],
            }
        )
    return {
        "table_id": "table-1",
        "rows": 4,
        "cols": 3,
        "cells": cells,
        "rows_for_search": rows,
        "section_title": "별표 A",
        "deleted_section": False,
    }


def annex_fixture():
    return {
        "schema_version": "jungeun-annex-draft-v2",
        "deleted_marker": False,
        "blocks": [
            {
                "type": "paragraph",
                "text": "앞 안내",
                "section_title": "별표 A",
                "deleted_section": False,
            },
            {
                "type": "table",
                "table_id": "table-1",
                "section_title": "별표 A",
                "deleted_section": False,
            },
            {
                "type": "paragraph",
                "text": "뒤 비고: 특정 조건은 제외",
                "section_title": "별표 A",
                "deleted_section": False,
            },
        ],
        "tables": [table_fixture()],
        "review": {"private_context": "검수용 기록"},
        "raw_xml": "<metadata>" + "사용하지 않을 레이아웃" * 5000 + "</metadata>",
    }


def annex_html(data):
    table = data["tables"][0]
    rows = []
    for number in range(table["rows"]):
        cells = []
        for cell in table["cells"]:
            if cell["row"] == number:
                cells.append(
                    f'<td data-cell-id="{cell["cell_id"]}" data-row="{cell["row"]}" '
                    f'data-col="{cell["col"]}" rowspan="{cell["rowspan"]}" colspan="{cell["colspan"]}">'
                    f"<p>{escape(cell['text'])}</p></td>"
                )
        rows.append(f'<tr data-row-index="{number}">' + "".join(cells) + "</tr>")
    return (
        '<section data-section-title="별표 A" data-deleted-section="false"><p>앞 안내</p>'
        '<table data-table-id="table-1">'
        + "".join(rows)
        + "</table><p>뒤 비고: 특정 조건은 제외</p></section>"
    )


class Text(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.feed(html)

    def handle_data(self, data):
        self.parts.append(data)


def test_json_rows_keep_headers_merged_parent_raw_text_and_after_table_notes():
    source = document(annex_fixture())
    chunks = chunk_preprocessed_documents([source])
    assert [chunk.source_location for chunk in chunks] == [
        f"table-1/row[{n}]" for n in range(4)
    ]
    values = [json.loads(chunk.content) for chunk in chunks]
    for value in values:
        assert value["paragraphs"] == ["앞 안내", "뒤 비고: 특정 조건은 제외"]
        assert len(value["header_rows"]) == 2
        assert value["header_rows"][1]["cells"][0]["text"] == "분류"
    inherited = values[3]["row"]["cells"][0]
    assert inherited["text"] == "상위 재질"
    assert inherited["origin_row"] == 2
    assert inherited["rowspan"] == 2
    assert inherited["inherited_from_previous_row"] is True
    assert values[2]["row"]["cells"][2]["text"] == "원문  A\n예외 유지"
    for chunk in chunks:
        assert "검수용 기록" not in chunk.content
        assert "레이아웃" not in chunk.content
        assert "정규화 대체값" not in chunk.content
        assert chunk.source_document_id == source.document_id
        assert chunk.source_document_version == "source-v2"
        assert chunk.source_url == source.source_url
        assert chunk.conditions == []


def test_html_and_json_locations_and_semantic_row_content_correspond():
    data = annex_fixture()
    jc = chunk_preprocessed_documents([document(data)])
    hc = chunk_preprocessed_documents([document(annex_html(data), "html")])
    assert [c.source_location for c in jc] == [c.source_location for c in hc]
    for json_chunk, html_chunk in zip(jc, hc, strict=True):
        value = json.loads(json_chunk.content)
        text = "".join(Text(html_chunk.content).parts)
        for paragraph in value["paragraphs"]:
            assert paragraph in text
        for row in [*value["header_rows"], value["row"]]:
            for cell in row["cells"]:
                assert cell["text"] in text
        assert json_chunk.chunk_id != html_chunk.chunk_id
    assert 'data-inherited="true"' in hc[3].content
    assert 'data-original-rowspan="2"' in hc[3].content
    assert 'colspan="2"' in hc[3].content
    assert 'rowspan="2"' not in hc[3].content.replace('data-original-rowspan="2"', "")


def test_image_overlay_is_preserved_as_same_object_in_both_representations():
    data = annex_fixture()
    summary = {
        "applicability": "합성 공동주택 기준",
        "source_location": "합성 그림",
        "colors": [{"item": "품목 A", "color": "색 A"}],
        "validation": "합성 검수 표시",
        "does_not_establish": "현장 시설을 확인한 결과가 아님",
    }
    data["structured_image_summary"] = summary
    raw = (
        annex_html(data)
        + '<aside data-review-overlay="image-summary">'
        + escape(json.dumps(summary, ensure_ascii=False))
        + "</aside>"
    )
    jc = chunk_preprocessed_documents([document(data)])
    hc = chunk_preprocessed_documents([document(raw, "html")])
    for chunk in jc:
        assert json.loads(chunk.content)["structured_image_summary"] == summary
    canonical = json.dumps(
        summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    assert all(canonical in "".join(Text(chunk.content).parts) for chunk in hc)


def body_fixture():
    return {
        "schema_version": "jungeun-body-draft-v2",
        "units": [
            {
                "unit_type": "heading",
                "raw_text": "제1장 총칙\n",
                "source_location": "조문/조[1] (조문번호 000000)",
                "deleted_article": False,
            },
            {
                "unit_type": "article",
                "raw_text": "제1조(원칙)  원문\n단, 예외.\n",
                "text": "정규화값",
                "source_location": "조문/조[2] (조문번호 000100)",
                "deleted_article": False,
            },
            {
                "unit_type": "article",
                "text": "삭제된 내용",
                "source_location": "조문/조[3] (조문번호 000200)",
                "deleted_article": True,
            },
        ],
        "supplementary_provisions": [
            {
                "source_location": "부칙[1]/부칙내용",
                "raw_text": "과거 시행일과 경과조치",
                "promulgation_date": "20000101",
                "promulgation_number": "10",
                "applicability_status": "historical_and_current_mixed_review_required",
            }
        ],
        "amendment_reasons": [{"raw_xml": "개정 이유 검수용 원문"}],
        "attachments": [{"title": "본문과 별도인 첨부"}],
    }


def test_body_keeps_headings_articles_supplement_status_and_excludes_deleted_articles():
    chunks = chunk_preprocessed_documents([document(body_fixture())])
    assert len(chunks) == 3
    assert json.loads(chunks[1].content)["text"] == "제1조(원칙)  원문\n단, 예외.\n"
    supplement = json.loads(chunks[2].content)
    assert (
        supplement["applicability_status"]
        == "historical_and_current_mixed_review_required"
    )
    assert supplement["promulgation_date"] == "20000101"
    assert "일괄 적용 금지" in supplement["note"]
    assert not any(
        "삭제된 내용" in chunk.content or "개정 이유 검수용 원문" in chunk.content
        for chunk in chunks
    )


def test_html_body_keeps_source_location_and_supplement_warning():
    html = (
        '<section data-unit-type="article" data-deleted-article="false" data-source-location="조문/조[2] (조문번호 000100)"><p>제1조 원문</p></section>'
        '<section data-unit-type="article" data-deleted-article="true" data-source-location="삭제"><p>삭제된 내용</p></section>'
        '<section data-unit-type="supplement" data-source-location="부칙[1]/부칙내용" data-promulgation-date="20000101" data-promulgation-number="10"><p>과거 시행일과 경과조치</p></section>'
    )
    chunks = chunk_preprocessed_documents([document(html, "html")])
    assert [chunk.source_location for chunk in chunks] == [
        "조문/조[2] (조문번호 000100)",
        "부칙[1]/부칙내용",
    ]
    assert 'data-promulgation-date="20000101"' in chunks[1].content
    assert "historical_and_current_mixed_review_required" in chunks[1].content
    assert "일괄 적용 금지" in chunks[1].content


def test_same_title_deleted_and_live_sections_are_not_merged_or_lost():
    data = {
        "schema_version": "jungeun-annex-draft-v2",
        "tables": [],
        "blocks": [
            {
                "type": "paragraph",
                "text": "살아 있는 안내",
                "section_title": "동일 제목",
                "deleted_section": False,
            },
            {
                "type": "paragraph",
                "text": "삭제된 별표 안내",
                "section_title": "동일 제목",
                "deleted_section": True,
            },
            {
                "type": "paragraph",
                "text": "다음 살아 있는 안내",
                "section_title": "동일 제목",
                "deleted_section": False,
            },
        ],
    }
    html = "".join(
        f'<section data-section-title="동일 제목" data-deleted-section="{str(b["deleted_section"]).lower()}"><p>{b["text"]}</p></section>'
        for b in data["blocks"]
    )
    jc = chunk_preprocessed_documents([document(data)])
    hc = chunk_preprocessed_documents([document(html, "html")])
    assert (
        [c.source_location for c in jc]
        == [c.source_location for c in hc]
        == ["section[1]/paragraphs", "section[3]/paragraphs"]
    )
    assert not any("삭제된 별표" in chunk.content for chunk in [*jc, *hc])


def test_entire_deleted_attachment_is_excluded():
    data = annex_fixture()
    data["deleted_marker"] = True
    assert chunk_preprocessed_documents([document(data)]) == []
    assert (
        chunk_preprocessed_documents(
            [
                document(
                    '<section data-section-title="삭제" data-deleted-section="true"><p>삭제 자료</p></section>',
                    "html",
                )
            ]
        )
        == []
    )


@pytest.mark.parametrize("variant", ["json", "html"])
def test_oversized_context_fails_with_source_and_location_instead_of_truncating(
    variant,
):
    data = annex_fixture()
    source = document(data if variant == "json" else annex_html(data), variant)
    chunks = chunk_preprocessed_documents([source])
    with pytest.raises(
        PreprocessedChunkingError, match="synthetic-annex.*table-1/row.*잘라내지"
    ):
        chunk_preprocessed_documents(
            [source], max_characters=min(len(c.content) for c in chunks) - 1
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_text",
        "lost_parent",
        "missing_columns",
        "overlapping",
        "missing_table_ref",
    ],
)
def test_inconsistent_table_structure_fails_explicitly(mutation):
    data = annex_fixture()
    table = data["tables"][0]
    if mutation == "wrong_text":
        table["rows_for_search"][3]["cell_values"][0]["text"] = "변조된 상위 값"
    elif mutation == "lost_parent":
        table["rows_for_search"][3]["cell_values"].pop(0)
    elif mutation == "missing_columns":
        table["rows_for_search"][3]["missing_columns"] = [0]
    elif mutation == "overlapping":
        table["cells"][0]["colspan"] = 2
    else:
        data["blocks"] = [b for b in data["blocks"] if b["type"] != "table"]
    with pytest.raises(PreprocessedChunkingError, match="synthetic-annex"):
        chunk_preprocessed_documents([document(data)])


def test_oversized_json_grid_is_rejected_before_allocating_rows(monkeypatch):
    import src.ingestion.preprocessed_chunking as chunking

    data = annex_fixture()
    data["tables"][0].update(rows=10**9, cols=10**9, cells=[], rows_for_search=[])

    def allocation_attempt(*args):
        # 검사 순서가 회귀해도 테스트 자체가 거대한 메모리를 할당하지 않게 한다.
        raise AssertionError("격자 크기 검사 전에 행 할당을 시도했습니다.")

    monkeypatch.setattr(chunking, "range", allocation_attempt, raising=False)
    with pytest.raises(PreprocessedChunkingError, match="synthetic-annex.*100,000칸"):
        chunk_preprocessed_documents([document(data)])


@pytest.mark.parametrize(
    "raw,fmt",
    [
        ('{"schema_version":"unknown"}', "json"),
        ("[]", "json"),
        ('{"schema_version":1,"schema_version":2}', "json"),
        ("<p>일반 HTML은 새 어댑터 규격이 아님</p>", "html"),
        ('<section data-section-title="x"><p>닫히지 않음</section>', "html"),
        (
            '<section data-section-title="x"><p>안내</p></section>누락하면 안 되는 서술',
            "html",
        ),
    ],
)
def test_unknown_or_malformed_inputs_are_rejected(raw, fmt):
    with pytest.raises(PreprocessedChunkingError, match="synthetic-annex"):
        chunk_preprocessed_documents([document(raw, fmt)])


def test_nested_html_table_is_rejected_without_silently_losing_parent_context():
    raw = annex_html(annex_fixture()).replace(
        "<p>품목 A</p>", "<p>품목 A</p><table><tr><td>내부표</td></tr></table>"
    )
    with pytest.raises(PreprocessedChunkingError, match="중첩표"):
        chunk_preprocessed_documents([document(raw, "html")])


def test_ids_are_stable_and_track_source_version_representation_and_rule():
    source = document(annex_fixture())
    original = chunk_preprocessed_documents([source])
    repeated = chunk_preprocessed_documents([source])
    assert [c.model_dump() for c in original] == [c.model_dump() for c in repeated]
    assert len({c.chunk_id for c in original}) == len(original)
    for change in [
        {"version": "source-v3"},
        {"document_id": "other"},
        {"source_url": "https://example.org/other"},
    ]:
        changed = chunk_preprocessed_documents([source.model_copy(update=change)])
        assert original[0].chunk_id != changed[0].chunk_id
    assert (
        original[0].chunk_id
        != chunk_preprocessed_documents([source], chunking_version="row-v2")[0].chunk_id
    )


@pytest.mark.parametrize("limit", [0, -1, True, 1.1])
def test_bad_limits_are_rejected(limit):
    with pytest.raises(ValueError, match="max_characters"):
        chunk_preprocessed_documents([], max_characters=limit)


def test_duplicate_source_and_invalid_input_are_rejected_without_modification():
    source = document(annex_fixture())
    original = copy.deepcopy(source.model_dump())
    with pytest.raises(PreprocessedChunkingError, match="중복"):
        chunk_preprocessed_documents([source, source])
    assert source.model_dump() == original
    with pytest.raises(TypeError, match="SourceDocument"):
        chunk_preprocessed_documents([{}])
    with pytest.raises(ValueError, match="chunking_version"):
        chunk_preprocessed_documents([], chunking_version=" ")
