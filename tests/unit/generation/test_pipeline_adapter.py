"""Verify the common generation callback boundary."""

from unittest.mock import Mock

import pytest

from src.contracts import Chunk, PipelineRequest
from src.generation.pipeline_adapter import AnswerGenerationError, make_answer_generator


def _chunk() -> Chunk:
    return Chunk(
        chunk_id="supplied-id",
        source_document_id="document",
        source_document_version="revision",
        title="원문 제목",
        content_format="html",
        content="<p>검증된 내용</p>",
        source_url="https://example.org/evidence",
        source_location="표 4",
        scope_type="district",
        districts=["송파구"],
        conditions=["공동주택"],
        chunking_version="test",
    )


def test_adapter_preserves_user_input_and_offered_chunk():
    chunk = _chunk()
    draft = Mock(return_value={"status": "answered", "message": "근거 안내", "citation_indices": [0]})
    request = PipelineRequest(
        question=" 원래 질문 ",
        district="송파구",
        dong="위례동",
        conditions={"item": "[종이]", "district": "예전 구"},
    )
    result = make_answer_generator(draft)(request, [chunk])
    assert result.cited_chunk_ids == [chunk.chunk_id]
    payload = draft.call_args.args[0]
    assert payload["original_question"] == request.question
    assert payload["conditions"] == {"district": "송파구", "dong": "위례동", "item": "[종이]"}
    [evidence] = payload["evidence"]
    assert evidence["text"] == chunk.content
    assert evidence["source"]["document_id"] == chunk.source_document_id
    assert evidence["source"]["source_url"] == chunk.source_url
    assert evidence["scope_type"] == "district"
    assert evidence["districts"] == ["송파구"]
    assert evidence["conditions"] == ["공동주택"]


def test_empty_context_and_clarification_skip_drafting():
    draft = Mock()
    request = PipelineRequest(question="어떻게 배출해요?")
    assert make_answer_generator(draft)(request, []).status == "insufficient_evidence"
    required = make_answer_generator(draft, required_conditions={"district": "구"})
    result = required(request, [_chunk()])
    assert result.status == "needs_clarification"
    assert result.cited_chunk_ids == []
    draft.assert_not_called()


def test_citation_outside_context_and_provider_failure_are_sanitized():
    request = PipelineRequest(question="근거는?")
    draft = Mock(return_value={"status": "answered", "message": "근거 안내", "citation_indices": [1]})
    with pytest.raises(AnswerGenerationError, match="invalid_draft"):
        make_answer_generator(draft)(request, [_chunk()])
    failing_draft = Mock(side_effect=ValueError("private provider diagnostic"))
    with pytest.raises(AnswerGenerationError, match="generation_failed") as error:
        make_answer_generator(failing_draft)(request, [_chunk()])
    assert "private provider diagnostic" not in str(error.value)


def test_blank_chunk_identifier_cannot_be_used():
    draft = Mock()
    chunk = _chunk().model_copy(update={"chunk_id": " "})
    with pytest.raises(AnswerGenerationError, match="invalid_input"):
        make_answer_generator(draft)(PipelineRequest(question="근거는?"), [chunk])
    draft.assert_not_called()


@pytest.mark.parametrize("second_version", ["revision", "next-revision"])
def test_conflict_uses_document_versions_instead_of_rendering_or_row(second_version):
    first = _chunk()
    second = first.model_copy(update={
        "chunk_id": "second-id",
        "source_document_version": second_version,
        "content_format": "json",
        "content": '{"guidance":"금요일에 배출"}',
        "source_location": "표 5",
    })
    draft = Mock(return_value={
        "status": "source_conflict",
        "conflict_sides": [
            {"evidence_index": 0, "excerpt": "검증된 내용"},
            {"evidence_index": 1, "excerpt": "금요일에 배출"},
        ],
    })
    generator = make_answer_generator(draft)
    request = PipelineRequest(question="두 안내가 일치하나요?")

    if second_version == first.source_document_version:
        with pytest.raises(AnswerGenerationError, match="invalid_draft"):
            generator(request, [first, second])
    else:
        result = generator(request, [first, second])
        assert result.status == "insufficient_evidence"
        assert result.cited_chunk_ids == [first.chunk_id, second.chunk_id]
        assert "확정하기 어렵습니다" in result.answer
