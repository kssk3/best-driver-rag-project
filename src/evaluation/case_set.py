"""최종 평가 문항 관리: 문항 구성과 채점 자료를 점검한다.

최종 20문항은 문항 파일(EvaluationCase 목록)과 채점 자료(필수 사실, 원문 위치, 판정 이유)로 나눠 둔다.
채점 자료는 채점에만 쓰며 검색, 질문 다듬기, 생성 입력에 넘기지 않는다.
이 모듈은 두 파일이 발제의 구성(직접 검색 10, 표현·조건 7, 근거 없음 3)과 맞는지 확인할 뿐이다.
"""

import argparse
import json
from pathlib import Path

from src.contracts import EvaluationCase
from src.evaluation.runner import (
    EvaluationCaseError,
    _unique_keys,
    load_evaluation_cases,
)

# 최종 20문항 = 직접 검색 10 + 표현 변형·조건 구분 7 + 근거 없음 3
EXPECTED_COUNTS = {"direct": 10, "variation": 7, "no_evidence": 3}
ANSWERABLE = ("direct", "variation")


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


# 채점표 읽기
def load_grading(path: Path) -> dict[str, dict]:

    data = json.loads(
        Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=_unique_keys
    )
    grading = data.get("grading") if isinstance(data, dict) else None

    if not isinstance(grading, dict):
        raise ValueError(
            '채점 파일은 {"grading": {문항 ID: 채점 항목}} 형태여야 합니다.'
        )

    for case_id, item in grading.items():
        if not isinstance(item, dict):
            raise ValueError(f"{case_id}: 채점 항목은 객체여야 합니다.")
        if not isinstance(item.get("category"), str):
            raise ValueError(f"{case_id}: category는 문자열이어야 합니다.")

    return grading


def _check_item(case: EvaluationCase, item: dict, category: str) -> list[str]:

    problems = []
    who = case.case_id

    if category in ANSWERABLE:
        facts = item.get("required_facts")
        if not (isinstance(facts, list) and facts and all(_text(f) for f in facts)):
            problems.append(f"{who}: required_facts(필수 사실)가 비어 있습니다.")

        evidence = item.get("evidence")
        if not (
            isinstance(evidence, list)
            and evidence
            and all(
                isinstance(e, dict)
                and _text(e.get("document_id"))
                and _text(e.get("source_location"))
                for e in evidence
            )
        ):
            problems.append(
                f"{who}: evidence는 document_id와 source_location이 모두 있는 항목이 1개 이상 필요합니다."
            )

        if not _text(item.get("reason")):
            problems.append(f"{who}: reason(판정 이유)이 비어 있습니다.")
        if case.expected_status != "answered":
            problems.append(
                f"{who}: 답변 가능 문항의 expected_status는 answered여야 합니다."
            )

    else:
        if not _text(item.get("absence_reason")):
            problems.append(
                f"{who}: absence_reason(근거가 없다고 판정한 이유)이 비어 있습니다."
            )
        if case.expected_status != "insufficient_evidence":
            problems.append(
                f"{who}: 근거 없음 문항의 expected_status는 insufficient_evidence여야 합니다."
            )

    return problems


# 문항과 채점표가 서로 맞는지 점검
def check_final_set(cases: list[EvaluationCase], grading: dict[str, dict]) -> list[str]:

    problems = []
    total = sum(EXPECTED_COUNTS.values())

    if len(cases) != total:
        problems.append(
            f"최종 문항은 {total}개여야 합니다. 지금은 {len(cases)}개 입니다."
        )

    case_ids = {c.case_id for c in cases}
    for case_id in sorted(case_ids - set(grading)):
        problems.append(f"{case_id}: 채점표가 없습니다.")
    for case_id in sorted(set(grading) - case_ids):
        problems.append(f"{case_id}: 채점표만 있고 문항이 없습니다.")

    counts = {name: 0 for name in EXPECTED_COUNTS}
    for case in cases:
        item = grading.get(case.case_id)
        if item is None:
            continue
        category = item.get("category")
        if category not in EXPECTED_COUNTS:
            problems.append(
                f"{case.case_id}: category는 {sorted(EXPECTED_COUNTS)} 중 하나여야 합니다. 지금은 {category!r}"
            )
            continue
        counts[category] += 1
        problems.extend(_check_item(case, item, category))

        # 모범 정답은 문항과 채점표 양쪽에 둘 수 있다. 있는 쪽은 각각 비어 있으면 안 되고, 둘 다 있으면 같아야 한다.
        if case.reference_answer is not None and not _text(case.reference_answer):
            problems.append(
                f"{case.case_id}: 문항의 reference_answer(모범 정답)는 비어 있지 않은 문자열이어야 합니다."
            )
        if "reference_answer" in item and not _text(item["reference_answer"]):
            problems.append(
                f"{case.case_id}: 채점표의 reference_answer(모범 정답)는 비어 있지 않은 문자열이어야 합니다."
            )
        elif "reference_answer" in item and case.reference_answer is not None:
            if item["reference_answer"] != case.reference_answer:
                problems.append(
                    f"{case.case_id}: 문항과 채점표의 reference_answer(모범 정답)가 다릅니다."
                )

    for name, expected in EXPECTED_COUNTS.items():
        if counts[name] != expected:
            problems.append(
                f"{name} 문항은 {expected}개여야 합니다. 지금은 {counts[name]}개 입니다."
            )

    return problems


# 최종 문항이 개발 문항과 겹치면 알림
def check_no_overlap(
    final_cases: list[EvaluationCase], dev_cases: list[EvaluationCase]
) -> list[str]:

    problems = []
    dev_ids = {c.case_id for c in dev_cases}
    dev_questions = {" ".join(c.question.split()) for c in dev_cases}

    for case in final_cases:
        if case.case_id in dev_ids:
            problems.append(f"{case.case_id}: 개발 문항과 case_id가 같습니다.")
        if " ".join(case.question.split()) in dev_questions:
            problems.append(f"{case.case_id}: 개발 문항과 질문이 같습니다.")

    return problems


def main(argv: list[str] | None = None) -> int:

    parser = argparse.ArgumentParser(
        description="최종 평가 문항과 채점표를 점검한다. 평가를 실행하지 않는다."
    )
    parser.add_argument(
        "--cases",
        type=Path,
        required=True,
        help="문항 파일 (e.g. tests/fixtures/interface/screen_check_set/cases.json)",
    )
    parser.add_argument("--grading", type=Path, required=True, help="채점 자료 파일")
    parser.add_argument(
        "--dev", type=Path, help="개발 문항 파일. 주면 겹치는 문항도 찾는다."
    )
    args = parser.parse_args(argv)

    try:
        cases = load_evaluation_cases(args.cases)
        problems = check_final_set(cases, load_grading(args.grading))
        if args.dev:
            problems.extend(check_no_overlap(cases, load_evaluation_cases(args.dev)))

    except (EvaluationCaseError, ValueError, OSError) as error:
        print(f"파일을 읽지 못했습니다.: {error}")
        return 2

    for problem in problems:
        print(f"- {problem}")
    print(f"문제 {len(problems)}건" if problems else "문제 없음")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
