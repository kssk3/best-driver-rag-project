"""실행 모드로 Streamlit 화면을 띄운다. 기본 팀 색인이 없으면 먼저 만든다.

사용: uv run --locked --env-file .env python -m scripts.run_chat [--settings 설정 파일]
기본 팀 색인(`TEAM_INDEX`)이 없을 때만 OpenAI 임베딩을 호출한다(약 543청크).
다른 설정의 색인은 만들지 않고, 기본 팀 색인은 청킹 기준선 지문과 맞는지 확인한다.
"""

import argparse
import csv
import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from src.infrastructure.stores import load_index
from src.ingestion.chunk_fingerprint import chunks_fingerprint

ROOT = Path(__file__).resolve().parent.parent
TEAM_INDEX = ROOT / "data/processed/ordinance-v2-openai-small/index-json.json"
BASELINE = ROOT / "results/chunking/chunk_stats.csv"
BUNDLE = "data/handoff/jungeun/ordinance-handoff-2026-11-24"
EMBEDDING_MODEL = "text-embedding-3-small"


def baseline_mismatch(index_path: Path) -> str | None:
    """색인의 청크가 청킹 기준선과 다르면 이유를, 같으면 None을 돌려준다."""
    index = load_index(index_path)
    version = index.metadata.chunking_version
    actual = chunks_fingerprint(entry.chunk for entry in index.entries)
    with BASELINE.open(encoding="utf-8-sig", newline="") as file:
        expected = {
            row["chunks_sha256"]
            for row in csv.DictReader(file)
            if row["format"] == "json" and row["chunking_version"] == version
        }
    if actual in expected:
        return None
    return (
        f"색인이 청킹 기준선과 다릅니다(chunking_version={version}): {index_path}\n"
        "옛 색인일 수 있습니다. 폴더 이름을 바꾸거나 지운 뒤 다시 실행하면 새로 만듭니다."
    )


def build_team_index(index: Path) -> None:
    """새 폴더에 만든 뒤 옮긴다. 이전에 실패해 남은 폴더는 지우지 않고 이름만 바꿔 둔다."""
    out = index.parent
    building = out.with_name(f"{out.name}.building-{uuid4().hex[:8]}")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.prepare_data",
            "--bundle",
            BUNDLE,
            "--version",
            "v1",
            "--output-dir",
            str(building),
            "--openai-model",
            EMBEDDING_MODEL,
        ],
        cwd=ROOT,
        check=True,
    )
    if not (building / index.name).exists():
        sys.exit(f"색인 생성이 끝났지만 {index.name}이 없습니다: {building}")
    # 기준선과 다른 새 색인은 기본 경로로 옮기지 않는다(확인용으로 임시 폴더에 남긴다).
    if problem := baseline_mismatch(building / index.name):
        sys.exit(
            f"새로 만든 색인을 사용하지 않습니다.\n{problem}\n확인용 폴더: {building}"
        )
    if out.exists():
        out.rename(out.with_name(f"{out.name}.incomplete-{uuid4().hex[:8]}"))
    building.rename(out)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", default="configs/team-c-rewrite-chat.json")
    args = parser.parse_args(argv)

    settings = json.loads((ROOT / args.settings).read_text(encoding="utf-8"))
    index = (ROOT / settings["index_path"]).resolve()
    is_team_index = index == TEAM_INDEX.resolve()
    if not index.exists():
        if not is_team_index:
            sys.exit(f"색인 파일이 없습니다: {index}\n직접 준비한 뒤 다시 실행하세요.")
        if not os.environ.get("OPENAI_API_KEY"):
            sys.exit(
                f"색인 파일이 없고 OPENAI_API_KEY도 없습니다: {index}\n"
                "`uv run --locked --env-file .env python -m scripts.run_chat`로 실행하세요."
            )
        print(f"색인이 없어 새로 만듭니다(임베딩 호출 발생): {index}", flush=True)
        build_team_index(index)
    elif is_team_index and (problem := baseline_mismatch(index)):
        sys.exit(problem)
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", "app.py"],
        cwd=ROOT,
        env={**os.environ, "RAG_CHAT_SETTINGS": args.settings},
        check=True,
    )


if __name__ == "__main__":
    main()
