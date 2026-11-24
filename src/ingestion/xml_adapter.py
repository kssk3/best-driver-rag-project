"""법령 API XML과 HWP 구조 XML을 공통 HTML 본문으로 변환한다.

XML 입력을 보존하고 검색 표현만 변환한다. JSON의 검색용 공백 정규화나
사람 검수 보정을 적용하지 않으며, 그림 내용과 현행 법규의 적용 여부를 추정하지 않는다.
"""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html import escape
from collections.abc import Iterator


class XMLAdapterError(ValueError):
    """지원하지 않는 XML 또는 의미를 보존할 수 없는 구조다."""


_ANNEX_TITLE = re.compile(r"^[〔【\[]\s*별표\s*\d+")
_DELETED_ARTICLE = re.compile(
    r"제\s*\d+\s*조(?:의\s*\d+)?\s*(?:\([^)]*\)\s*)?"
    r"(?:삭제\s*(?:<[^<>]*>)?|<\s*삭제[^<>]*>)"
)


def _attrs(**values: object) -> str:
    return "".join(
        f' {key.replace("_", "-")}="{escape(str(value), quote=True)}"'
        for key, value in values.items()
    )


def _required_text(node: ET.Element, tag: str) -> str:
    child = node.find(tag)
    if child is None:
        raise XMLAdapterError(f"{node.tag}/{tag} 요소가 없습니다.")
    text = "".join(child.itertext())
    if not text.strip():
        raise XMLAdapterError(f"{node.tag}/{tag} 본문이 비어 있습니다.")
    return text


def _law_html(root: ET.Element) -> str:
    parts: list[str] = []
    article_index = supplement_index = 0
    seen_articles: set[str] = set()
    for group in root:
        if group.tag == "조문":
            for article in group.findall("조"):
                article_index += 1
                number = article.findtext("조문번호", "")
                kind = article.findtext("조문여부", "")
                if not number or kind not in {"Y", "N"}:
                    raise XMLAdapterError(f"조문/조[{article_index}]: 조문번호/조문여부가 잘못되었습니다.")
                if kind == "Y" and number in seen_articles:
                    raise XMLAdapterError(f"중복 조문번호: {number}")
                if kind == "Y":
                    seen_articles.add(number)
                raw_text = _required_text(article, "조내용")
                title = article.findtext("조제목", "")
                deleted = kind == "Y" and (
                    title.strip() == "삭제" or bool(_DELETED_ARTICLE.fullmatch(raw_text.strip()))
                )
                attrs = _attrs(
                    data_source_location=f"조문/조[{article_index}] (조문번호 {number})",
                    data_unit_type="article" if kind == "Y" else "heading",
                    data_article_number=number,
                    data_section_title=title,
                    data_deleted_article=str(deleted).lower(),
                )
                parts.append(f"<section{attrs}><p>{escape(raw_text)}</p></section>")
        elif group.tag == "부칙":
            supplement_index += 1
            text = _required_text(group, "부칙내용")
            attrs = _attrs(
                data_source_location=f"부칙[{supplement_index}]/부칙내용",
                data_unit_type="supplement",
                data_applicability_status="historical_and_current_mixed_review_required",
                data_promulgation_date=group.findtext("부칙공포일자", ""),
                data_promulgation_number=group.findtext("부칙공포번호", ""),
            )
            parts.append(f"<section{attrs}><p>{escape(text)}</p></section>")
        # 제개정이유, 연락처, 첨부 목록은 조문 본문에 섞지 않는다.
    if not article_index:
        raise XMLAdapterError("LawService에 조문 본문이 없습니다.")
    return "".join(parts)


@dataclass
class _Block:
    kind: str
    text: str
    html: str


