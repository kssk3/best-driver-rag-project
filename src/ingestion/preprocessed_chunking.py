"""jungeun v2 JSON과 XML 어댑터 HTML의 조문/표 행을 대응시키는 청킹.

전체 삭제 표시가 있는 조문/별표 구역은 제외한다. 부칙은 과거/현행 혼재
주의를 보존한다. 표 행에는 첫 행의 병합 범위에 해당하는 머리글과 같은
구역의 모든 문단(후행 비고 포함)을 반복한다. search_text 정규화 대신
원문 text를 쓰므로 이 경로는 표현/청킹 비교이며 정규화 효과 비교가 아니다.
"""

import hashlib
import json
from dataclasses import dataclass, field
from html import escape
from html.parser import HTMLParser

from src.contracts import Chunk, SourceDocument


class PreprocessedChunkingError(ValueError):
    """알 수 없는 구조나 보존할 수 없는 청크를 명시적으로 거부한다."""


_HISTORY = "historical_and_current_mixed_review_required"
_HISTORY_NOTE = "과거 부칙의 시행일\u00b7경과조치 포함. 현행 일반 배출 기준으로 일괄 적용 금지."
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _text(value, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name}은 문자열이어야 합니다.")
    return value


def _list(value, name: str) -> list:
    if not isinstance(value, list):
        raise ValueError(f"{name}은 목록이어야 합니다.")
    return value


def _int(value, name: str, minimum=0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name}은 {minimum} 이상의 정수여야 합니다.")
    return value


def _deleted(value=False) -> bool:
    if not isinstance(value, bool):
        raise ValueError("삭제 표시는 bool이어야 합니다.")
    return value


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"JSON 중복 키: {key}")
        result[key] = value
    return result


def _load_json(content: str):
    def invalid(value):
        raise ValueError(f"JSON 비유한 값: {value}")
    return json.loads(content, object_pairs_hook=_object, parse_constant=invalid)


@dataclass
class _Cell:
    cell_id: str
    row: int
    col: int
    rowspan: int
    colspan: int
    text: str
    html: str = ""

    def value(self, row: int) -> dict:
        return {
            "cell_id": self.cell_id, "origin_row": self.row, "origin_col": self.col,
            "rowspan": self.rowspan, "colspan": self.colspan,
            "inherited_from_previous_row": self.row < row, "text": self.text,
        }


def _grid(cells: list[_Cell], rows: int, cols: int) -> list[list[_Cell]]:
    # XML 어댑터와 같은 한도를 메모리 할당 전에 적용한다.
    if rows * cols > 100_000:
        raise ValueError("표가 지원 크기 100,000칸을 초과했습니다.")
    grid = [[None] * cols for _ in range(rows)]
    seen = set()
    for cell in cells:
        if cell.cell_id in seen:
            raise ValueError(f"중복 셀 ID: {cell.cell_id}")
        seen.add(cell.cell_id)
        if cell.row + cell.rowspan > rows or cell.col + cell.colspan > cols:
            raise ValueError(f"셀 병합 범위가 표를 벗어납니다: {cell.cell_id}")
        for row in range(cell.row, cell.row + cell.rowspan):
            for col in range(cell.col, cell.col + cell.colspan):
                if grid[row][col] is not None:
                    raise ValueError(f"셀 병합 범위가 겹칩니다: {cell.cell_id}")
                grid[row][col] = cell
    result = []
    for row in grid:
        if any(cell is None for cell in row):
            raise ValueError("표에 누락된 열이 있어 셀 관계를 보장할 수 없습니다.")
        # colspan으로 여러 열을 차지한 같은 셀은 한 번만 기록한다.
        result.append([cell for i, cell in enumerate(row) if i == 0 or cell is not row[i - 1]])
    return result


