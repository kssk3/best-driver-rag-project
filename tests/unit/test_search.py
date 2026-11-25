"""A(Vector) 검색 단위 테스트. 실제 임베딩 API 없이 손으로 정한 벡터를 쓴다."""

import pytest

from src.contracts import Chunk, ResolvedQuery, SearchCandidate
from src.ingestion.indexing import build_index
from src.retrieval.search import (
    RetrievalConfigError,
    RetrievalError,
    RetrievalVariantError,
    bm25_search,
    cosine_similarity,
    is_in_region,
    make_vector_retriever,
    rrf_merge,
    tokenize,
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


# --- 제외 목록 (송파 별표 4 요일표) -------------------------------------------


def make_songpa_schedule_index(location: str):
    """송파 시행규칙 첨부의 주어진 위치 청크 하나와 일반 송파 청크 하나로 색인을 만든다."""
    schedule = make_chunk("schedule", "district", ["송파구"], "송파 페트병").model_copy(
        update={
            "source_document_id": "songpa-rules:attachment:121237861",
            "source_location": location,
        }
    )
    other = make_chunk("songpa-pet", "district", ["송파구"], "송파 페트병")
    return build_index([schedule, other], FakeEmbedder())


def test_excluded_schedule_table_is_not_searched():
    # 별표 4 요일표(table-2)는 질문과 똑같아도 A·BM25 어디에도 나오지 않는다.
    index = make_songpa_schedule_index("table-2/row[3]")

    vector_ids = [
        r.chunk.chunk_id for r in vector_search(index, [1.0, 0.0, 0.0], "송파구", 5)
    ]
    bm25_ids = [
        r.chunk.chunk_id for r in bm25_search(index, "송파 페트병", "송파구", 5)
    ]

    assert vector_ids == ["songpa-pet"]
    assert bm25_ids == ["songpa-pet"]


def test_exclusion_matches_only_listed_table():
    # 같은 첨부라도 다른 표(table-3: 포상금 지급기준)는 그대로 검색한다.
    index = make_songpa_schedule_index("table-3/row[0]")

    results = bm25_search(index, "송파 페트병", "송파구", 5)
    assert {r.chunk.chunk_id for r in results} == {"schedule", "songpa-pet"}


# --- tokenize (BM25용 2글자 조각) -------------------------------------------


def test_tokenize_splits_words_into_bigrams_and_keeps_single_letters():
    # "페트병은" → 페트·트병·병은, 1글자 "캔"은 그대로, 문장부호는 버린다.
    assert tokenize("페트병은 캔?") == ["페트", "트병", "병은", "캔"]


def test_tokenize_shares_bigrams_when_particle_differs():
    # 조사가 달라도("은" / "을") 핵심 조각 "페트", "트병"을 공유한다.
    assert {"페트", "트병"} <= set(tokenize("페트병을"))


def test_tokenize_ignores_html_tags():
    # HTML 청크의 태그 이름·속성은 본문이 아니므로 조각에 넣지 않는다.
    assert tokenize('<p data-x="y">캔 &amp; 병</p>') == ["캔", "병"]


# --- bm25_search ------------------------------------------------------------


def test_bm25_search_ranks_by_shared_bigrams_within_region():
    results = bm25_search(make_index(), "서대문 페트병", "서대문구", top_k=5)
    ids = [r.chunk.chunk_id for r in results]

    # 글자가 가장 많이 겹치는 서대문 페트병이 1위. 송파·지역 미확인은 지역 필터로 빠진다.
    assert ids[0] == "seodaemun-pet"
    assert "songpa-pet" not in ids
    assert "unknown-pet" not in ids
    assert [r.rank for r in results] == list(range(1, len(results) + 1))
    assert set(results[0].stage_scores) == {"bm25"}


def test_bm25_search_drops_chunks_without_shared_bigrams():
    # 질문과 겹치는 조각이 없는 청크(점수 0)는 '글자로 맞은 문서'가 아니라서 뺀다.
    results = bm25_search(make_index(), "종이팩", "서대문구", top_k=5)
    assert [r.chunk.chunk_id for r in results] == ["seodaemun-carton"]


def test_bm25_search_returns_empty_when_query_has_no_words():
    assert bm25_search(make_index(), "?!", "서대문구", top_k=5) == []


def test_bm25_search_rejects_non_positive_top_k():
    with pytest.raises(RetrievalError):
        bm25_search(make_index(), "페트병", "서대문구", top_k=0)


# --- rrf_merge (순위 합치기) -------------------------------------------------


def ranked(*chunk_ids: str, score: float = 1.0) -> list[SearchCandidate]:
    """주어진 순서대로 1위부터 순위를 매긴 합성 후보 목록."""
    return [
        SearchCandidate(
            chunk=make_chunk(cid, "district", ["서대문구"], cid), rank=n, score=score
        )
        for n, cid in enumerate(chunk_ids, start=1)
    ]


def test_rrf_merge_adds_reciprocal_ranks_from_each_list():
    # x: vector 1위 + bm25 2위 → 1/61 + 1/62,  y: vector 2위 + bm25 1위 → 1/62 + 1/61
    # z: vector 3위만 → 1/63.  x·y 동점이면 chunk_id 순.
    merged = rrf_merge(
        {"vector": ranked("x", "y", "z"), "bm25": ranked("y", "x")}, top_k=5
    )

    assert [c.chunk.chunk_id for c in merged] == ["x", "y", "z"]
    assert merged[0].score == pytest.approx(1 / 61 + 1 / 62)
    assert merged[2].score == pytest.approx(1 / 63)
    assert [c.rank for c in merged] == [1, 2, 3]


def test_rrf_merge_prefers_document_found_by_both():
    # 한쪽 1위(only-a)보다 양쪽 모두 2위(both)가 위로 온다: 2/62 > 1/61.
    merged = rrf_merge(
        {"vector": ranked("only-a", "both"), "bm25": ranked("only-b", "both")},
        top_k=5,
    )
    assert merged[0].chunk.chunk_id == "both"


def test_rrf_merge_keeps_stage_scores_and_top_k():
    merged = rrf_merge(
        {
            "vector": ranked("x", "y", score=0.9),
            "bm25": ranked("x", score=12.0),
        },
        top_k=1,
    )

    assert len(merged) == 1
    assert merged[0].stage_scores == {
        "vector": 0.9,
        "bm25": 12.0,
        "rrf": pytest.approx(1 / 61 + 1 / 61),
    }


def test_rrf_merge_rejects_non_positive_top_k():
    with pytest.raises(RetrievalError):
        rrf_merge({"vector": ranked("x")}, top_k=0)


# --- make_vector_retriever (파이프라인 규격) --------------------------------


def test_retriever_follows_pipeline_contract():
    retrieve = make_vector_retriever(make_index(), FakeEmbedder())
    query = ResolvedQuery(search_query="페트병 질문", district="서대문구")

    results = retrieve(query, variant="A", top_k=5)

    assert results[0].chunk.chunk_id == "seodaemun-pet"
    assert all(r.chunk.chunk_id != "songpa-pet" for r in results)


def test_retriever_runs_hybrid_variant_b():
    # B = Vector + BM25를 RRF로 합친 결과. 지역 필터와 단계 점수 기록을 확인한다.
    retrieve = make_vector_retriever(make_index(), FakeEmbedder())
    query = ResolvedQuery(search_query="서대문 페트병", district="서대문구")

    results = retrieve(query, variant="B", top_k=5)
    ids = [r.chunk.chunk_id for r in results]

    # 서대문 페트병: Vector 1위(1.0) + BM25 1위(서대·대문·페트·트병 모두 겹침) → B 1위.
    # (질문이 "페트병 질문"이면 BM25는 더 짧은 공통 페트병을 1위로 줘서 RRF 동점이 된다.)
    assert ids[0] == "seodaemun-pet"
    assert "songpa-pet" not in ids and "unknown-pet" not in ids
    assert {"vector", "bm25", "rrf"} <= set(results[0].stage_scores)
    assert results[0].score == results[0].stage_scores["rrf"]


@pytest.mark.parametrize("variant", ["C", "Z"])
def test_retriever_rejects_unsupported_variant(variant):
    # 아직 없는 검색 방식은 빈 결과가 아니라 설정 오류로 알린다.
    retrieve = make_vector_retriever(make_index(), FakeEmbedder())
    query = ResolvedQuery(search_query="페트병 질문", district="서대문구")

    with pytest.raises(RetrievalVariantError) as caught:
        retrieve(query, variant=variant, top_k=5)
    assert caught.value.code == "retrieval.unsupported_variant"


def test_retriever_rejects_embedder_different_from_index():
    # 색인을 만든 임베딩과 다른 임베딩이면 벡터를 비교할 수 없다 → 설정 오류.
    class OtherEmbedder(FakeEmbedder):
        identity = "another-embedding-v1"

    with pytest.raises(RetrievalConfigError):
        make_vector_retriever(make_index(), OtherEmbedder())
