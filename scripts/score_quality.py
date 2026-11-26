"""평가 실행(runs.csv)에 정답 충족·근거 적합·근거 없음 대응을 채점해 quality.csv로 저장한다.

사용: uv run --locked --env-file .env python -m scripts.score_quality \\
  --runs results/local/<실행>/runs.csv --candidates results/local/<실행>/candidates.csv \\
  --grading eval/test-grading.json --cases eval/test.json --output-dir results/local/<새 폴더>
`--grading`은 여러 번 줄 수 있다(예: eval/dev-scoring-notes.json). 판정 모델 호출이 발생한다(실행당 최대 3회).
"""

import argparse
import csv
import json
from pathlib import Path

from src.evaluation.answer_quality import KEYS, Judge, score_run, summarize
from src.evaluation.runner import load_evaluation_cases

COLUMNS = [
    "run_id",
    "case_id",
    "variant",
    "rewrite_enabled",
    "status",
    *KEYS,
    *[f"{key}_reason" for key in KEYS],
    "judge_model",
]


def load_grading(paths: list[Path]) -> dict[str, dict]:
    """채점 자료를 하나로 합친다. 형식은 {"grading": {...}}(최종셋)과 {문항 ID: 항목}(개발셋 메모) 둘 다 읽는다."""
    merged: dict[str, dict] = {}
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        merged.update(data["grading"] if "grading" in data else data)
    return merged


def make_judge(model: str) -> Judge:
    from src.infrastructure.chat_models import (
        ChatModelSettings,
        create_chat_model,
        invoke_chat,
    )

    chat = create_chat_model(ChatModelSettings(model=model)).bind(
        response_format={"type": "json_object"}
    )
    return lambda prompt: invoke_chat(chat, prompt)


def cited_texts_by_run(candidates: list[dict[str, str]]) -> dict[str, list[str]]:
    """실행별로 인용된 근거 본문. 자치구와 문서 위치는 청크 본문이 아니라 메타데이터에 있어 머리말로 붙인다."""
    cited: dict[str, list[str]] = {}
    for row in candidates:
        if row.get("citation_position"):
            head = f"[{row.get('district', '')} | {row.get('title', '')} | {row.get('source_location', '')}]"
            cited.setdefault(row["run_id"], []).append(f"{head}\n{row['text']}")
    return cited


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--grading", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model", default="gpt-6-luna")
    args = parser.parse_args(argv)
    if args.output_dir.exists():
        parser.error("기존 결과를 덮어쓸 수 없습니다. 새 --output-dir를 지정하세요.")

    grading = load_grading(args.grading)
    questions = {c.case_id: c.question for c in load_evaluation_cases(args.cases)}
    with args.runs.open(encoding="utf-8", newline="") as file:
        runs = list(csv.DictReader(file))
    with args.candidates.open(encoding="utf-8", newline="") as file:
        cited = cited_texts_by_run(list(csv.DictReader(file)))

    judge = make_judge(args.model)
    rows = []
    for run in runs:
        item = grading.get(run["case_id"])
        if item is None:
            continue  # 채점 자료가 없는 문항은 건너뛴다.
        row = score_run(
            run,
            item,
            questions.get(run["case_id"], ""),
            cited.get(run["run_id"], []),
            judge,
        )
        row["judge_model"] = args.model
        rows.append(row)

    args.output_dir.mkdir(parents=True)
    with (args.output_dir / "quality.csv").open(
        "w", encoding="utf-8", newline=""
    ) as file:
        writer = csv.DictWriter(file, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"채점 {len(rows)}건: {args.output_dir / 'quality.csv'}")
    for item in summarize(rows):
        print(item)


if __name__ == "__main__":
    main()