def _json_rows(table: dict) -> list[list[_Cell]]:
    rows = _int(table["rows"], "rows", 1)
    cols = _int(table["cols"], "cols", 1)
    cells = [
        _Cell(_text(cell["cell_id"], "cell_id"), _int(cell["row"], "row"),
              _int(cell["col"], "col"), _int(cell["rowspan"], "rowspan", 1),
              _int(cell["colspan"], "colspan", 1), _text(cell["text"], "cell text"))
        for cell in _list(table["cells"], "cells")
    ]
    grid = _grid(cells, rows, cols)
    searches = _list(table["rows_for_search"], "rows_for_search")
    if len(searches) != rows:
        raise ValueError("rows_for_search 행 수가 표와 다릅니다.")
    for row, (search, expected) in enumerate(zip(searches, grid, strict=True)):
        if search["row"] != row or search.get("table_id") != table["table_id"]:
            raise ValueError("rows_for_search 행/표 위치가 맞지 않습니다.")
        if search.get("missing_columns"):
            raise ValueError("rows_for_search에 누락된 열이 있습니다.")
        values = _list(search["cell_values"], "cell_values")
        if [cell["cell_id"] for cell in values] != [cell.cell_id for cell in expected]:
            raise ValueError("rows_for_search의 병합셀 상속이 원본 셀과 다릅니다.")
        for value, cell in zip(values, expected, strict=True):
            if any(value.get(key) != expected_value for key, expected_value in cell.value(row).items()):
                raise ValueError(f"rows_for_search 원문/병합 정보가 다릅니다: {cell.cell_id}")
            if value.get("columns") != list(range(cell.col, cell.col + cell.colspan)):
                raise ValueError(f"rows_for_search의 열 범위가 다릅니다: {cell.cell_id}")
            # 검증한 rows_for_search의 원문 text를 사용한다. search_text는 쓰지 않는다.
            cell.text = value["text"]
    return grid


def _header_count(rows: list[list[_Cell]]) -> int:
    # 별도 semantic header flag가 없으므로 첫 행과 그 셀의 수직 병합 범위를
    # 공통 머리글로 둔다. 이 규칙을 JSON/HTML에 동일하게 적용한다.
    return max(cell.rowspan for cell in rows[0])


def _json_body(data: dict):
    for unit in _list(data["units"], "units"):
        if _deleted(unit.get("deleted_article", False)):
            continue
        if unit["unit_type"] not in {"article", "heading"}:
            raise ValueError(f"알 수 없는 본문 단위: {unit['unit_type']}")
        text = _text(unit.get("raw_text", unit.get("text")), "unit text")
        if text.strip():
            yield _text(unit["source_location"], "source_location"), {
                "unit_type": unit["unit_type"], "text": text,
            }
    for supplement in _list(data["supplementary_provisions"], "supplementary_provisions"):
        yield _text(supplement["source_location"], "source_location"), {
            "unit_type": "supplement", "text": _text(supplement.get("raw_text", supplement.get("text")), "supplement text"),
            "applicability_status": supplement.get("applicability_status", _HISTORY),
            "note": supplement.get("note", _HISTORY_NOTE),
            "promulgation_date": supplement.get("promulgation_date", ""),
            "promulgation_number": supplement.get("promulgation_number", ""),
        }


