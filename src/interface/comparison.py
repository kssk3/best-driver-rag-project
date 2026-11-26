"""비교 패널의 점수 집계. 화면(Streamlit)을 모르는 순수 함수만 둔다.

규칙은 results/README.md의 "실검색 A/B/C 점수 비교"를 따른다. 한 평가의 scores.csv에서
comparison_eligible이 "true"인 행만 variant별로 모아 건수와 평균을 낸다.
"""

import csv
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from statistics import mean

VARIANTS = ("A", "B", "C")
REQUIRED_COLUMNS = ("variant", "score", "comparison_eligible")


class ScoresFileError(ValueError):
    """scores.csv를 집계할 수 없는 경우. 코드만 담고 파일 내용(질문·답변)은 넣지 않는다."""


@dataclass(frozen=True)
class VariantSummary:
    variant: str
    count: int
    # None은 숫자 점수가 하나도 없다는 뜻이다. 유효한 0.0 평균과 구별해야 한다.
    mean: float | None


def summarize_scores(path: Path) -> list[VariantSummary]:
    values: dict[str, list[float]] = {variant: [] for variant in VARIANTS}
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if not set(REQUIRED_COLUMNS) <= set(reader.fieldnames or ()):
            raise ScoresFileError("missing_columns")
        for row in reader:
            if row["comparison_eligible"] != "true":
                continue
            if row["variant"] not in values:
                raise ScoresFileError("unknown_variant")
            try:
                score = float(row["score"])
            except (TypeError, ValueError):
                raise ScoresFileError("invalid_score") from None
            if not isfinite(score):
                raise ScoresFileError("invalid_score")
            values[row["variant"]].append(score)
    return [
        VariantSummary(variant, len(scores), mean(scores) if scores else None)
        for variant, scores in values.items()
    ]


def format_summary(summary: VariantSummary) -> str:
    average = "—" if summary.mean is None else f"{summary.mean:.3f}"
    return f"{summary.count}건 · 평균 {average}"
