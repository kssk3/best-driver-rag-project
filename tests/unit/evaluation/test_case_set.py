"""최종 평가 문항 점검 테스트. 가상 문항만 사용하며 실제 평가 문항이 아니다."""

import copy
import json
from pathlib import Path

import pytest

from src.contracts import EvaluationCase
from src.evaluation.case_set import (
    check_final_set,
    check_no_overlap,
    load_grading,
    main,
)


def make_cases() -> list[EvaluationCase]:
    cases = []
    for number in range(1, 21):
        refusal = number >= 18
        cases.append(
            EvaluationCase(
                case_id=f"fx-{number:02d}",
                question=f"[가상] 질문 {number}",
                district="서대문구",
                expected_status="insufficient_evidence" if refusal else "answered",
            )
        )
    return cases


def make_grading() -> dict[str, dict]:
    grading = {}
    for number in range(1, 21):
        case_id = f"fx-{number:02d}"
        if number >= 18:
            grading[case_id] = {
                "category": "no_evidence",
                "absence_reason": "[가상] 자료에 없음",
            }
        else:
            grading[case_id] = {
                "category": "direct" if number <= 10 else "variation",
                "required_facts": ["[가상] 필수 사실"],
                "evidence": [
                    {"document_id": "fx-doc", "source_location": "가상 표 > 행"}
                ],
                "reason": "[가상] 판정 이유",
            }
    return grading


def test_valid_set_has_no_problems() -> None:
    assert check_final_set(make_cases(), make_grading()) == []


def test_reference_answer_may_be_in_both_files_when_same() -> None:
    cases = make_cases()
    grading = make_grading()
    cases[0] = cases[0].model_copy(update={"reference_answer": "[가상] 모범 정답"})
    grading["fx-01"]["reference_answer"] = "[가상] 모범 정답"
    assert check_final_set(cases, grading) == []


def test_reference_answer_in_both_files_must_match() -> None:
    cases = make_cases()
    grading = make_grading()
    cases[0] = cases[0].model_copy(update={"reference_answer": "[가상] 모범 정답"})
    grading["fx-01"]["reference_answer"] = "[가상] 다른 정답"
    problems = check_final_set(cases, grading)
    assert any("fx-01" in p and "reference_answer" in p for p in problems)


def test_reference_answer_in_one_file_only_is_fine() -> None:
    cases = make_cases()
    grading = make_grading()
    grading["fx-01"]["reference_answer"] = "[가상] 채점표에만 있는 정답"
    assert check_final_set(cases, grading) == []


def test_wrong_total_is_reported() -> None:
    problems = check_final_set(make_cases()[:19], make_grading())
    assert any("20개여야 합니다. 지금은 19개 입니다" in p for p in problems)


def test_case_without_grading_is_reported() -> None:
    grading = make_grading()
    del grading["fx-05"]
    problems = check_final_set(make_cases(), grading)
    assert "fx-05: 채점표가 없습니다." in problems


def test_grading_without_case_is_reported() -> None:
    grading = make_grading()
    grading["fx-99"] = copy.deepcopy(grading["fx-01"])
    assert "fx-99: 채점표만 있고 문항이 없습니다." in check_final_set(
        make_cases(), grading
    )


def test_unknown_category_is_reported() -> None:
    grading = make_grading()
    grading["fx-01"]["category"] = "easy"
    problems = check_final_set(make_cases(), grading)
    assert any(p.startswith("fx-01: category는") for p in problems)


def test_category_counts_are_checked() -> None:
    grading = make_grading()
    grading["fx-10"]["category"] = "variation"
    problems = check_final_set(make_cases(), grading)
    assert "direct 문항은 10개여야 합니다. 지금은 9개 입니다." in problems
    assert "variation 문항은 7개여야 합니다. 지금은 8개 입니다." in problems


@pytest.mark.parametrize(
    "field, expected",
    [
        ("required_facts", "required_facts"),
        ("evidence", "evidence"),
        ("reason", "reason"),
    ],
)
def test_answerable_case_needs_facts_evidence_and_reason(
    field: str, expected: str
) -> None:
    grading = make_grading()
    del grading["fx-01"][field]
    problems = check_final_set(make_cases(), grading)
    assert any(p.startswith("fx-01:") and expected in p for p in problems)


def test_evidence_needs_location() -> None:
    grading = make_grading()
    grading["fx-02"]["evidence"] = [{"document_id": "fx-doc", "source_location": " "}]
    problems = check_final_set(make_cases(), grading)
    assert any(p.startswith("fx-02:") and "source_location" in p for p in problems)


def test_no_evidence_case_needs_absence_reason() -> None:
    grading = make_grading()
    grading["fx-18"]["absence_reason"] = ""
    problems = check_final_set(make_cases(), grading)
    assert any(p.startswith("fx-18:") and "absence_reason" in p for p in problems)


