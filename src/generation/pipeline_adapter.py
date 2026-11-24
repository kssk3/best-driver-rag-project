"""Adapt shared pipeline requests and chunks to the answer generation contract."""

from collections.abc import Callable, Mapping

from src.contracts import Chunk, GenerationResult, PipelineRequest
from src.generation.answer import AnswerDraft, Evidence, GenerationInput, generate_answer


class AnswerGenerationError(RuntimeError):
    """Expose a stable failure reason through the shared pipeline error state."""


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
                dict(raw_conditions) if decode_conditions is None
                else decode_conditions(raw_conditions)
            )
        except Exception:
            raise AnswerGenerationError("condition_decode_failed") from None
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
            raise AnswerGenerationError("pending_evidence")
        status = answer["status"]
        if status == "error":
            raise AnswerGenerationError(answer.get("error_kind", "generation_failed"))

        allowed_ids = {chunk.chunk_id for chunk in chunks}
        cited_ids = []
        for citation in answer["citations"]:
            chunk_id = citation["chunk_id"]
            if chunk_id is None or not chunk_id.strip() or chunk_id not in allowed_ids:
                raise AnswerGenerationError("invalid_citation")
            cited_ids.append(chunk_id)
        return GenerationResult(status=status, answer=answer["message"], cited_chunk_ids=cited_ids)

    return generate
