"""원문을 보존한 검색용 텍스트와 병합 셀을 반영한 행 표현.

용어 복원은 명시된 표기 안의 공백만 제거한다. 일반 문단 경계를 임의로
붙이지 않으며, 이 자료를 실제 검색·청킹에 연결하는 작업은 별도다.
행 ID는 첨부 내부 범위이며 부모 MST·첨부 ID와 함께 사용한다.
"""

import re
from typing import TypedDict


class NormalizationChange(TypedDict):
    kind: str
    before: str
    after: str


class NormalizedSearchText(TypedDict):
    text: str
    changes: list[NormalizationChange]


class PreparedCell(TypedDict):
    cell_id: str
    origin_row: int
    origin_col: int
    columns: list[int]
    rowspan: int
    colspan: int
    inherited_from_previous_row: bool
    text: str
    search_text: str
    normalization_changes: list[NormalizationChange]


class PreparedRow(TypedDict):
    row_id: str
    table_id: str
    row: int
    cell_values: list[PreparedCell]
    missing_columns: list[int]
    search_text: str
    context_ref: str
    context_required: bool


# 실제 원문에 있는 표기. 동의어 치환·임의 형태소 결합 제외
KNOWN_JOIN_TERMS = (
    "폴리에틸렌테레프탈레이트",
    "음식물류전용용기납부필증",
    "일반규격봉투",
    "특수규격봉투",
    "공공용봉투",
    "생활폐기물용",
    "사업장용봉투",
    "생활용품류",
    "가전제품류",
    "합성수지류",
    "생활용봉투",
    "재사용봉투",
    "공동주택",
    "가구류",
    "기타류",
    "음식점",
)
_KNOWN_JOIN_PATTERN = re.compile(
    "|".join(
        r"\s*".join(re.escape(char) for char in term)
        for term in sorted(KNOWN_JOIN_TERMS, key=len, reverse=True)
    )
)


def normalize_search_text(text: str) -> NormalizedSearchText:
    """명시 용어 내부 공백 복원과 검색용 공백 정리. 원문 문자열은 불변."""
    if not isinstance(text, str):
        raise TypeError("검색용 정규화 입력은 문자열 필요")
    changes: list[NormalizationChange] = []

    def join_term(match: re.Match[str]) -> str:
        before = match.group(0)
        after = re.sub(r"\s+", "", before)
        if before != after:
            changes.append(
                {"kind": "join_known_term", "before": before, "after": after}
            )
        return after

    joined = _KNOWN_JOIN_PATTERN.sub(join_term, text)
    normalized = " ".join(joined.split())
    if joined != normalized:
        changes.append(
            {
                "kind": "normalize_whitespace",
                "before": joined,
                "after": normalized,
            }
        )
    return {"text": normalized, "changes": changes}


def _positive_integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"표의 {field}는 양의 정수 필요")
    return value


def prepare_table_rows(table: dict) -> list[PreparedRow]:
    """row_cell_ids로 병합 값을 각 행에 연결. 각주·비고와 함께 읽는 초안 반환.

    원본 표·셀·문단을 변경하지 않는다. 잘못된 좌표나 누락된 셀 참조는
    빈 텍스트로 숨기지 않고 오류로 중단한다. 빈 좌표는 missing_columns로 구분한다.
    """
    table_id = table.get("table_id")
    if not isinstance(table_id, str) or not table_id:
        raise ValueError("table_id 문자열 필요")
    row_count = _positive_integer(table.get("rows"), "rows")
    col_count = _positive_integer(table.get("cols"), "cols")
    cells = table.get("cells")
    grid = table.get("row_cell_ids")
    if not isinstance(cells, list) or not isinstance(grid, list):
        raise ValueError("cells·row_cell_ids 목록 필요")
    if len(grid) != row_count:
        raise ValueError("행 개수와 row_cell_ids 불일치")

    by_id = {}
    normalized_cells = {}
    for cell in cells:
        if not isinstance(cell, dict):
            raise ValueError("셀 객체 필요")
        cell_id = cell.get("cell_id")
        if not isinstance(cell_id, str) or not cell_id or cell_id in by_id:
            raise ValueError("고유한 cell_id 필요")
        text = cell.get("text")
        if not isinstance(text, str):
            raise ValueError("셀 text 문자열 필요")
        origin_row, origin_col = cell.get("row"), cell.get("col")
        for coordinate, limit in ((origin_row, row_count), (origin_col, col_count)):
            if (
                isinstance(coordinate, bool)
                or not isinstance(coordinate, int)
                or not 0 <= coordinate < limit
            ):
                raise ValueError("셀 원점 좌표 범위 확인 필요")
        rowspan = _positive_integer(cell.get("rowspan"), "rowspan")
        colspan = _positive_integer(cell.get("colspan"), "colspan")
        if origin_row + rowspan > row_count or origin_col + colspan > col_count:
            raise ValueError("셀 병합 범위가 표를 벗어남")
        by_id[cell_id] = cell
        normalized_cells[cell_id] = normalize_search_text(text)

    rows: list[PreparedRow] = []
    used_ids = set()
    for row_index, ids in enumerate(grid):
        if not isinstance(ids, list) or len(ids) != col_count:
            raise ValueError("열 개수와 row_cell_ids 불일치")
        row_cells: dict[str, PreparedCell] = {}
        missing_columns = []
        for column, cell_id in enumerate(ids):
            if cell_id is None:
                missing_columns.append(column)
                continue
            if not isinstance(cell_id, str) or cell_id not in by_id:
                raise ValueError("존재하지 않는 셀 참조")
            cell = by_id[cell_id]
            if not (
                cell["row"] <= row_index < cell["row"] + cell["rowspan"]
                and cell["col"] <= column < cell["col"] + cell["colspan"]
            ):
                raise ValueError("셀 참조와 원본 병합 좌표 불일치")
            used_ids.add(cell_id)
            if cell_id in row_cells:
                row_cells[cell_id]["columns"].append(column)
                continue
            normalized = normalized_cells[cell_id]
            row_cells[cell_id] = {
                "cell_id": cell_id,
                "origin_row": cell["row"],
                "origin_col": cell["col"],
                "columns": [column],
                "rowspan": cell["rowspan"],
                "colspan": cell["colspan"],
                "inherited_from_previous_row": cell["row"] < row_index,
                "text": cell["text"],
                "search_text": normalized["text"],
                "normalization_changes": [
                    dict(change) for change in normalized["changes"]
                ],
            }
        values = list(row_cells.values())
        rows.append(
            {
                "row_id": f"{table_id}-row-{row_index}",
                "table_id": table_id,
                "row": row_index,
                "cell_values": values,
                "missing_columns": missing_columns,
                "search_text": " | ".join(
                    value["search_text"] for value in values if value["search_text"]
                ),
                "context_ref": "attachment.blocks",
                "context_required": True,
            }
        )
    if used_ids != set(by_id):
        raise ValueError("행 참조에서 누락된 원본 셀")
    return rows