def test_expected_status_must_match_category() -> None:
    cases = make_cases()
    cases[0] = cases[0].model_copy(update={"expected_status": "insufficient_evidence"})
    cases[17] = cases[17].model_copy(update={"expected_status": "answered"})
    problems = check_final_set(cases, make_grading())
    assert any(p.startswith("fx-01:") and "answered" in p for p in problems)
    assert any(
        p.startswith("fx-18:") and "insufficient_evidence" in p for p in problems
    )


def test_overlap_with_dev_set_is_reported() -> None:
    final = make_cases()
    dev = [
        EvaluationCase(
            case_id="dev-01", question="[가상]  질문 3"
        ),  # 공백만 다른 같은 질문
        EvaluationCase(case_id="fx-07", question="[가상] 전혀 다른 질문"),  # 같은 ID
    ]
    problems = check_no_overlap(final, dev)
    assert "fx-03: 개발 문항과 질문이 같습니다." in problems
    assert "fx-07: 개발 문항과 case_id가 같습니다." in problems


def test_no_overlap_when_sets_are_separate() -> None:
    dev = [EvaluationCase(case_id="dev-01", question="[가상] 개발 질문")]
    assert check_no_overlap(make_cases(), dev) == []


def test_load_grading_requires_grading_object(tmp_path: Path) -> None:
    path = tmp_path / "grading.json"
    path.write_text(json.dumps({"items": {}}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_grading(path)


def write_files(tmp_path: Path, grading: dict) -> tuple[Path, Path]:
    cases_path = tmp_path / "test.json"
    grading_path = tmp_path / "grading.json"
    cases_path.write_text(
        json.dumps(
            [c.model_dump(mode="json") for c in make_cases()], ensure_ascii=False
        ),
        encoding="utf-8",
    )
    grading_path.write_text(
        json.dumps({"grading": grading}, ensure_ascii=False), encoding="utf-8"
    )
    return cases_path, grading_path


def test_main_returns_zero_for_valid_files(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    cases_path, grading_path = write_files(tmp_path, make_grading())
    assert main(["--cases", str(cases_path), "--grading", str(grading_path)]) == 0
    assert "문제 없음" in capsys.readouterr().out


def test_main_returns_one_and_lists_problems(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    grading = make_grading()
    del grading["fx-05"]
    cases_path, grading_path = write_files(tmp_path, grading)
    assert main(["--cases", str(cases_path), "--grading", str(grading_path)]) == 1
    assert "fx-05: 채점표가 없습니다." in capsys.readouterr().out


def test_main_returns_two_when_file_is_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    code = main(
        [
            "--cases",
            str(tmp_path / "none.json"),
            "--grading",
            str(tmp_path / "none2.json"),
        ]
    )
    assert code == 2
    assert "읽지 못했습니다" in capsys.readouterr().out


@pytest.mark.parametrize(
    "grading",
    [{"fx-01": []}, {"fx-01": {"category": 1}}, {"fx-01": {}}],
)
def test_load_grading_rejects_malformed_entries(tmp_path: Path, grading: dict) -> None:
    path = tmp_path / "grading.json"
    path.write_text(json.dumps({"grading": grading}), encoding="utf-8")
    with pytest.raises(ValueError, match="fx-01"):
        load_grading(path)


def test_main_returns_two_for_malformed_grading_entry(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    cases_path, grading_path = write_files(tmp_path, {"fx-01": []})
    assert main(["--cases", str(cases_path), "--grading", str(grading_path)]) == 2
    assert "fx-01" in capsys.readouterr().out


def test_load_grading_rejects_duplicate_case_id(tmp_path: Path) -> None:
    path = tmp_path / "grading.json"
    path.write_text(
        '{"grading": {"fx-01": {"category": "direct"}, "fx-01": {"category": "direct"}}}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="중복"):
        load_grading(path)


def test_missing_expected_status_is_reported() -> None:
    cases = make_cases()
    cases[0] = cases[0].model_copy(update={"expected_status": None})
    cases[19] = cases[19].model_copy(update={"expected_status": None})
    problems = check_final_set(cases, make_grading())
    assert any("expected_status" in p and "fx-01" in p for p in problems)
    assert any("expected_status" in p and "fx-20" in p for p in problems)


@pytest.mark.parametrize("value", ["", "  ", [], {"a": 1}])
def test_grading_only_reference_answer_must_be_nonblank_text(value: object) -> None:
    grading = make_grading()
    grading["fx-01"]["reference_answer"] = value
    problems = check_final_set(make_cases(), grading)
    assert any("fx-01" in p and "reference_answer" in p for p in problems)


@pytest.mark.parametrize("value", ["", "   "])
def test_blank_case_side_reference_answer_is_reported(value: str) -> None:
    cases = make_cases()
    cases[0] = cases[0].model_copy(update={"reference_answer": value})
    problems = check_final_set(cases, make_grading())
    assert any("fx-01" in p and "reference_answer" in p for p in problems)
