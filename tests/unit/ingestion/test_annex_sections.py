"""별표·별지의 실제 제목과 삭제 구획 경계를 확인한다."""

from html import escape
from pathlib import Path

import pytest

from src.ingestion.annexes import extract_hwp_xml

TABLE_XML = """<TableControl><TableBody rows="1" cols="1"><TableRow>
<TableCell row="0" col="0" rowspan="1" colspan="1"><Paragraph>
<Text>원문 조건</Text></Paragraph></TableCell>
</TableRow></TableBody></TableControl>"""


def _extract_sections(tmp_path: Path, paragraphs: list[str]) -> dict:
    path = tmp_path / "sections.xml"
    fragments = [
        f"<Paragraph><Text>{escape(text)}</Text></Paragraph>{TABLE_XML}"
        for text in paragraphs
    ]
    path.write_text(
        "<HwpDoc><BodyText>" + "".join(fragments) + "</BodyText></HwpDoc>",
        encoding="utf-8",
    )
    return extract_hwp_xml(path)


@pytest.mark.parametrize(
    "heading",
    [
        "[별표 2]",
        "〔별표 2〕<개정 2021. 11. 3.>",
        "【별표 1】",
        "별표2",
        "[별표 2의3]",
        "별표2의3 <신설 2009. 11. 9>",
        "[별지 2] <신설 2009. 11. 9>",
        "별지2",
        "별지1의2",
        "[별지 제1호서식]  <개정 2011. 8. 10.>",
        "〔별지 제2호서식〕",
    ],
)
def test_active_heading_resets_deleted_section(tmp_path: Path, heading: str):
    content = _extract_sections(tmp_path, ["[별표 1] 삭제", heading])
    table = content["tables"][1]

    assert content["tables"][0]["deleted_section"] is True
    assert table["section_title"] == heading
    assert table["deleted_section"] is False
    assert table["cells"][0]["text"] == "원문 조건"
    assert table["cells"][0]["cell_id"] == "table-2-r0-c0"


def test_deleted_forms_end_at_each_active_form(tmp_path: Path):
    headings = [
        "별지1 <삭제 2014.9.25.>",
        "별지1의2 <삭제 2014.9.25.>",
        "[별지 2] <신설 2009. 11. 9>",
        "[별지 3] <신설 2009. 11. 9>",
        "[별지 4] <신설 2009. 11. 9>",
    ]
    content = _extract_sections(tmp_path, headings)

    for table, heading, deleted in zip(
        content["tables"], headings, [True, True, False, False, False], strict=True
    ):
        assert table["section_title"] == heading
        assert table["deleted_section"] is deleted
    paragraphs = [b for b in content["blocks"] if b["type"] == "paragraph"]
    assert [b["text"] for b in paragraphs] == headings
    assert [b["deleted_section"] for b in paragraphs] == [
        True,
        True,
        False,
        False,
        False,
    ]


def test_separate_deleted_marker_keeps_existing_annex_behavior(tmp_path: Path):
    heading = "[별표 3] <개정 2010.8.12.>"
    content = _extract_sections(
        tmp_path, [heading, "<삭제 2015.10.22.>", "〔별표 4〕신설<2017.3.30.>"]
    )

    assert [table["deleted_section"] for table in content["tables"]] == [
        False,
        True,
        False,
    ]
    assert content["tables"][1]["section_title"] == heading


@pytest.mark.parametrize(
    "reference",
    [
        "비고 1. 별표2 제2호의 배출요령을 준용한다.",
        "별표 2 제2호의 배출요령을 준용한다.",
        "[별표 2]에 따른 배출요령을 준용한다.",
        "[별지 제1호서식]에 따라 작성한다.",
        "안내: 별지1의2 <삭제 2014.9.25.>",
    ],
)
def test_body_reference_does_not_start_section(tmp_path: Path, reference: str):
    heading = "[별표 1] 삭제"
    content = _extract_sections(tmp_path, [heading, reference])
    table = content["tables"][1]

    assert table["section_title"] == heading
    assert table["deleted_section"] is True
    assert content["blocks"][2]["text"] == reference


def test_songpa_original_forms_keep_deleted_and_active_boundaries():
    xml_path = (
        Path(__file__).resolve().parents[3]
        / "data/handoff/jungeun/ordinance-handoff-2026-11-24/processed/annex"
        / "2053883_154690993.xml"
    )
    content = extract_hwp_xml(xml_path)

    assert [block["deleted_section"] for block in content["blocks"][:2]] == [
        True,
        True,
    ]
    assert [table["section_title"] for table in content["tables"]] == [
        f"[별지 {number}] <신설 2009. 11. 9>" for number in (2, 3, 4)
    ]
    assert all(not table["deleted_section"] for table in content["tables"])
