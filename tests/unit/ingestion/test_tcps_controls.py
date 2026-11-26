"""글자 겹침 원문과 UTF-8 JSON 왕복의 코드포인트 보존 검사."""

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from src.ingestion.annexes import _text, extract_hwp_xml

# 실제 두 첨부의 legacy Yi 음절·보충 평면 PUA 표기. 화면 모양·번호 추정 제외
TCPS_PAYLOADS = ("\ua289\ua298", "\U000f0289\U000f0298")


@pytest.mark.parametrize("payload", TCPS_PAYLOADS)
@pytest.mark.parametrize("ensure_ascii", [False, True])
def test_tcps_source_survives_extraction_and_utf8_json_round_trip(
    tmp_path: Path, payload: str, ensure_ascii: bool
):
    path = tmp_path / "tcps.xml"
    path.write_text(
        f"""<HwpDoc><BodyText>
<Paragraph><Text>[별표 1]</Text></Paragraph>
<Paragraph><Text>차. ⑭, </Text><TCPSControl chid="tcps" textlength="{payload}"/>
<Text> : 처리방법 기재</Text><ControlChar name="PARAGRAPH_BREAK"/></Paragraph>
<TableControl><TableBody rows="2" cols="2"><TableRow>
<TableCell row="0" col="0" rowspan="2" colspan="1"><Paragraph>
<TCPSControl chid="tcps" textlength="{payload}"/><Text> 처리방법</Text>
<ControlChar name="PARAGRAPH_BREAK"/></Paragraph></TableCell>
<TableCell row="0" col="1" rowspan="1" colspan="1"><Paragraph>
<Text>원문 방법</Text></Paragraph></TableCell></TableRow><TableRow>
<TableCell row="1" col="1" rowspan="1" colspan="1"><Paragraph>
<Text>다만, 조건</Text></Paragraph></TableCell></TableRow></TableBody></TableControl>
</BodyText></HwpDoc>""",
        encoding="utf-8",
    )
    original = path.read_bytes()
    extracted = extract_hwp_xml(path)
    output = tmp_path / "tcps.json"
    output.write_text(
        json.dumps(extracted, ensure_ascii=ensure_ascii), encoding="utf-8"
    )
    restored = json.loads(output.read_text(encoding="utf-8"))

    assert restored == extracted
    assert path.read_bytes() == original
    assert restored["blocks"][1]["text"] == f"차. ⑭, {payload} : 처리방법 기재\n"
    table = restored["tables"][0]
    cell = table["cells"][0]
    assert cell["paragraphs"] == [f"{payload} 처리방법\n"]
    assert cell["text"] == f"{payload} 처리방법"
    assert (cell["row"], cell["col"], cell["rowspan"], cell["colspan"]) == (
        0,
        0,
        2,
        1,
    )
    assert table["row_cell_ids"] == [
        ["table-1-r0-c0", "table-1-r0-c1"],
        ["table-1-r0-c0", "table-1-r1-c1"],
    ]
    rows = table["rows_for_search"]
    assert [row["row_id"] for row in rows] == ["table-1-row-0", "table-1-row-1"]
    assert rows[0]["search_text"] == f"{payload} 처리방법 | 원문 방법"
    assert rows[1]["search_text"] == f"{payload} 처리방법 | 다만, 조건"
    inherited = rows[1]["cell_values"][0]
    assert inherited["cell_id"] == cell["cell_id"]
    assert inherited["text"] == cell["text"]
    assert inherited["inherited_from_previous_row"] is True
    assert [ord(char) for char in inherited["text"][: len(payload)]] == [
        ord(char) for char in payload
    ]


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("<Text>원문</Text>", "원문"),
        ("직접 본문", "직접 본문"),
        ("앞<Text>가운데</Text>뒤<Text>끝</Text>꼬리", "앞가운데뒤끝꼬리"),
    ],
)
def test_tcps_rendered_body_takes_priority_without_appending_attribute(body, expected):
    node = ET.fromstring(f'<TCPSControl textlength="중복 금지">{body}</TCPSControl>')
    assert _text(node) == expected


def test_tcps_xml_indentation_does_not_hide_attribute_payload():
    node = ET.fromstring('<TCPSControl textlength="\ua289\ua298">\n  </TCPSControl>')
    assert _text(node) == "\ua289\ua298"


def test_empty_tcps_without_payload_stays_empty():
    node = ET.fromstring("<TCPSControl/>")
    assert _text(node) == ""
