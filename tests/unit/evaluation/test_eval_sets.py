"""eval/의 개발·최종 문항 파일이 발제 구성(개발 10, 최종 20)과 서로 겹치지 않는지 확인한다. 모델·색인을 쓰지 않는다."""

from pathlib import Path

from src.evaluation.case_set import check_final_set, check_no_overlap, load_grading
from src.evaluation.runner import load_evaluation_cases

EVAL = Path(__file__).parent.parent.parent.parent / "eval"


def load():
    dev = load_evaluation_cases(EVAL / "dev.json")
    test = load_evaluation_cases(EVAL / "test.json")
    return dev, test


def test_dev_set_has_eight_answerable_and_two_without_evidence() -> None:
    dev, _ = load()
    statuses = [case.expected_status for case in dev]
    assert len(dev) == 10
    assert statuses.count("answered") == 8
    assert statuses.count("insufficient_evidence") == 2
    for case in dev:
        assert bool(case.allowed_chunk_ids) == (case.expected_status == "answered")


def test_final_set_matches_the_required_composition() -> None:
    dev, test = load()
    grading = load_grading(EVAL / "test-grading.json")
    assert check_final_set(test, grading) == []  # 직접 10, 변형 7, 근거 없음 3
    assert check_no_overlap(test, dev) == []


def test_final_set_shares_no_evidence_chunk_with_the_dev_set() -> None:
    dev, test = load()
    dev_chunks = {i for case in dev for i in case.allowed_chunk_ids}
    test_chunks = {i for case in test for i in case.allowed_chunk_ids}
    assert dev_chunks.isdisjoint(test_chunks)


def test_final_set_covers_both_districts_evenly() -> None:
    _, test = load()
    districts = [case.district for case in test]
    assert districts.count("서대문구") == districts.count("송파구") == 10
