"""표 행 청크의 임베딩·BM25 입력용 평문(실험).

담당 없음. 청크 ID와 본문(content)은 바꾸지 않고 검색 입력만 바꾼다.
송파구 시행규칙 별표의 표 행은 품목 이름이 "세   탁   기"처럼 글자 사이가 벌어져 있어
질문의 "세탁기"와 글자가 맞지 않는다. 이 모듈은 그 공백을 합치고(1번), 행에 표 제목·머리글을
붙인 평문을 만든다(2번). 표 행이 아닌 본문 문장은 건드리지 않는다.
"""

import json
import re
from typing import Any

# 한글 한 글자씩 공백·줄바꿈으로 떨어진 덩어리: "세   탁   기", "가\n전\n제\n품\n류"
# 앞뒤가 한글이면 단어 일부이므로 합치지 않는다(예: "이 조례"는 "조례"가 두 글자라 그대로 둔다).
_SPACED = re.compile(r"(?<![가-힣])(?:[가-힣]\s+)+[가-힣](?![가-힣])")
_WHITESPACE = re.compile(r"\s+")
# 표 제목 줄의 개정 이력 잡음: "[별표 2] <개정 98․6․12, ...>", "〔별표 6〕<개정 ...>"
_HISTORY = re.compile(
    r"^[\[〔]?(?:별표|별지)[^\n]*(?:<|＜)[^\n]*(?:개정|신설)|^<(?:개정|신설)"
)


def collapse_spaced_hangul(text: str) -> str:
    """글자 사이가 벌어진 한글 덩어리의 공백을 합친다. 이미 합쳐진 글에는 변화가 없다."""
    return _SPACED.sub(lambda m: _WHITESPACE.sub("", m.group(0)), text)


def _clean(text: object) -> str:
    return _WHITESPACE.sub(" ", collapse_spaced_hangul(str(text))).strip()


def _labels(header_rows: list[dict[str, Any]]) -> dict[int, list[str]]:
    labels: dict[int, list[str]] = {}
    for header in header_rows:
        for cell in header.get("cells", []):
            text = _clean(cell.get("text", ""))
            start = cell.get("origin_col", 0)
            for col in range(start, start + cell.get("colspan", 1)):
                if text and text not in labels.setdefault(col, []):
                    labels[col].append(text)
    return labels


def row_embedding_text(content: str) -> str | None:
    """표 행 청크의 JSON 본문을 임베딩·BM25용 평문으로 바꾼다. 표 행이 아니면 None.

    줄 구성: 표 제목·설명 문단(개정 이력 줄은 뺀다), 열 제목과 짝지은 셀 값.
    글자 사이가 벌어진 품목 이름은 합친다. 숫자·단위 같은 값은 그대로 둔다.
    """
    try:
        body = json.loads(content)
        row = body["row"]
        cells = row["cells"]
    except (ValueError, KeyError, TypeError):
        return None
    if not isinstance(cells, list):
        return None
    labels = _labels(body.get("header_rows", []))
    lines: list[str] = []
    for paragraph in body.get("paragraphs", []):
        line = _clean(paragraph)
        if line and not _HISTORY.match(line) and line not in lines:
            lines.append(line)
    for cell in cells:
        text = _clean(cell.get("text", ""))
        if not text:
            continue
        label = " / ".join(labels.get(cell.get("origin_col", 0), []))
        entry = f"{label}: {text}" if label else text
        if entry not in lines:
            lines.append(entry)
    return "\n".join(lines)


def search_text(text: str, content: str) -> str:
    """BM25·재정렬 입력(`chunk_text` 결과)용: 표 행 청크일 때만 글자 사이 공백을 합친다."""
    return (
        collapse_spaced_hangul(text)
        if row_embedding_text(content) is not None
        else text
    )
