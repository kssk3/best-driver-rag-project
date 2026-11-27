"""비교 패널의 방식별 점수 요약 값. 화면(Streamlit)을 모르는 순수 값만 둔다.

점수는 Langfuse에서 읽는다(langfuse_scores.py). 방식별 건수와 평균을 같은 모양으로 표시한다.
"""

from dataclasses import dataclass

VARIANTS = ("A", "B", "C")


@dataclass(frozen=True)
class VariantSummary:
    variant: str
    count: int
    # None은 숫자 점수가 하나도 없다는 뜻이다. 유효한 0.0 평균과 구별해야 한다.
    mean: float | None
