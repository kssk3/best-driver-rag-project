"""청킹 결과의 현황을 한 줄로 요약해 CSV에 누적한다.

담당: 이승주
`scripts.prepare_data`가 만든 `chunks-html.json` 또는 `chunks-json.json`을 읽는다. 외부 호출은 하지 않는다.
청킹 버전(`chunking_version`)과 형식(`content_format`)은 청크에서 읽는다. 한 파일에 여러 값이 섞여 있으면 거부한다.
python -m scripts.chunk_stats --help 참조.
"""

import argparse
import csv
import hashlib
import html
import json
import re
import statistics
from collections import Counter
from pathlib import Path

# 이 길이(태그를 뺀 글자 수)보다 짧으면 맥락이 부족한 청크로 센다. 기준은 정해진 값이 아니라 점검용 임시 기준이다.
SHORT_PLAIN_CHARS = 100

COLUMNS = [
    "chunking_version",
    "format",
    "chunk_count",
    "documents",
    "서대문구",
    "송파구",
    "공통",
    "범위미상",
    "article_chunks",
    "heading_chunks",
    "table_row_chunks",
    "other_chunks",
    "conditions_empty",
    "deleted_marker_chunks",
    "short_chunks",
    "duplicate_plain_chunks",
    "content_min",
    "content_median",
    "content_p90",
    "content_max",
    "plain_min",
    "plain_median",
    "plain_p90",
    "plain_max",
    "chunks_sha256",
]


def plain_text(content: str, content_format: str = "html") -> str:
    """공백을 한 칸으로 줄인다. HTML 청크는 태그도 지운다.

    JSON 청크는 태그를 지우지 않는다. 조문의 `<개정 2011. 8. 10.>` 같은 원문 글자가 태그로 오해되어 사라지기 때문이다.
    그래서 JSON 청크의 plain 값은 구조 글자가 섞인 길이이며 HTML 청크의 plain 값과 같은 뜻이 아니다.
    """
    text = content
    if content_format == "html":
        text = re.sub(r"<[^>]+>", " ", text)
        # &lt; &gt; &amp;뿐 아니라 &quot;, &#x27;, &nbsp; 같은 문자 참조도 한 글자로 센다.
        text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _plain(chunk: dict) -> str:
    return plain_text(chunk["content"], chunk.get("content_format", "html"))


def _percentile(values: list[int], q: float) -> int:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def _has_deleted_marker(text: str) -> bool:
    # "삭제 <2015. 11. 11.>" 또는 "<삭제 2015.4.2>" 꼴의 삭제 표시
    return bool(re.search(r"삭제\s*<|<[^<>]*삭제", text))


def _scope(chunk: dict) -> str:
    """청크의 범위. common과 unknown은 둘 다 districts가 빈 목록이므로 scope_type으로 구별한다."""
    scope = chunk.get("scope_type")
    if scope in ("district", "common", "unknown"):
        return scope
    # scope_type이 없는 옛 파일은 구 목록이 비었으면 공통으로 본다.
    return "district" if chunk["districts"] else "common"


def detect_version(chunks: list[dict]) -> str:
    """청크들이 모두 같은 chunking_version이면 그 값을 돌려주고, 없거나 섞여 있으면 거부한다."""
    versions = {c.get("chunking_version") for c in chunks}
    if len(versions) != 1 or not next(iter(versions)):
        raise ValueError(
            f"청크의 chunking_version이 하나가 아닙니다: {sorted(map(str, versions))}"
        )
    return versions.pop()


def _is_heading(chunk: dict) -> bool:
    """장·절 제목 청크. 조문 번호가 000000인 조문 단위다(JSON 청크의 unit_type이 heading인 것과 일치한다)."""
    return (
        chunk["source_location"].startswith("조문")
        and "(조문번호 000000)" in chunk["source_location"]
    )


def detect_format(chunks: list[dict]) -> str:
    """청크들이 모두 같은 content_format이면 그 값을 돌려주고, 섞여 있으면 거부한다."""
    formats = {c.get("content_format", "html") for c in chunks}
    if len(formats) != 1:
        raise ValueError(f"청크의 content_format이 하나가 아닙니다: {sorted(formats)}")
    return formats.pop()


