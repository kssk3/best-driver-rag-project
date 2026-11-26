"""Ragas 채점 단계에서 원문 없이 실패 위치와 오류 유형을 기록한다."""

import json
from contextlib import contextmanager

from instructor.core.exceptions import (
    AsyncValidationError,
    IncompleteOutputException,
    ResponseParsingError,
)
from openai import (
    APIConnectionError,
    APIResponseValidationError,
    APIStatusError,
    APITimeoutError,
)
from pydantic import ValidationError
from ragas.metrics.collections import Faithfulness

from src.evaluation.answer_metrics import JudgeError
from src.evaluation.judgment_details import JudgmentDetails, Verdict


def _error_kind(error: BaseException) -> str:
    # Instructor는 SDK 또는 응답 검증 예외를 원인으로 연결한다.
    seen: set[int] = set()
    cause: BaseException | None = error
    while cause is not None and id(cause) not in seen:
        seen.add(id(cause))
        if isinstance(cause, APIStatusError):
            return f"http_{cause.status_code}"
        if isinstance(cause, APITimeoutError):
            return "timeout"
        if isinstance(cause, APIConnectionError):
            return "connection"
        if isinstance(
            cause,
            (
                ValidationError,
                json.JSONDecodeError,
                ResponseParsingError,
                AsyncValidationError,
                IncompleteOutputException,
                APIResponseValidationError,
            ),
        ):
            return "invalid_response"
        cause = cause.__cause__
    return "error"


@contextmanager
def judge_stage(stage: str):
    try:
        yield
    except Exception as error:
        raise JudgeError(f"judge_{stage}_{_error_kind(error)}") from None


class ArchivedFaithfulness(Faithfulness):
    """Ragas의 프롬프트, 재시도 설정 및 점수 계산을 그대로 사용한다."""

    details: JudgmentDetails | None = None

    async def _create_statements(self, question, response):
        with judge_stage("statements"):
            result = await super()._create_statements(question, response)
            if self.details is not None:
                self.details.statements = list(result)
            return result

    async def _create_verdicts(self, statements, context):
        with judge_stage("verdicts"):
            result = await super()._create_verdicts(statements, context)
            if self.details is not None:
                self.details.verdicts = [
                    Verdict(**item.model_dump()) for item in result.statements
                ]
            return result
