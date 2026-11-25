"""A(Vector) 검색 단위 테스트. 실제 임베딩 API 없이 손으로 정한 벡터를 쓴다."""

import pytest

from src.contracts import Chunk, ResolvedQuery
from src.ingestion.indexing import build_index
from src.retrieval.search import (
    RetrievalConfigError,
    RetrievalError,
    cosine_similarity,
    is_in_region,
    make_vector_retriever,
    vector_search,
)


def make_chunk(chunk_id: str, scope: str, districts: list[str], content: str) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        source_document_id=f"synthetic-{chunk_id}",
        source_document_version="v1",
        title="합성 안내",
        content_format="html",
        content=content,
        source_url="https://example.org/guide",
        source_location="합성 별표 1",
        scope_type=scope,
        districts=districts,
        chunking_version="synthetic-v1",
    )


class FakeEmbedder:
    """본문마다 미리 정한 벡터를 돌려주는 합성 임베딩 (검색 순서를 예측 가능하게)."""

    identity = "synthetic-fixed-vectors-v1"
    vectors = {
        "서대문 페트병": [1.0, 0.0, 0.0],
        "서대문 종이팩": [0.6, 0.8, 0.0],
        "송파 페트병": [
            1.0,
            0.0,
            0.0,
        ],  # 다른 구지만 질문과 가장 비슷함 → 필터로 빠져야 함
        "공통 페트병": [0.8, 0.6, 0.0],
        "지역 미확인 페트병": [1.0, 0.0, 0.0],
        "페트병 질문": [1.0, 0.0, 0.0],
    }

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.vectors[text] for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self.vectors[text]


CHUNKS = [
    make_chunk("seodaemun-pet", "district", ["서대문구"], "서대문 페트병"),
    make_chunk("seodaemun-carton", "district", ["서대문구"], "서대문 종이팩"),
    make_chunk("songpa-pet", "district", ["송파구"], "송파 페트병"),
    make_chunk("common-pet", "common", [], "공통 페트병"),
    make_chunk("unknown-pet", "unknown", [], "지역 미확인 페트병"),
]


def make_index():
    return build_index(CHUNKS, FakeEmbedder())


# --- is_in_region -----------------------------------------------------------


def test_is_in_region_keeps_selected_district_and_common():
    assert is_in_region(CHUNKS[0], "서대문구") is True  # 서대문구 문서
    assert is_in_region(CHUNKS[3], "서대문구") is True  # 공통 문서


def test_is_in_region_drops_other_district_and_unknown():
    assert is_in_region(CHUNKS[2], "서대문구") is False  # 송파구 문서
    assert is_in_region(CHUNKS[4], "서대문구") is False  # 지역 미확인 문서


def test_is_in_region_without_district_keeps_only_common():
    assert is_in_region(CHUNKS[3], None) is True
    assert is_in_region(CHUNKS[0], None) is False


# --- cosine_similarity ------------------------------------------------------


def test_cosine_similarity_same_direction_is_one():
    assert cosine_similarity([1.0, 0.0], [2.0, 0.0]) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_is_zero():
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_similarity_zero_vector_is_zero():
    assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


# --- vector_search ----------------------------------------------------------


def test_vector_search_ranks_by_similarity_within_region():
    results = vector_search(make_index(), [1.0, 0.0, 0.0], "서대문구", top_k=5)

    # 송파구·지역 미확인 문서는 질문과 가장 비슷해도 빠진다.
    assert [r.chunk.chunk_id for r in results] == [
        "seodaemun-pet",  # 1.0
        "common-pet",  # 0.8
        "seodaemun-carton",  # 0.6
    ]
    assert [r.rank for r in results] == [1, 2, 3]
    assert results[0].score == pytest.approx(1.0)


def test_vector_search_keeps_only_top_k():
    results = vector_search(make_index(), [1.0, 0.0, 0.0], "서대문구", top_k=2)
    assert [r.chunk.chunk_id for r in results] == ["seodaemun-pet", "common-pet"]


def test_vector_search_rejects_wrong_dimension():
    # 오류를 빈 결과로 숨기지 않는다.
    with pytest.raises(ValueError):
        vector_search(make_index(), [1.0, 0.0], "서대문구", top_k=5)


def test_vector_search_rejects_non_positive_top_k():
    # top_k가 0이면 빈 결과가 아니라 입력 오류로 알린다.
    with pytest.raises(RetrievalError):
        vector_search(make_index(), [1.0, 0.0, 0.0], "서대문구", top_k=0)


# --- make_vector_retriever (파이프라인 규격) --------------------------------


def test_retriever_follows_pipeline_contract():
    retrieve = make_vector_retriever(make_index(), FakeEmbedder())
    query = ResolvedQuery(search_query="페트병 질문", district="서대문구")

    results = retrieve(query, variant="A", top_k=5)

    assert results[0].chunk.chunk_id == "seodaemun-pet"
    assert all(r.chunk.chunk_id != "songpa-pet" for r in results)


def test_retriever_raises_for_unimplemented_variant():
    retrieve = make_vector_retriever(make_index(), FakeEmbedder())
    query = ResolvedQuery(search_query="페트병 질문", district="서대문구")

    with pytest.raises(NotImplementedError):
        retrieve(query, variant="B", top_k=5)


def test_retriever_rejects_embedder_different_from_index():
    # 색인을 만든 임베딩과 다른 임베딩이면 벡터를 비교할 수 없다 → 설정 오류.
    class OtherEmbedder(FakeEmbedder):
        identity = "another-embedding-v1"

    with pytest.raises(RetrievalConfigError):
        make_vector_retriever(make_index(), OtherEmbedder())
