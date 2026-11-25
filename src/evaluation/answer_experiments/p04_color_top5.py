import argparse
import json
import subprocess
import sys
from pathlib import Path

from src.evaluation.runner import load_evaluation_cases

INDEX = "data/processed/p04-v2-openai-small/index-json.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    cases = load_evaluation_cases("eval/dev.json")
    case = next((c for c in cases if c.case_id == "p04-colors-trick"), None)

    if case is None or not case.district or not case.allowed_chunk_ids:
        raise SystemExit(
            "색상표 문항의 case_id, district, allowed_chunk_ids를 확인하세요."
        )

    subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.search_index",
            "--index",
            INDEX,
            "--district",
            case.district,
            "--question",
            case.question,
            "--top-k",
            "5",
            "--output",
            str(args.output),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )

    record = json.loads(args.output.read_text(encoding="utf-8"))
    [index_result] = record["results"]
    first_rank = None
    for rank, match in enumerate(index_result["matches"], start=1):
        chunk = match["chunk"]
        print(f"{rank}위  {chunk['chunk_id']}  {chunk['source_location']}")
        if first_rank is None and chunk["chunk_id"] in case.allowed_chunk_ids:
            first_rank = rank

    if first_rank is None:
        print("Hit@5 = 0 · 정답 청크가 상위 5개에 없습니다.")
    else:
        print(f"Hit@5 = 1 · 정답 청크는 {first_rank}위입니다.")


if __name__ == "__main__":
    main()
