"""비교 패널의 점수 집계(src/interface/comparison.py)를 확인한다. 외부 호출은 하지 않는다."""

import csv
from pathlib import Path
from statistics import mean

import pytest

from src.evaluation.answer_metrics import FIELDS
from src.interface.comparison import (
    ScoresFileError,
    VariantSummary,
    format_summary,
    summarize_scores,
)


def write_scores(path: Path, rows: list[dict], fieldnames=FIELDS) -> Path:
    # 실제 scores.csv와 같은 열을 쓰고, 이 테스트가 보지 않는 열은 비워 둔다.
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, restval="")
        writer.writeheader()
        writer.writerows(rows)
    return path


def row(variant: str, score: str, eligible: str = "true") -> dict:
    return {
        "variant": variant,
        "score": score,
        "comparison_eligible": eligible,
        "metric": "faithfulness",
    }


def by_variant(summaries: list[VariantSummary]) -> dict[str, VariantSummary]:
    return {summary.variant: summary for summary in summaries}


def test_only_eligible_rows_are_counted_per_variant(tmp_path) -> None:
    path = write_scores(
        tmp_path / "scores.csv",
        [
            row("A", "1.0"),
            row("A", "0.5"),
            row("B", "0.25"),
            row("A", "0.0", eligible="false"),  # 제외 행은 점수가 있어도 세지 않는다.
            row("C", "0.9", eligible="false"),
        ],
    )

    result = by_variant(summarize_scores(path))

    assert (result["A"].count, result["A"].mean) == (2, 0.75)
    assert (result["B"].count, result["B"].mean) == (1, 0.25)
    assert (result["C"].count, result["C"].mean) == (0, None)


def test_a_valid_zero_is_a_score_but_no_score_is_not(tmp_path) -> None:
    path = write_scores(tmp_path / "scores.csv", [row("A", "0.0")])

    result = by_variant(summarize_scores(path))

    assert format_summary(result["A"]) == "1건 · 평균 0.000"
    assert format_summary(result["B"]) == "0건 · 평균 —"


def test_rows_that_are_not_eligible_may_carry_any_score_text(tmp_path) -> None:
    path = write_scores(
        tmp_path / "scores.csv",
        [row("A", "", eligible="false"), row("B", "nan", eligible="false")],
    )

    assert all(s.count == 0 for s in summarize_scores(path))


def test_result_matches_the_readme_example(tmp_path) -> None:
    rows = [row("A", "0.8"), row("A", "0.6"), row("B", "1.0"), row("C", "0.1")]
    path = write_scores(tmp_path / "scores.csv", rows)

    expected = {"A": [], "B": [], "C": []}
    for r in csv.DictReader(path.open(newline="", encoding="utf-8")):
        if r["comparison_eligible"] == "true":
            expected[r["variant"]].append(float(r["score"]))

    actual = {s.variant: (s.count, s.mean) for s in summarize_scores(path)}
    assert actual == {v: (len(x), mean(x) if x else None) for v, x in expected.items()}


@pytest.mark.parametrize(
    "bad_row, code",
    [
        (row("A", ""), "invalid_score"),
        (row("A", "abc"), "invalid_score"),
        (row("A", "nan"), "invalid_score"),
        (row("D", "1.0"), "unknown_variant"),
    ],
)
def test_an_eligible_row_that_cannot_be_counted_is_an_error(
    tmp_path, bad_row, code
) -> None:
    path = write_scores(tmp_path / "scores.csv", [row("A", "1.0"), bad_row])

    with pytest.raises(ScoresFileError, match=code):
        summarize_scores(path)


@pytest.mark.parametrize("missing", ["variant", "score", "comparison_eligible"])
def test_a_file_without_a_needed_column_is_an_error(tmp_path, missing) -> None:
    fields = [name for name in FIELDS if name != missing]
    path = write_scores(tmp_path / "scores.csv", [], fieldnames=fields)

    with pytest.raises(ScoresFileError, match="missing_columns"):
        summarize_scores(path)


def test_an_empty_file_is_an_error(tmp_path) -> None:
    path = tmp_path / "scores.csv"
    path.write_bytes(b"")

    with pytest.raises(ScoresFileError, match="missing_columns"):
        summarize_scores(path)
