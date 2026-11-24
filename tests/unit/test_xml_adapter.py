"""XML 원문 의미와 구조를 보존하는 경계를 네트워크 없이 검증한다."""

from html import escape
from html.parser import HTMLParser

import pytest

from src.ingestion.xml_adapter import XMLAdapterError, xml_to_html


class _HTML(HTMLParser):
    def __init__(self, html: str):
        super().__init__(convert_charrefs=True)
        self.nodes = []
        self.stack = []
        self.feed(html)
        self.close()
        assert not self.stack

    def handle_starttag(self, tag, attrs):
        node = {"tag": tag, "attrs": dict(attrs), "text": "",
                "parent": self.stack[-1] if self.stack else None}
        self.nodes.append(node)
        if tag not in {"meta", "br", "img"}:
            self.stack.append(node)

    def handle_endtag(self, tag):
        assert self.stack[-1]["tag"] == tag
        self.stack.pop()

    def handle_data(self, text):
        for node in self.stack:
            node["text"] += text

    def select(self, tag):
        return [node for node in self.nodes if node["tag"] == tag]


def _article(number, text, *, kind="Y", title="제목"):
    return (f"<조><조문번호>{number}</조문번호><조문여부>{kind}</조문여부>"
            f"<조제목>{title}</조제목><조내용>{escape(text)}</조내용></조>")


def _p(text):
    return "<Paragraph><LineSeg><Text>" + escape(text) + "</Text></LineSeg></Paragraph>"


def _cell(row, col, text, *, rowspan=1, colspan=1):
    return (f'<TableCell row="{row}" col="{col}" rowspan="{rowspan}" colspan="{colspan}">'
            + _p(text) + "</TableCell>")


def _table(cells, *, rows=1, cols=1):
    return (f'<TableControl><TableBody rows="{rows}" cols="{cols}">'
            + "".join("<TableRow>" + row + "</TableRow>" for row in cells)
            + "</TableBody></TableControl>")


def _hwp(body):
    return '<HwpDoc><DocInfo><Text>작성자 메타데이터</Text></DocInfo><BodyText><SectionDef>' + body + "</SectionDef></BodyText></HwpDoc>"


def test_law_preserves_raw_text_order_and_locations_but_excludes_amendment_reasons():
    raw = "  제1조(목적)  원문\n<개정 2021. 11. 3.> & 예외  \n"
    supplement = "부칙\n  과거 경과조치 <2010. 1. 1.>\n"
    source = ("<LawService><자치법규기본정보><전화번호>메타데이터</전화번호></자치법규기본정보>"
              + "<조문>" + _article("000000", "제1장 총칙\n", kind="N", title="")
              + _article("000100", raw) + "</조문>"
              + "<부칙><부칙공포일자>20251231</부칙공포일자><부칙공포번호>1839</부칙공포번호>"
              + "<부칙내용>" + escape(supplement) + "</부칙내용></부칙>"
              + "<제개정이유>검색에서 제외할 개정이유</제개정이유></LawService>")
    html = xml_to_html(source)
    parsed = _HTML(html)
    sections = parsed.select("section")
    assert [node["text"] for node in sections] == ["제1장 총칙\n", raw, supplement]
    assert sections[1]["attrs"]["data-source-location"] == "조문/조[2] (조문번호 000100)"
    assert sections[0]["attrs"]["data-unit-type"] == "heading"
    assert sections[2]["attrs"] == {
        "data-source-location": "부칙[1]/부칙내용", "data-unit-type": "supplement",
        "data-applicability-status": "historical_and_current_mixed_review_required",
        "data-promulgation-date": "20251231", "data-promulgation-number": "1839",
    }
    assert "개정이유" not in html and "메타데이터" not in html
    assert "&lt;개정" in html  # 개정 문구를 HTML 태그로 오인하지 않는다.


def test_full_article_deletion_does_not_mark_partial_deletion():
    source = ("<LawService><조문>" + _article("000100", "제1조 <삭제 2020. 1. 1.>")
              + _article("000200", "제2조(배출) 1. 삭제\n2. 이물질 제거 후 배출")
              + "</조문></LawService>")
    sections = _HTML(xml_to_html(source)).select("section")
    assert [s["attrs"]["data-deleted-article"] for s in sections] == ["true", "false"]
    assert "1. 삭제" in sections[1]["text"]


