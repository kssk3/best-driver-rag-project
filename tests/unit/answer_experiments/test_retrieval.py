"""Exercise the same scoped search contract through both real adapters."""

from copy import deepcopy

import pytest

from src.evaluation.answer_experiments.retrieval import (
    RetrievalDocument,
    prepare_adapters,
)


def document(identifier, district, text, *, eligible=True):
    return RetrievalDocument(
        document_key=identifier,
        district=district,
        eligible_for_disposal=eligible,
        evidence={
            "source": {"document_id": identifier, "source_location": "합성 사례"},
            "text": text,
            "chunk_id": None,
        },
    )


def test_both_adapters_rank_only_eligible_documents_in_the_same_scope():
    exact_match = "서대문구에서 종이팩 수거용기의 색상은 무엇인가요?"
    documents = [
        document("other-district", "송파구", exact_match),
        document("signage", "서대문구", exact_match, eligible=False),
        document("color-spec", "서대문구", "종이팩 재활용 수거용기 색상은 녹색"),
        document("common", None, "종이상자는 분리배출 전에 펼칩니다"),
    ]
    original = deepcopy(documents)

    for adapter in prepare_adapters(documents, districts=("서대문구", "송파구")):
        results = adapter.search(exact_match, district="서대문구", k=5)
        assert [item.rank for item in results] == [1, 2]
        assert {item.evidence["source"]["document_id"] for item in results} == {
            "color-spec",
            "common",
        }
        assert all(item.evidence["chunk_id"] is None for item in results)
        assert adapter.search(exact_match, district="서대문구", k=1) == results[:1]
        with pytest.raises(ValueError, match="k"):
            adapter.search(exact_match, district="서대문구", k=6)
    assert documents == original


def test_fusion_keeps_distinct_sources_with_identical_text():
    documents = [
        document("source-one", "송파구", "재활용 일반 폐기물 수거 일정"),
        document("source-two", "송파구", "재활용 일반 폐기물 수거 일정"),
    ]

    for adapter in prepare_adapters(documents, districts=("서대문구", "송파구")):
        assert adapter.search("폐기물 일정", district="서대문구", k=5) == []
        results = adapter.search("폐기물 일정", district="송파구", k=5)
        assert {item.evidence["source"]["document_id"] for item in results} == {
            "source-one",
            "source-two",
        }
