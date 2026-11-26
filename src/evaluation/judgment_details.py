"""Faithfulness가 반환한 두 단계의 원문을 평가 시도 단위로 보관한다."""

from pydantic import BaseModel, ConfigDict, Field


class Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    statement: str
    verdict: int
    reason: str


class JudgmentDetails(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    evaluation_id: str
    attempt_index: int
    run_id: str
    metric: str
    model_input_chunk_ids: list[str] = Field(default_factory=list)
    # None은 해당 단계가 결과를 반환하기 전에 실패한 경우다.
    statements: list[str] | None = None
    verdicts: list[Verdict] | None = None