def _json_annex(data: dict):
    if _deleted(data.get("deleted_marker", False)):
        return
    tables = {}
    for table in _list(data["tables"], "tables"):
        table_id = _text(table["table_id"], "table_id")
        if table_id in tables:
            raise ValueError(f"중복 표: {table_id}")
        tables[table_id] = table
    sections = []
    for block in _list(data["blocks"], "blocks"):
        key = (_text(block["section_title"], "section_title"), _deleted(block.get("deleted_section", False)))
        if not sections or sections[-1][0] != key:
            sections.append((key, []))
        sections[-1][1].append(block)
    referenced = set()
    for section_number, ((title, deleted), blocks) in enumerate(sections, 1):
        context, section_tables = [], []
        for block in blocks:
            if block["type"] == "paragraph":
                context.append(_text(block["text"], "paragraph text"))
            elif block["type"] == "table":
                table_id = block["table_id"]
                if table_id not in tables or table_id in referenced:
                    raise ValueError(f"누락되거나 중복된 표 참조: {table_id}")
                referenced.add(table_id)
                table = tables[table_id]
                if table["section_title"] != title or _deleted(table.get("deleted_section", False)) != deleted:
                    raise ValueError(f"표와 구역의 정보가 다릅니다: {table_id}")
                section_tables.append(table)
            else:
                raise ValueError(f"알 수 없는 별표 블록: {block['type']}")
        if deleted:
            continue
        common = {"section_title": title, "paragraphs": context}
        if not section_tables and any(text.strip() for text in context):
            yield f"section[{section_number}]/paragraphs", common
        for table in section_tables:
            rows = _json_rows(table)
            headers = [{"row": n, "cells": [cell.value(n) for cell in cells]}
                       for n, cells in enumerate(rows[:_header_count(rows)])]
            for number, cells in enumerate(rows):
                yield f"{table['table_id']}/row[{number}]", {
                    **common, "table_id": table["table_id"], "header_rows": headers,
                    "row": {"row": number, "cells": [cell.value(number) for cell in cells]},
                }
    if referenced != set(tables):
        raise ValueError("blocks에서 참조하지 않는 표가 있어 문맥을 정할 수 없습니다.")


@dataclass
class _Node:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list = field(default_factory=list)
    parent: "_Node | None" = field(default=None, repr=False)

    def inner(self) -> str:
        return "".join(child.render() if isinstance(child, _Node) else escape(child) for child in self.children)

    def render(self) -> str:
        attrs = "".join(f' {name}="{escape(value, quote=True)}"' for name, value in self.attrs.items())
        return f"<{self.tag}{attrs}>" + ("" if self.tag in _VOID else self.inner() + f"</{self.tag}>")

    def text(self) -> str:
        return "".join(child.text() if isinstance(child, _Node) else child for child in self.children)

    def walk(self, tag: str):
        for child in self.children:
            if isinstance(child, _Node):
                if child.tag == tag:
                    yield child
                yield from child.walk(tag)

    def ancestor(self, tag: str):
        node = self.parent
        while node is not None:
            if node.tag == tag:
                return node
            node = node.parent
        return None


class _HTML(HTMLParser):
    def __init__(self, content: str):
        super().__init__(convert_charrefs=True)
        self.root = _Node("")
        self.stack = [self.root]
        self.feed(content)
        self.close()
        if len(self.stack) != 1:
            raise ValueError("HTML 종료 태그가 누락되었습니다.")

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, {k: v or "" for k, v in attrs}, parent=self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.stack.pop()

    def handle_endtag(self, tag):
        if len(self.stack) == 1 or self.stack[-1].tag != tag:
            raise ValueError(f"HTML 종료 태그가 맞지 않습니다: {tag}")
        self.stack.pop()

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def _flag(node: _Node, name: str) -> bool:
    value = node.attrs.get(name, "false")
    if value not in {"true", "false"}:
        raise ValueError(f"{name}은 true/false여야 합니다.")
    return value == "true"


def _html_rows(table: _Node) -> list[list[_Cell]]:
    if list(table.walk("table")):
        raise ValueError("중첩표는 상위 셀과의 대응 규격이 없어 행 청킹할 수 없습니다.")
    row_nodes = list(table.walk("tr"))
    cells = []
    for number, row in enumerate(row_nodes):
        if int(row.attrs["data-row-index"]) != number:
            raise ValueError("HTML 표 행 번호가 연속적이지 않습니다.")
        for node in [*row.walk("td"), *row.walk("th")]:
            origin_row, origin_col = int(node.attrs["data-row"]), int(node.attrs["data-col"])
            if origin_row != number:
                raise ValueError("HTML 셀의 원점 행과 표 행이 다릅니다.")
            cells.append(_Cell(
                node.attrs["data-cell-id"], _int(origin_row, "cell row"), _int(origin_col, "cell col"),
                _int(int(node.attrs.get("rowspan", "1")), "rowspan", 1),
                _int(int(node.attrs.get("colspan", "1")), "colspan", 1), node.text(), node.inner(),
            ))
    if not row_nodes or not cells:
        raise ValueError("빈 HTML 표는 행 청킹할 수 없습니다.")
    return _grid(cells, len(row_nodes), max(cell.col + cell.colspan for cell in cells))