class _HwpRenderer:
    def __init__(self, body: ET.Element):
        self.body = body
        self.table_ids = {
            node: f"table-{index}" for index, node in enumerate(body.iter("TableControl"), 1)
        }

    def _pieces(self, node: ET.Element) -> Iterator[str | _Block]:
        if node.tag == "Text":
            yield node.text or ""
        elif node.tag == "Tab":
            yield "\t"
        elif node.tag == "ControlChar":
            name = node.get("name", "")
            if name == "PARAGRAPH_BREAK":
                yield "\n"
            elif name in {"FIXWIDTH_SPACE", "NBSPACE", "TAB"}:
                yield " "
            else:
                yield node.get("char", "")
        elif node.tag == "TableControl":
            yield _Block("table", "", self._table(node))
        elif node.tag == "Paragraph":
            yield from self._paragraph(node)
        elif node.tag in {"FootNote", "Footnote", "EndNote", "Endnote"}:
            blocks = list(self._walk_children(node))
            attrs = _attrs(data_note_type=node.tag, data_note_number=node.get("number", ""))
            yield _Block("note", "".join(b.text for b in blocks),
                         f"<aside{attrs}>" + "".join(b.html for b in blocks) + "</aside>")
        elif node.tag in {"Picture", "ShapePicture"}:
            # 자리 표시의 설명도 원문 텍스트에 추가하지 않는다. 그림 보정은 별도 검수다.
            yield _Block("image", "", '<span data-embedded-object="image" data-extraction-status="unread"></span>')
        else:
            for child in node:
                yield from self._pieces(child)

    def _paragraph(self, node: ET.Element) -> Iterator[_Block]:
        buffer: list[str] = []
        emitted = False
        for child in node:
            for piece in self._pieces(child):
                if isinstance(piece, str):
                    buffer.append(piece)
                else:
                    if buffer:
                        text = "".join(buffer)
                        yield _Block("paragraph", text, f"<p>{escape(text)}</p>")
                        buffer.clear()
                    yield piece
                    emitted = True
        if buffer or not emitted:
            text = "".join(buffer)
            yield _Block("paragraph", text, f"<p>{escape(text)}</p>")

    def _walk_children(self, node: ET.Element) -> Iterator[_Block]:
        for child in node:
            for piece in self._pieces(child):
                if isinstance(piece, _Block):
                    yield piece
                elif piece:
                    yield _Block("paragraph", piece, f"<p>{escape(piece)}</p>")

    @staticmethod
    def _integer(node: ET.Element, key: str, *, minimum: int = 0) -> int:
        value = node.get(key, "")
        if not re.fullmatch(r"[0-9]+", value) or int(value) < minimum:
            raise XMLAdapterError(f"{node.tag}의 {key} 값이 잘못되었습니다: {value!r}")
        return int(value)

    def _table(self, node: ET.Element) -> str:
        body = node.find("TableBody")
        if body is None:
            raise XMLAdapterError("TableControl/TableBody가 없습니다.")
        rows = self._integer(body, "rows", minimum=1)
        cols = self._integer(body, "cols", minimum=1)
        if rows * cols > 100_000:
            raise XMLAdapterError("표가 지원 크기 100,000칸을 초과했습니다.")
        table_id = self.table_ids[node]
        occupied: set[tuple[int, int]] = set()
        starts: dict[tuple[int, int], str] = {}
        for cell in body.findall("./TableRow/TableCell"):
            row, col = self._integer(cell, "row"), self._integer(cell, "col")
            rowspan = self._integer(cell, "rowspan", minimum=1)
            colspan = self._integer(cell, "colspan", minimum=1)
            if row + rowspan > rows or col + colspan > cols:
                raise XMLAdapterError(f"{table_id}: 셀 좌표/병합이 표 범위를 벗어납니다.")
            slots = {(r, c) for r in range(row, row + rowspan) for c in range(col, col + colspan)}
            if occupied.intersection(slots):
                raise XMLAdapterError(f"{table_id}: 셀 좌표/병합 영역이 겹칩니다.")
            occupied.update(slots)
            attrs = _attrs(data_cell_id=f"{table_id}-r{row}-c{col}", data_row=row, data_col=col,
                           rowspan=rowspan, colspan=colspan)
            starts[row, col] = f"<td{attrs}>" + "".join(b.html for b in self._walk_children(cell)) + "</td>"
        if len(occupied) != rows * cols:
            raise XMLAdapterError(f"{table_id}: 누락된 표 셀 좌표가 있습니다.")
        attrs = _attrs(data_table_id=table_id, data_source_location=table_id)
        rendered_rows = []
        for row in range(rows):
            row_attrs = _attrs(data_row_index=row, data_source_location=f"{table_id}/row[{row}]")
            rendered_rows.append(f"<tr{row_attrs}>" + "".join(starts.get((row, col), "") for col in range(cols)) + "</tr>")
        # 캡션 등 TableBody 외의 본문도 버리지 않고 표 직전에 보존한다.
        caption = "".join(block.html for child in node if child is not body
                          for block in self._walk_children(child))
        return caption + f"<table{attrs}>" + "".join(rendered_rows) + "</table>"

    def html(self) -> str:
        sections: list[str] = []
        current: list[str] = []
        title, deleted = "", False

        def flush() -> None:
            if current:
                attrs = _attrs(data_section_title=title, data_deleted_section=str(deleted).lower())
                sections.append(f"<section{attrs}>" + "".join(current) + "</section>")
                current.clear()

        for block in self._walk_children(self.body):
            text = block.text.strip()
            if block.kind == "paragraph" and _ANNEX_TITLE.match(text):
                flush()
                title, deleted = text, "삭제" in text
            elif block.kind == "paragraph" and text.startswith("<삭제") and not deleted:
                # 같은 별표 제목 안에서도 이 지점 이후만 삭제로 표시한다.
                flush()
                deleted = True
            current.append(block.html)
        flush()
        if not sections:
            raise XMLAdapterError("HwpDoc/BodyText에 추출할 본문이 없습니다.")
        return "".join(sections)


def xml_to_html(content: str) -> str:
    """LawService/HwpDoc만 변환한다. XML 내부 DTD와 엔티티 선언은 허용하지 않는다."""
    if not isinstance(content, str) or not content.strip():
        raise XMLAdapterError("비어 있지 않은 XML 문자열이 필요합니다.")
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", content, re.IGNORECASE):
        raise XMLAdapterError("XML DTD/entity 선언은 지원하지 않습니다.")
    try:
        root = ET.fromstring(content)
    except ET.ParseError as error:
        raise XMLAdapterError(f"XML 문법 오류: {error}") from error
    if root.tag == "LawService":
        body = _law_html(root)
    elif root.tag == "HwpDoc":
        source = root.find("BodyText")
        if source is None:
            raise XMLAdapterError("HwpDoc/BodyText가 없습니다.")
        body = _HwpRenderer(source).html()
    else:
        raise XMLAdapterError(f"지원하지 않는 XML 루트: {root.tag}")
    return '<!doctype html><html lang="ko"><head><meta charset="utf-8"></head><body>' + body + "</body></html>"