def test_hwp_section_boundaries_merges_control_characters_and_following_notes():
    table = _table([_cell(0, 0, "종이팩", rowspan=2) + _cell(0, 1, "씻어서 배출"),
                    _cell(1, 1, "오염 시 제외")], rows=2, cols=2)
    controls = ('<Paragraph><Text>  안내</Text><ControlChar name="FIXWIDTH_SPACE"/>'
                '<Text>조건</Text><Tab/><Text>A</Text><ControlChar name="PARAGRAPH_BREAK" char="&#13;"/></Paragraph>')
    source = _hwp(_p("[별표 1] <삭제 2003. 8. 4.>\n") + _p("[별표 2]\n")
                  + controls + table + _p("비고: 전용 수거함이 없을 때의 조건\n")
                  + _p("[별표 3]\n") + _p("<삭제 2020. 1. 1.>\n") + _p("삭제 구획"))
    parsed = _HTML(xml_to_html(source))
    sections = parsed.select("section")
    assert [(s["attrs"]["data-section-title"], s["attrs"]["data-deleted-section"]) for s in sections] == [
        ("[별표 1] <삭제 2003. 8. 4.>", "true"), ("[별표 2]", "false"),
        ("[별표 3]", "false"), ("[별표 3]", "true"),
    ]
    assert "  안내 조건\tA\n" in sections[1]["text"]
    assert "비고: 전용 수거함이 없을 때의 조건\n" in sections[1]["text"]
    cells = parsed.select("td")
    assert [c["text"] for c in cells] == ["종이팩", "씻어서 배출", "오염 시 제외"]
    assert cells[0]["attrs"] == {"data-cell-id": "table-1-r0-c0", "data-row": "0", "data-col": "0", "rowspan": "2", "colspan": "1"}
    assert parsed.select("tr")[1]["attrs"]["data-source-location"] == "table-1/row[1]"
    assert "작성자 메타데이터" not in parsed.select("body")[0]["text"]


def test_hwp_nested_table_and_note_keep_reading_order_without_duplicate_text():
    inner = _table([_cell(0, 0, "중첩 셀")])
    outer_cell = '<TableCell row="0" col="0" rowspan="1" colspan="1"><Paragraph><Text>앞</Text>' + inner + '<Text>뒤</Text></Paragraph></TableCell>'
    note = '<Paragraph><Text>본문</Text><FootNote number="1">' + _p("각주 예외") + '</FootNote><Text>계속</Text></Paragraph>'
    parsed = _HTML(xml_to_html(_hwp(_table([outer_cell]) + note)))
    assert [t["attrs"]["data-table-id"] for t in parsed.select("table")] == ["table-1", "table-2"]
    assert parsed.select("td")[0]["text"] == "앞중첩 셀뒤"
    assert parsed.select("body")[0]["text"] == "앞중첩 셀뒤본문각주 예외계속"
    assert parsed.select("aside")[0]["attrs"]["data-note-number"] == "1"


def test_hwp_images_are_identified_without_inventing_image_text():
    html = xml_to_html(_hwp(_p("표지 제목") + '<Paragraph><ShapePicture><PictureInfo/></ShapePicture></Paragraph>'))
    parsed = _HTML(html)
    assert parsed.select("body")[0]["text"] == "표지 제목"
    assert parsed.select("span")[0]["attrs"]["data-extraction-status"] == "unread"


@pytest.mark.parametrize("source", [
    '<!DOCTYPE LawService SYSTEM "file:///private"><LawService/>',
    '<!DOCTYPE HwpDoc [<!ENTITY x "expanded">]><HwpDoc>&x;</HwpDoc>',
    '<!ENTITY x "expanded"><LawService/>',
    "<unknown/>", "<HwpDoc>", "<HwpDoc/>", "<LawService/>",
])
def test_unsupported_or_unsafe_xml_is_rejected(source):
    with pytest.raises(XMLAdapterError):
        xml_to_html(source)


@pytest.mark.parametrize("table", [
    _table([_cell(-1, 0, "음수")]),
    _table([_cell(0, 0, "범위 초과", rowspan=2)]),
    _table([_cell(0, 0, "겹침", colspan=2) + _cell(0, 1, "중복")], cols=2),
    _table([_cell(0, 0, "누락")], cols=2),
    _table([_cell(0, 0, "0 병합", rowspan=0)]),
    '<TableControl/>',
])
def test_invalid_table_coordinates_do_not_produce_partial_html(table):
    with pytest.raises(XMLAdapterError):
        xml_to_html(_hwp(table))


@pytest.mark.parametrize("articles", [
    _article("000100", ""),
    _article("000100", "본문", kind="invalid"),
    _article("000100", "첫째") + _article("000100", "둘째"),
])
def test_invalid_law_units_are_rejected(articles):
    with pytest.raises(XMLAdapterError):
        xml_to_html("<LawService><조문>" + articles + "</조문></LawService>")
