"""Run both source evidence question sets through the shared runtime offline."""

import json
from pathlib import Path

import pytest

from src.config import RuntimeSettings
from src.contracts import (
    Chunk,
    PipelineOptions,
    ResolvedQuery,
    SearchCandidate,
    SourceDocument,
)
from src.evaluation.answer_experiments.evidence_answer_probe import (
    decode_evidence_conditions,
    draft_evidence_answer,
    make_evidence_request,
)
from src.evaluation.answer_experiments.evidence_retrieval_benchmark import (
    _CASES,
    _evidence_corpus,
)
from src.generation.pipeline_adapter import make_answer_generator
from src.ingestion.chunking import chunk_documents
from src.ingestion.preprocessed_bundle import load_preprocessed_bundle
from src.ingestion.preprocessed_chunking import chunk_preprocessed_documents
from src.runtime import create_runtime

PROJECT = Path(__file__).resolve().parents[3]
BUNDLE = PROJECT / "data/handoff/jungeun/ordinance-handoff-2026-11-24"
COLOR_ID = "seodaemun-rules:attachment:160561037"
SIGNAGE_ID = "seodaemun-ordinance:attachment:160319461"


@pytest.fixture(scope="module")
def annex_chunks() -> list[Chunk]:
    bundle = load_preprocessed_bundle(BUNDLE, project_root=PROJECT, version="v1")
    return chunk_preprocessed_documents(
        [doc for doc in bundle.documents if doc.document_id in {COLOR_ID, SIGNAGE_ID}]
    )


def _schedule_chunks() -> list[Chunk]:
    # The established source evidence passages are synthetic excerpts. Use their reviewed URLs
    # and the shared chunker's IDs to exercise provenance through the runtime.
    review_path = BUNDLE / "review/schedule_evidence/conflict_evidence.json"
    review = json.loads(review_path.read_text(encoding="utf-8"))
    urls = {entry["source_type"]: entry["url"] for entry in review["sources"]}
    chunks = []
    for document in _evidence_corpus():
        if not document.document_key.startswith("evidence-wirye-"):
            continue
        evidence = document.evidence
        source = evidence["source"]
        [chunk] = chunk_documents(
            [
                SourceDocument(
                    document_id=document.document_key,
                    version="evidence-observation",
                    title=source["source_type"],
                    content_format="html",
                    content=evidence["text"],
                    source_url=urls[source["source_type"]],
                    scope_type="district",
                    districts=["송파구"],
                )
            ]
        )
        chunks.append(
            chunk.model_copy(update={"source_location": source["source_location"]})
        )
    return chunks


@pytest.mark.parametrize("case", _CASES, ids=lambda case: case.question_id)
@pytest.mark.parametrize("content_format", ["html", "json"])
def test_evidence_original_and_trick_questions_use_shared_runtime(
    case, content_format, annex_chunks, tmp_path
):
    if case.case_group == "observation":
        evidence = _schedule_chunks()
    else:
        source_id = SIGNAGE_ID if "signage" in case.question_id else COLOR_ID
        evidence = [
            next(
                chunk
                for chunk in annex_chunks
                if chunk.source_document_id == source_id
                and chunk.content_format == content_format
            )
        ]

    draft_inputs = []

    def draft(payload):
        draft_inputs.append(payload)
        return draft_evidence_answer(payload)

    runtime = create_runtime(
        RuntimeSettings(
            runs_path=tmp_path, pipeline=PipelineOptions(run_kind="fixed_evidence")
        ),
        resolver=lambda request: ResolvedQuery(
            search_query=request.question, district=request.district, dong=request.dong
        ),
        retriever=lambda *_args, **_kwargs: [
            SearchCandidate(chunk=chunk, rank=rank)
            for rank, chunk in enumerate(evidence, start=1)
        ],
        generator=make_answer_generator(
            draft, decode_conditions=decode_evidence_conditions
        ),
    )
    request = make_evidence_request(
        case.question, district=case.district, conditions=case.conditions
    )
    record = runtime.run(request)
    response = record.response
    assert record.run_kind == "fixed_evidence"
    assert len(draft_inputs) == 1  # One local drafting call.
    assert draft_inputs[0]["original_question"] == case.question
    assert draft_inputs[0]["conditions"] == {
        "district": case.district,
        **case.conditions,
    }
    assert (
        draft_inputs[0]["evidence"][0]["source"]["document_version"]
        == evidence[0].source_document_version
    )
    assert (
        draft_inputs[0]["evidence"][0]["source"]["source_location"]
        == evidence[0].source_location
    )
    assert record.model_input_chunk_ids == [chunk.chunk_id for chunk in evidence]
    assert (tmp_path / f"{record.run_id}.json").is_file()
    if case.case_group == "observation":
        assert record.request.dong == "위례동"
        assert response.status == "insufficient_evidence"
        assert "월·수·금" in response.answer and "화·목·일" in response.answer
        assert "확정하기 어렵습니다" in response.answer
        assert len(response.citations) == 2
    elif "signage" in case.question_id:
        assert draft_inputs[0]["evidence"][0]["source"]["document_id"] == SIGNAGE_ID
        assert response.status == "insufficient_evidence"
        assert response.citations == []
        return
    else:
        assert response.status == "answered"
        assert "캔 회색" in response.answer
        assert "유리병 주황색" in response.answer
        assert len(response.citations) == 1
    for citation, chunk in zip(response.citations, evidence, strict=True):
        assert citation.chunk_id == chunk.chunk_id
        assert citation.document_id == chunk.source_document_id
        assert citation.document_version == chunk.source_document_version
        assert citation.source_location == chunk.source_location
        assert citation.source_url == chunk.source_url


def test_review_overlay_supplies_color_and_cannot_override_scope(annex_chunks):
    chunk = next(
        chunk
        for chunk in annex_chunks
        if chunk.source_document_id == COLOR_ID and chunk.content_format == "json"
    )
    content = json.loads(chunk.content)
    content["structured_image_summary"]["colors"][0]["color"] = "은색"
    changed = chunk.model_copy(
        update={"content": json.dumps(content, ensure_ascii=False)}
    )
    generator = make_answer_generator(draft_evidence_answer)
    case = _CASES[1]
    request = make_evidence_request(
        case.question, district=case.district, conditions=case.conditions
    )
    assert "캔 은색" in generator(request, [changed]).answer
    other_source = changed.model_copy(update={"source_document_id": SIGNAGE_ID})
    assert generator(request, [other_source]).status == "insufficient_evidence"
    other_housing = request.model_copy(
        update={"conditions": {**request.conditions, "housing_type": "단독주택"}}
    )
    assert generator(other_housing, [changed]).status == "insufficient_evidence"
    other_district = changed.model_copy(update={"districts": ["송파구"]})
    assert generator(request, [other_district]).status == "insufficient_evidence"


def test_evidence_items_encoding_preserves_plain_conditions():
    values = ["음식,물", "유리", "음식,물"]
    request = make_evidence_request(
        "질문", district="송파구", conditions={"items": values, "foo": "[1]"}
    )
    assert decode_evidence_conditions(request.conditions) == {
        "items": values,
        "foo": "[1]",
    }
    ordinary = make_evidence_request(
        "질문", district="송파구", conditions={"items": '["유리"]'}
    )
    assert decode_evidence_conditions(ordinary.conditions) == {"items": '["유리"]'}