def _context_html(node: _Node) -> str:
    # 표 앞/뒤 순서와 무관하게 같은 section의 모든 서술을 보존한다.
    parts = []
    for child in node.children:
        if isinstance(child, str):
            parts.append(escape(child))
        elif child.tag != "table" and not (child.tag == "aside" and child.attrs.get("data-review-overlay") == "image-summary"):
            if list(child.walk("table")):
                raise ValueError("표를 감싼 별도 요소의 문맥 규격을 확인해야 합니다.")
            parts.append(child.render())
    return "".join(parts)


def _row_html(number: int, cells: list[_Cell]) -> str:
    content = []
    for cell in cells:
        content.append(
            f'<td data-cell-id="{escape(cell.cell_id, quote=True)}" data-origin-row="{cell.row}" '
            f'data-origin-col="{cell.col}" data-original-rowspan="{cell.rowspan}" '
            f'data-inherited="{str(cell.row < number).lower()}" colspan="{cell.colspan}">{cell.html}</td>'
        )
    # 수직 병합 값을 현재 행에 반복하고 원점/원래 span을 명시한다. 출력의
    # rowspan을 1로 풀어 머리글/단일 행의 잘못된 셀 겹침을 만들지 않는다.
    return f'<tr data-row-index="{number}">' + "".join(content) + "</tr>"


def _html_parts(content: str):
    root = _HTML(content).root
    overlays = [node for node in root.walk("aside") if node.attrs.get("data-review-overlay") == "image-summary"]
    if len(overlays) > 1:
        raise ValueError("이미지 검수 요약이 여러 개여서 대응할 수 없습니다.")
    summary = _load_json(overlays[0].text()) if overlays else None
    if summary is not None and not isinstance(summary, dict):
        raise ValueError("이미지 검수 요약은 JSON 객체여야 합니다.")
    overlay = f'<aside data-review-overlay="image-summary">{escape(_dump(summary))}</aside>' if summary is not None else ""
    sections = list(root.walk("section"))
    if not sections:
        raise ValueError("XML 어댑터의 section 정보가 없는 HTML입니다.")
    def check_outside(node, inside=False):
        if node.tag == "head" or (node.tag == "aside" and node.attrs.get("data-review-overlay") == "image-summary"):
            return
        inside = inside or node.tag == "section"
        for child in node.children:
            if isinstance(child, _Node):
                check_outside(child, inside)
            elif child.strip() and not inside:
                raise ValueError("section 밖 서술문의 적용 범위를 확인해야 합니다.")
    check_outside(root)
    for paragraph in root.walk("p"):
        if paragraph.ancestor("section") is None and paragraph.ancestor("aside") is None and paragraph.text().strip():
            raise ValueError("section 밖 문단의 적용 범위를 확인해야 합니다.")
    for number, section in enumerate(sections, 1):
        if section.ancestor("section") is not None:
            raise ValueError("중첩 section은 지원하지 않습니다.")
        if "data-unit-type" in section.attrs:
            kind = section.attrs["data-unit-type"]
            if kind not in {"article", "heading", "supplement"}:
                raise ValueError(f"알 수 없는 본문 단위: {kind}")
            if _flag(section, "data-deleted-article"):
                continue
            location = section.attrs["data-source-location"]
            text = section.render()
            if kind == "supplement":
                state = section.attrs.get("data-applicability-status", _HISTORY)
                text += f'<aside data-applicability-status="{escape(state, quote=True)}">{escape(_HISTORY_NOTE)}</aside>'
            yield location, text + overlay
        elif "data-section-title" in section.attrs:
            if _flag(section, "data-deleted-section"):
                continue
            title = section.attrs["data-section-title"]
            context = _context_html(section)
            tables = list(section.walk("table"))
            if not tables and section.text().strip():
                yield f"section[{number}]/paragraphs", section.render() + overlay
            for table in tables:
                table_id = table.attrs["data-table-id"]
                rows = _html_rows(table)
                headers = "".join(_row_html(n, row) for n, row in enumerate(rows[:_header_count(rows)]))
                for row_number, cells in enumerate(rows):
                    value = (f'<section data-section-title="{escape(title, quote=True)}">{context}'
                             f'<table data-table-id="{escape(table_id, quote=True)}"><thead>{headers}</thead>'
                             f'<tbody>{_row_html(row_number, cells)}</tbody></table></section>{overlay}')
                    yield f"{table_id}/row[{row_number}]", value
        else:
            raise ValueError("알 수 없는 HTML section 규격입니다.")


