"""Adapt shared pipeline requests and chunks to the answer generation contract."""

import re
from collections.abc import Callable, Mapping

from src.common.errors import ApplicationError, ErrorCategory
from src.contracts import Chunk, GenerationResult, PipelineRequest
from src.generation.answer import (
    AnswerDraft,
    Evidence,
    GenerationInput,
    generate_answer,
)

# 실패 이유는 한 구간의 snake_case여야 generation.<이유> 코드로 기록한다.
_REASON_PATTERN = re.compile(r"[a-z][a-z0-9_]*")


class AnswerGenerationError(ApplicationError, RuntimeError):
    """Expose a stable failure reason through the shared pipeline error state.

    The message stays the bare reason (e.g. ``invalid_draft``); ``code`` carries
    ``generation.<reason>`` for evaluation. A reason that is not a single snake_case
    segment is coded ``generation.invalid_error_kind``, and a raise without ``code``
    keeps the default ``generation.failed`` (unclassified). RuntimeError is kept for
    compatibility.
    """

    code = "generation.failed"
    category = ErrorCategory.INTERNAL
    user_message = "답변을 준비하는 중 오류가 발생했습니다."


def _generation_error(reason: object) -> AnswerGenerationError:
    # error_kind는 지금 answer.py의 고정값뿐이지만, 값이 바뀌어도 형식 검사 오류가
    # 원래 생성 실패를 덮지 않도록 형식이 틀리면 invalid_error_kind로 기록한다.
    # 클래스 기본값 generation.failed는 코드 없이 던진 미분류 오류용으로 남긴다.
    if isinstance(reason, str) and _REASON_PATTERN.fullmatch(reason):
        return AnswerGenerationError(reason, code=f"generation.{reason}")
    text = reason if isinstance(reason, str) else "generation_failed"
    return AnswerGenerationError(text, code="generation.invalid_error_kind")


def _to_evidence(chunk: Chunk) -> Evidence:
    return {
        "chunk_id": chunk.chunk_id,
        "text": chunk.content,
        "source": {
            "document_id": chunk.source_document_id,
            "document_version": chunk.source_document_version,
            "title": chunk.title,
            "content_format": chunk.content_format,
            "source_url": chunk.source_url,
            "source_location": chunk.source_location,
            "chunking_version": chunk.chunking_version,
        },
        "scope_type": chunk.scope_type,
        "districts": chunk.districts,
        "conditions": chunk.conditions,
    }


def make_answer_generator(
    draft_answer: Callable[[GenerationInput], AnswerDraft],
    *,
    required_conditions: Mapping[str, str] | None = None,
    decode_conditions: Callable[[Mapping[str, str]], dict[str, object]] | None = None,
) -> Callable[[PipelineRequest, list[Chunk]], GenerationResult]:
    """Build the generator callback accepted by create_runtime.

    The shared runtime records its selected context. Provider invocation and
    payload tracing belong to the injected draft function.
    """
    required = dict(required_conditions or {})

    def generate(request: PipelineRequest, chunks: list[Chunk]) -> GenerationResult:
        raw_conditions = dict(request.conditions)
        try:
            conditions: dict[str, object] = (
                dict(raw_conditions)
                if decode_conditions is None
                else decode_conditions(raw_conditions)
            )
        except Exception:
            raise _generation_error("condition_decode_failed") from None
        if request.district is not None:
            conditions["district"] = request.district
        if request.dong is not None:
            conditions["dong"] = request.dong

        answer = generate_answer(
            {
                "original_question": request.question,
                "conditions": conditions,
                "evidence": [_to_evidence(chunk) for chunk in chunks],
                "required_conditions": required,
            },
            draft_answer,
        )
        if answer is None:
            raise _generation_error("pending_evidence")
        status = answer["status"]
        if status == "error":
            raise _generation_error(answer.get("error_kind", "generation_failed"))

        allowed_ids = {chunk.chunk_id for chunk in chunks}
        cited_ids = []
        for citation in answer["citations"]:
            chunk_id = citation["chunk_id"]
            if chunk_id is None or not chunk_id.strip() or chunk_id not in allowed_ids:
                raise _generation_error("invalid_citation")
            cited_ids.append(chunk_id)
        return GenerationResult(
            status=status, answer=answer["message"], cited_chunk_ids=cited_ids
        )

    return generate
