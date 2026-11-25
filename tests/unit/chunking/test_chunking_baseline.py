"""청킹 결과가 기준선(results/chunking/chunk_stats.csv)과 같은지 확인한다.

정은님 인계 번들을 현재 청킹 코드로 청킹한 결과를 `scripts.chunk_stats`로 요약해 CSV의
같은 `chunking_version` 줄과 비교한다. 청킹 결과가 달라지는 변경(코드뿐 아니라 번들 변경 포함)이
버전 이름과 기준선을 갱신하지 않고 들어오는 것을 막으려는 점검이다.
"""

import csv
from pathlib import Path

import pytest

from scripts.chunk_stats import COLUMNS, summarize
from src.ingestion.preprocessed_bundle import load_preprocessed_bundle
from src.ingestion.preprocessed_chunking import chunk_preprocessed_documents

ROOT = Path(__file__).resolve().parents[3]
BUNDLE = ROOT / "data/handoff/jungeun/ordinance-handoff-2026-11-24"
BASELINE = ROOT / "results/chunking/chunk_stats.csv"

HOW_TO_FIX = (
    "청킹 결과가 기준선과 다릅니다. 청킹 결과가 달라지는 변경이면 다음을 함께 하세요.\n"
    "1) src/ingestion/preprocessed_chunking.py의 chunking_version 기본값을 올립니다.\n"
    "2) 아래 명령을 HTML·JSON 두 형식에 각각 실행해 results/chunking/chunk_stats.csv에 새 버전 줄을 추가합니다"
    "(옛 버전 줄은 지우지 않습니다).\n"
    "   uv run --locked python -m scripts.prepare_data --bundle {bundle} --version v1 --output-dir results/local/<새 폴더>\n"
    "   uv run --locked python -m scripts.chunk_stats --chunks results/local/<새 폴더>/chunks-html.json "
    "--csv results/chunking/chunk_stats.csv\n"
    "3) chunk_id가 모두 바뀌므로 근거 매핑(tests/fixtures/interface/screen_check_set/chunk_id_map.csv, "
    "eval/dev.json의 allowed_chunk_ids 등)과 색인을 갱신하고 영향받는 팀원에게 알립니다.\n"
    "버전을 올리지 않고 같은 이름의 줄을 고치면 이전 결과와 비교할 수 없게 되므로 하지 마세요."
)


def _current_chunks() -> dict[str, list[dict]]:
    """scripts.prepare_data와 같은 순서(색인 대상 문서만, 형식별)로 청킹한다."""
    prepared = load_preprocessed_bundle(BUNDLE, project_root=ROOT, version="v1")
    eligible = {
        s["document_id"] for s in prepared.report["sources"] if s["index_eligible"]
    }
    selected = [d for d in prepared.documents if d.document_id in eligible]
    return {
        fmt: [
            c.model_dump(mode="json")
            for c in chunk_preprocessed_documents(
                [d for d in selected if d.content_format == fmt]
            )
        ]
        for fmt in ("html", "json")
    }


def _baseline_rows() -> list[dict]:
    with open(BASELINE, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def test_baseline_csv_has_current_columns() -> None:
    with open(BASELINE, encoding="utf-8-sig", newline="") as f:
        assert csv.DictReader(f).fieldnames == COLUMNS


@pytest.mark.parametrize("fmt", ["html", "json"])
def test_current_chunking_matches_the_baseline_row_of_its_version(fmt: str) -> None:
    row = summarize(_current_chunks()[fmt])
    matches = [
        r
        for r in _baseline_rows()
        if r["chunking_version"] == row["chunking_version"] and r["format"] == fmt
    ]
    assert len(matches) == 1, (
        f"기준선 CSV에 {row['chunking_version']} / {fmt} 줄이 {len(matches)}개 있습니다(1개여야 합니다).\n"
        + HOW_TO_FIX.format(bundle=BUNDLE.relative_to(ROOT).as_posix())
    )
    differences = {
        key: (matches[0][key], str(row[key]))
        for key in COLUMNS
        if matches[0][key] != str(row[key])
    }
    assert not differences, (
        f"{row['chunking_version']} / {fmt}의 청킹 결과가 기준선과 다릅니다(열: (기준선, 현재)): {differences}\n"
        + HOW_TO_FIX.format(bundle=BUNDLE.relative_to(ROOT).as_posix())
    )