def chunk_preprocessed_documents(
    documents: list[SourceDocument], *, max_characters: int = 12000,
    chunking_version: str = "preprocessed-v2-row-v1",
) -> list[Chunk]:
    """원본은 유지하며 승인된 두 전처리 스키마/HTML 표현만 구조적으로 청킹한다.

    길이는 토큰이 아닌 문자 수다. 각주/병합 맥락을 포함한 청크가 한도를
    넘으면 전체 호출을 실패시키며 자르거나 누락된 성공 결과를 반환하지 않는다.
    """
    _int(max_characters, "max_characters", 1)
    if not isinstance(chunking_version, str) or not chunking_version.strip():
        raise ValueError("chunking_version은 비어 있지 않은 문자열이어야 합니다.")
    chunks, sources, identities = [], set(), set()
    for document in documents:
        if not isinstance(document, SourceDocument):
            raise TypeError("SourceDocument 목록이 필요합니다.")
        key = (document.document_id, document.version, document.content_format)
        if key in sources:
            raise PreprocessedChunkingError(f"문서 {document.document_id!r}: 중복 문서/버전/형식")
        sources.add(key)
        try:
            if document.content_format == "json":
                data = _load_json(document.content)
                if not isinstance(data, dict):
                    raise ValueError("전처리 JSON은 객체여야 합니다.")
                schema = data.get("schema_version")
                if schema == "jungeun-body-draft-v2":
                    raw_parts = _json_body(data)
                elif schema == "jungeun-annex-draft-v2":
                    raw_parts = _json_annex(data)
                else:
                    raise ValueError(f"알 수 없는 JSON schema_version: {schema!r}")
                summary = data.get("structured_image_summary")
                if summary is not None and not isinstance(summary, dict):
                    raise ValueError("structured_image_summary는 객체여야 합니다.")
                parts = ((location, _dump({**value, **({"structured_image_summary": summary} if summary is not None else {})}))
                         for location, value in raw_parts)
            elif document.content_format == "html":
                parts = _html_parts(document.content)
            else:
                raise ValueError(f"알 수 없는 표현 형식: {document.content_format}")
            for location, content in parts:
                if not location.strip():
                    raise ValueError("원문 위치가 비어 있습니다.")
                if len(content) > max_characters:
                    raise ValueError(f"{location}: 문맥 포함 {len(content)}자가 한도 {max_characters}를 초과합니다. 잘라내지 않습니다.")
                identity = {
                    "document_id": document.document_id, "version": document.version,
                    "format": document.content_format, "content": content, "location": location,
                    "source_url": document.source_url, "chunking_version": chunking_version,
                }
                digest = hashlib.sha256(_dump(identity).encode("utf-8")).hexdigest()
                if digest in identities:
                    raise ValueError(f"중복 청크 위치/내용: {location}")
                identities.add(digest)
                chunks.append(Chunk(
                    chunk_id=f"chunk-{digest}", source_document_id=document.document_id,
                    source_document_version=document.version, title=document.title,
                    content_format=document.content_format, content=content,
                    source_url=document.source_url, source_location=location,
                    scope_type=document.scope_type, districts=list(document.districts),
                    conditions=[], chunking_version=chunking_version,
                ))
        except (ValueError, KeyError, TypeError, IndexError) as error:
            raise PreprocessedChunkingError(f"문서 {document.document_id!r} ({document.version}/{document.content_format}): {error}") from error
    return chunks
