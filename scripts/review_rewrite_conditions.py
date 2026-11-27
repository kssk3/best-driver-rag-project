"""모델·검색 호출 없이 두 리라이트 경로의 조건 보존 후보를 CSV로 기록한다."""

import argparse
import csv
import json
from pathlib import Path

from src.query.rewrite import expected_prompt_query
from src.rewrite_dictionary.runtime import make_question_rewriter

DEFAULT_CASES = Path("docs/jungeun/rewrite_condition_cases.json")
DEFAULT_OUTPUT = Path("docs/jungeun/rewrite_condition_review.csv")


def check_conditions(question: str, rewritten: str, fragments: list[str]) -> dict:
    """문자열 보존만 검사한다. 의미·출처의 적합성은 사람이 판단한다."""
    missing = [text for text in fragments if text not in rewritten]
    body = " ".join(question.split())
    return {
        "missing_fragments": " | ".join(missing),
        "body_preserved": str(rewritten.startswith(body)).lower(),
        "automatic_status": "조건 누락 후보" if missing else "문자열 보존",
    }


def review_rows(cases: list[dict]) -> list[dict]:
    catalog = make_question_rewriter()
    rows = []
    for case in cases:
        for route, rewrite in (
            ("catalog-rules", catalog),
            ("prompt-rule-expected", expected_prompt_query),
        ):
            rewritten = rewrite(case["question"])
            rows.append(
                {
                    **case,
                    "required_fragments": " | ".join(case["required_fragments"]),
                    "route": route,
                    "rewritten_question": rewritten,
                    **check_conditions(
                        case["question"], rewritten, case["required_fragments"]
                    ),
                }
            )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    # 기존 사람 검수 기록을 덮어쓰지 않는다.
    if args.output.exists():
        parser.error("검수표가 이미 있습니다. 새 --output 경로를 지정하세요.")
    rows = review_rows(json.loads(args.cases.read_text(encoding="utf-8")))
    with args.output.open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"{args.output}: {len(rows)}행, 사람 검수는 별도")


if __name__ == "__main__":
    main()
