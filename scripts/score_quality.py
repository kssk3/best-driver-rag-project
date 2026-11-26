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


# 문서 ID의 앞부분으로 청크가 실제로 속한 자치구를 정한다. candidates.csv의 district 열은
# 질문의 지역이라 다른 자치구 청크를 인용해도 같은 값이 들어간다.
AUTHORITY = {"seodaemun": "서대문구", "songpa": "송파구"}


def district_of_document(document_id: str) -> str:
    return AUTHORITY.get(document_id.split("-")[0], "자치구 미상")


def cited_texts_by_run(candidates: list[dict[str, str]]) -> dict[str, list[str]]:
    """실행별로 인용된 근거 본문. 자치구와 문서 위치는 청크 본문이 아니라 메타데이터에 있어 머리말로 붙인다."""
    cited: dict[str, list[str]] = {}
    for row in candidates:
        if row.get("citation_position"):
            district = district_of_document(row.get("document_id", ""))
            head = f"[{district} | {row.get('title', '')} | {row.get('source_location', '')}]"
            cited.setdefault(row["run_id"], []).append(f"{head}\n{row['text']}")
    return cited


def run_config(run: dict[str, str]) -> str:
    """구성 이름. 실행 기록 없이 실패한 행은 variant가 비어 있어 configuration으로 구별한다."""
    return run.get("variant") or run.get("configuration") or ""


def fill_failed_rows(runs: list[dict[str, str]]) -> list[dict[str, str]]:
    """실행 기록 없이 실패한 행의 구성 이름과 리라이트 여부를 같은 구성의 다른 행에서 채운다."""
    rewrite: dict[str, set[str]] = {}
    for r in runs:
        if r.get("rewrite_enabled"):
            rewrite.setdefault(run_config(r), set()).add(r["rewrite_enabled"])
    filled = []
    for r in runs:
        config = run_config(r)
        known = rewrite.get(config, set())
        value = r.get("rewrite_enabled") or (
            next(iter(known)) if len(known) == 1 else ""
        )
        filled.append({**r, "variant": config, "rewrite_enabled": value})
    return filled


def check_inputs(
    runs: list[dict[str, str]],
    candidates: list[dict[str, str]],
    questions: dict[str, str],
    grading: dict[str, dict],
    allow_subset: bool = False,
) -> list[str]:
    """모델을 부르기 전에 실행·후보·문항·채점 자료가 같은 묶음인지 대조한다. 문제 목록을 돌려준다."""
    problems = []
    run_ids = {r["run_id"] for r in runs}
    for name, rows in (("runs", runs), ("candidates", candidates)):
        datasets = {r.get("dataset_id", "") for r in rows}
        if len(datasets) > 1:
            problems.append(f"{name}에 dataset_id가 여러 개 섞여 있습니다.")
    if (
        runs
        and candidates
        and {r.get("dataset_id") for r in runs}
        != {r.get("dataset_id") for r in candidates}
    ):
        problems.append("runs와 candidates의 dataset_id가 다릅니다(다른 평가 묶음).")
    orphans = {r["run_id"] for r in candidates} - run_ids
    if orphans:
        problems.append(f"candidates에 runs에 없는 실행 {len(orphans)}개가 있습니다.")
    rows_by_run: dict[str, list[dict[str, str]]] = {}
    for row in candidates:
        rows_by_run.setdefault(row["run_id"], []).append(row)
    for run in runs:
        rows = rows_by_run.get(run["run_id"], [])
        count = run.get("candidate_count", "")
        if count != "" and int(count) != len(rows):
            problems.append(
                f"{run['case_id']} {run.get('variant', '')}: 실행 기록의 후보 {count}개와 candidates의 후보 행 {len(rows)}개가 다릅니다(파일이 불완전)."
            )
        # 값이 없는 예전 기록("")과 명시적인 빈 배열("[]")을 구분한다. 기록됐으면 빈 배열도 대조한다.
        raw_ranks = run.get("citation_ranks_json") or ""
        if raw_ranks != "":
            ranks = sorted(json.loads(raw_ranks))
            cited = sorted(int(r["rank"]) for r in rows if r.get("citation_position"))
            if cited != ranks:
                problems.append(
                    f"{run['case_id']} {run.get('variant', '')}: 인용 순위 {ranks}가 candidates의 인용 행 {cited}과 다릅니다."
                )
    case_ids = {r["case_id"] for r in runs}
    for case_id in sorted(case_ids - set(questions)):
        problems.append(f"{case_id}: 문항 파일(--cases)에 없습니다.")
    for case_id in sorted(case_ids - set(grading)):
        problems.append(
            f"{case_id}: 채점 자료(--grading)에 없습니다. 점수 없이 건너뛰지 않습니다."
        )
    seen: dict[tuple[str, str, str], int] = {}
    for r in runs:
        key = (r["case_id"], run_config(r), str(r.get("rewrite_enabled", "")))
        seen[key] = seen.get(key, 0) + 1
    for key, count in seen.items():
        if count > 1:
            problems.append(f"{key}가 {count}번 있습니다(중복).")
    if not allow_subset:
        expected = set(grading) & set(questions)
        for config in {(k[1], k[2]) for k in seen}:
            have = {k[0] for k in seen if (k[1], k[2]) == config}
            missing = expected - have
            if missing:
                problems.append(
                    f"구성 {config}에 채점 자료의 문항 {len(missing)}개가 없습니다. 일부만 채점하려면 --allow-subset을 쓰세요."
                )
    return problems


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--grading", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model", default="gpt-6-luna")
    parser.add_argument(
        "--allow-subset",
        action="store_true",
        help="구성마다 채점 자료의 일부 문항만 실행한 경우(재현용 일부 문항)를 허용한다.",
    )
    args = parser.parse_args(argv)
    if args.output_dir.exists():
        parser.error("기존 결과를 덮어쓸 수 없습니다. 새 --output-dir를 지정하세요.")

    grading = load_grading(args.grading)
    questions = {c.case_id: c.question for c in load_evaluation_cases(args.cases)}
    with args.runs.open(encoding="utf-8", newline="") as file:
        runs = fill_failed_rows(list(csv.DictReader(file)))
    with args.candidates.open(encoding="utf-8", newline="") as file:
        candidates = list(csv.DictReader(file))
    problems = check_inputs(runs, candidates, questions, grading, args.allow_subset)
    if problems:
        parser.error(
            "입력이 맞지 않아 중단합니다(모델 호출 전):\n- " + "\n- ".join(problems)
        )
    cited = cited_texts_by_run(candidates)

    judge = make_judge(args.model)
    rows = []
    for run in runs:
        row = score_run(
            run,
            grading[run["case_id"]],
            questions[run["case_id"]],
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