def summarize(chunks: list[dict]) -> dict:
    """청크 목록(prepare_data의 chunks-*.json 항목)을 한 줄 요약으로 바꾼다.

    구 열은 구마다 따로 센다. 여러 구에 적용되는 청크는 각 구 열에 모두 들어가므로
    서대문구+송파구가 청크 수보다 커질 수 있다.
    """
    if not chunks:
        raise ValueError("청크가 없습니다.")
    chunking_version = detect_version(chunks)
    fmt = detect_format(chunks)
    raw = [len(c["content"]) for c in chunks]
    plain_texts = [_plain(c) for c in chunks]
    plain = [len(t) for t in plain_texts]
    same = Counter(plain_texts)
    heading = sum(1 for c in chunks if _is_heading(c))
    article = (
        sum(1 for c in chunks if c["source_location"].startswith("조문")) - heading
    )
    table = sum(1 for c in chunks if c["source_location"].startswith("table-"))
    return {
        "chunking_version": chunking_version,
        "format": fmt,
        "chunk_count": len(chunks),
        "documents": len({c["source_document_id"] for c in chunks}),
        "서대문구": sum(1 for c in chunks if "서대문구" in c["districts"]),
        "송파구": sum(1 for c in chunks if "송파구" in c["districts"]),
        "공통": sum(1 for c in chunks if _scope(c) == "common"),
        "범위미상": sum(1 for c in chunks if _scope(c) == "unknown"),
        "article_chunks": article,
        "heading_chunks": heading,
        "table_row_chunks": table,
        "other_chunks": len(chunks) - article - heading - table,
        "conditions_empty": sum(1 for c in chunks if not c["conditions"]),
        "deleted_marker_chunks": sum(
            1 for c in chunks if _has_deleted_marker(_plain(c))
        ),
        "short_chunks": sum(1 for n in plain if n < SHORT_PLAIN_CHARS),
        # 평문이 다른 청크와 완전히 같은 청크의 수(같은 묶음의 모든 청크를 센다)
        "duplicate_plain_chunks": sum(n for n in same.values() if n > 1),
        "content_min": min(raw),
        "content_median": int(statistics.median(raw)),
        "content_p90": _percentile(raw, 0.9),
        "content_max": max(raw),
        "plain_min": min(plain),
        "plain_median": int(statistics.median(plain)),
        "plain_p90": _percentile(plain, 0.9),
        "plain_max": max(plain),
        # chunk_id는 제목·범위·구 목록·조건을 섞지 않으므로 ID가 아니라 청크의 모든 필드를 해시한다.
        "chunks_sha256": hashlib.sha256(
            json.dumps(
                sorted(chunks, key=lambda c: c["chunk_id"]),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
    }


def append_row(row: dict, csv_path: Path) -> None:
    """CSV 끝에 한 줄을 더한다. 파일이 없으면 제목 줄부터 만든다. 같은 이름(chunking_version, format)이 이미 있으면 거부한다."""
    csv_path = Path(csv_path)
    # 0바이트 파일은 새 파일로 본다(머리글을 쓴다).
    exists = csv_path.exists() and csv_path.stat().st_size > 0
    if exists:
        with open(csv_path, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames != COLUMNS:
                raise ValueError(
                    "기존 CSV의 열이 이 스크립트의 열과 다릅니다. 새 파일에 기록하세요."
                )
            for old in reader:
                if (
                    old["chunking_version"] == row["chunking_version"]
                    and old["format"] == row["format"]
                ):
                    raise ValueError(
                        f"이미 있는 기록입니다: {row['chunking_version']} / {row['format']}"
                    )
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(
        csv_path, "a", encoding="utf-8-sig" if not exists else "utf-8", newline=""
    ) as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def load_chunks(path: Path) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(data, list):
        raise ValueError("청크 파일은 목록이어야 합니다.")
    return data


def show(chunks: list[dict], needle: str, limit: int = 3) -> None:
    """source_document_id 또는 source_location에 needle이 들어 있는 청크의 평문을 보여 준다."""
    found = [
        c
        for c in chunks
        if needle in c["source_document_id"] or needle in c["source_location"]
    ]
    print(f'"{needle}" 일치 {len(found)}개 (앞 {min(limit, len(found))}개 표시)')
    for c in found[:limit]:
        text = _plain(c)
        print(
            f"--- {c['source_document_id']} | {c['source_location']} | 평문 {len(text)}자"
        )
        print(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--chunks",
        type=Path,
        required=True,
        help="chunks-html.json 또는 chunks-json.json",
    )
    parser.add_argument(
        "--csv", type=Path, help="누적할 CSV. 주지 않으면 요약만 출력한다."
    )
    parser.add_argument(
        "--show", help="이 문자열이 문서 ID나 원문 위치에 있는 청크의 평문을 보여 준다."
    )
    args = parser.parse_args(argv)

    try:
        chunks = load_chunks(args.chunks)
        if args.show:
            show(chunks, args.show)
            return 0
        row = summarize(chunks)
        for key in COLUMNS:
            print(f"{key}: {row[key]}")
        if args.csv:
            append_row(row, args.csv)
            print(f"기록했습니다: {args.csv}")
    except (ValueError, OSError, KeyError) as error:
        print(f"실패했습니다: {error}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
