"""A(Vector) 검색 단위 테스트. 실제 임베딩 API 없이 손으로 정한 벡터를 쓴다."""

import json
from pathlib import Path

import pytest

from src.contracts import Chunk, ResolvedQuery, SearchCandidate
from src.infrastructure.embeddings import DemoHashEmbeddings
from src.infrastructure.stores import load_index, save_index
from src.ingestion.indexing import build_index
from src.ingestion.preprocessed_bundle import load_preprocessed_bundle
from src.ingestion.preprocessed_chunking import chunk_preprocessed_documents
from src.retrieval.search import (
    RerankerOutputError,
    RetrievalConfigError,
    RetrievalError,
    RetrievalVariantError,
    bm25_search,
    chunk_text,
    cosine_similarity,
    is_in_region,
    is_searchable,
    make_vector_retriever,
    rerank,
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


def test_remapped_songpa_schedule_stays_excluded_after_index_reload(tmp_path):
    project = Path(__file__).resolve().parents[2]
    songpa_id = "songpa-rules:attachment:121237861"
    prepared = load_preprocessed_bundle(
        project / "data/handoff/jungeun/ordinance-handoff-2026-11-24",
        project_root=project,
        version="remapped",
        identities={
            songpa_id: "local-annex",
            "seodaemun-ordinance:attachment:160319457": songpa_id,
        },
    )
    rows = {
        "local-annex": {"table-2/row[3]", "table-3/row[3]"},
        songpa_id: {"table-2/row[1]"},
    }
    documents = [d for d in prepared.documents if d.document_id in rows]
    chunks = [
        chunk
        for chunk in chunk_preprocessed_documents(documents)
        if chunk.source_location in rows[chunk.source_document_id]
    ]
    assert {
        (c.source_document_id, c.source_location, c.content_format) for c in chunks
    } == {
        (source_id, location, fmt)
        for source_id, locations in rows.items()
        for location in locations
        for fmt in ("html", "json")
    }

    embedder = DemoHashEmbeddings()
    path = tmp_path / "index.json"
    save_index(build_index(chunks, embedder), path)
    index = load_index(path)
    for district, query, allowed_row in (
        ("송파구", "별표", "table-3/row[3]"),
        ("서대문구", "생활폐기물용", "table-2/row[1]"),
    ):
        expected = {c.chunk_id for c in chunks if c.source_location == allowed_row}
        for candidates in (
            vector_search(index, embedder.embed_query(query), district, len(chunks)),
            bm25_search(index, query, district, len(chunks)),
        ):
            assert {c.chunk.chunk_id for c in candidates} == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://example.org/flDownload.do?gubun=ELIS&flSeq=121237861",
        "https://www.law.go.kr/flDownload.do?gubun=ELIS&flSeq=121237862",
        "https://www.law.go.kr/ordinInfoP.do?gubun=ELIS&flSeq=121237861",
        "https://www.law.go.kr/flDownload.do?gubun=LAW&flSeq=121237861",
        "https://[invalid",
    ],
)
def test_other_sources_can_use_the_same_table_location(url):
    other = make_chunk("other", "district", ["송파구"], "다른 표").model_copy(
        update={"source_url": url, "source_location": "table-2/row[3]"}
    )
    assert is_searchable(other, "송파구")


# --- tokenize (BM25용 2글자 조각) -------------------------------------------


def test_tokenize_splits_words_into_bigrams_and_keeps_single_letters():
    # "페트병은" → 페트·트병·병은, 1글자 "캔"은 그대로, 문장부호는 버린다.
    assert tokenize("페트병은 캔?") == ["페트", "트병", "병은", "캔"]


def test_tokenize_shares_bigrams_when_particle_differs():
    # 조사가 달라도("은" / "을") 핵심 조각 "페트", "트병"을 공유한다.
    assert {"페트", "트병"} <= set(tokenize("페트병을"))


def test_html_tags_are_removed_by_chunk_text_before_tokenize():
    # HTML 청크의 태그 이름·속성은 본문이 아니므로 chunk_text가 먼저 지운다.
    chunk = make_chunk(
        "html", "district", ["서대문구"], '<p data-x="y">캔 &amp; 병</p>'
    )
    assert tokenize(chunk_text(chunk)) == ["캔", "병"]


def test_tokenize_keeps_angle_bracket_text_from_plain_body():
    # 정은님 리뷰: 본문의 "<개정 2011. 8. 10.>"이 태그로 오해받아 사라지면 안 된다.
    # "2011"은 2글자 조각 "20", "01", "11"로 쪼개진다
    assert {"개정", "20", "01", "11"} <= set(tokenize("제1장 총칙 <개정 2011. 8. 10.>"))


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


def json_table_chunk(chunk_id: str, row_number: int, cells: list[str]) -> Chunk:
    """청킹 결과와 같은 모양의 JSON 표 행 청크. 셀마다 cell_id·위치 같은 구조 정보가 붙는다."""

    def cell(row: int, col: int, text: str) -> dict:
        return {
            "cell_id": f"table-1-r{row}-c{col}",
            "colspan": 1,
            "inherited_from_previous_row": False,
            "origin_col": col,
            "origin_row": row,
            "rowspan": 1,
            "text": text,
        }

    headers = ["품목", "규격", "금액"]
    content = {
        "header_rows": [
            {"cells": [cell(0, c, t) for c, t in enumerate(headers)], "row": 0}
        ],
        "paragraphs": ["〔별표 1〕 수수료 기준\n", ""],
        "row": {
            "cells": [cell(row_number, c, t) for c, t in enumerate(cells)],
            "row": row_number,
        },
        "section_title": "〔별표 1〕 수수료 기준",
        "table_id": "table-1",
    }
    chunk = make_chunk(chunk_id, "district", ["서대문구"], "-")
    return chunk.model_copy(
        update={
            "content_format": "json",
            "content": json.dumps(content, ensure_ascii=False),
        }
    )


def test_chunk_text_puts_row_cells_with_headers_first_and_drops_structure():
    text = chunk_text(json_table_chunk("bag", 3, ["종량제 봉투", "10L", "250원"]))

    assert text.splitlines()[0] == "품목: 종량제 봉투 | 규격: 10L | 금액: 250원"
    assert "〔별표 1〕 수수료 기준" in text
    assert text.count("〔별표 1〕 수수료 기준") == 1  # 제목·문단 중복은 한 번만
    assert "cell_id" not in text and "table-1" not in text


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        # JSON이 아니면 원문 그대로
        ("JSON 아님", "JSON 아님"),
        # 목록 JSON: 글자만 (숫자·true 제외)
        ('["캔", 1, true]', "캔"),
        # 표가 아닌 문단 청크: 구조 키(unit_type)와 숫자는 빼고 글자만
        ('{"text": "제1장 총칙", "unit_type": "heading", "number": 1}', "제1장 총칙"),
        # 여러 열을 합친 머리글(colspan)은 모든 열에 붙고, 빈 셀·빈 머리글은 건너뛴다
        (
            json.dumps(
                {
                    "header_rows": [
                        {
                            "cells": [
                                {"origin_col": 0, "colspan": 2, "text": "품목"},
                                {"origin_col": 2, "colspan": 1, "text": ""},
                            ]
                        }
                    ],
                    "row": {
                        "cells": [
                            {"origin_col": 0, "text": "장롱"},
                            {"origin_col": 1, "text": ""},
                            {"origin_col": 2, "text": "10,000"},
                        ]
                    },
                },
                ensure_ascii=False,
            ),
            "품목: 장롱 | 10,000",
        ),
        # 행 없이 머리글만 있으면 머리글 글자도 본문으로 남긴다
        (
            '{"header_rows": [{"cells": [{"text": "품목"}]}], "paragraphs": ["문단"]}',
            "품목\n문단",
        ),
    ],
)
def test_chunk_text_handles_other_json_shapes(content, expected):
    chunk = make_chunk("x", "district", ["서대문구"], "-").model_copy(
        update={"content_format": "json", "content": content}
    )
    assert chunk_text(chunk) == expected


def test_bm25_finds_amendment_note_in_json_paragraph():
    # JSON 문단의 "<개정 ...>"을 검색할 수 있어야 한다 (예전엔 tokenize가 태그로 지웠다).
    chunk = make_chunk("article", "district", ["서대문구"], "-").model_copy(
        update={
            "content_format": "json",
            "content": '{"text": "제1장 총칙 <개정 2011. 8. 10.>", "unit_type": "heading"}',
        }
    )
    index = build_index([chunk], DemoHashEmbeddings(4))

    results = bm25_search(index, "개정", "서대문구", top_k=5)

    assert [r.chunk.chunk_id for r in results] == ["article"]


def test_unexpected_table_shape_falls_back_to_plain_json_text():
    # 정은님 리뷰: header_rows가 문자열 목록이면 셀 전용 추출에서 .get() 오류로 B·C가 멈췄다.
    # 팀 표 모양이 아니면 글자 값만 모으는 일반 추출로 넘긴다.
    chunk = make_chunk("odd", "district", ["서대문구"], "-").model_copy(
        update={
            "content_format": "json",
            "content": json.dumps(
                {
                    "header_rows": ["품목", "규격"],
                    "row": {"cells": [{"text": "장롱"}, {"text": "120cm 이하"}]},
                },
                ensure_ascii=False,
            ),
        }
    )
    assert chunk_text(chunk) == "품목\n규격\n장롱\n120cm 이하"

    index = build_index([chunk], DemoHashEmbeddings(4))
    results = bm25_search(index, "장롱", "서대문구", top_k=5)
    assert [r.chunk.chunk_id for r in results] == ["odd"]


def test_bm25_does_not_match_json_row_numbers():
    # 행 번호가 10인 종이 청크가 "10L" 질문에 걸리면 안 된다 (row: 10은 본문이 아님).
    paper = json_table_chunk("paper-row-10", 10, ["종이", "신문지", "묶어서"])
    bag = json_table_chunk("bag-10l", 3, ["종량제 봉투", "10L", "250원"])
    index = build_index([paper, bag], DemoHashEmbeddings(4))

    results = bm25_search(index, "10L", "서대문구", top_k=5)

    assert [r.chunk.chunk_id for r in results] == ["bag-10l"]


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
    # 없는 검색 방식(Z), 재정렬기 없이 요청한 C는 빈 결과가 아니라 설정 오류로 알린다.
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


# --- rerank / C 검색 (재정렬기는 가짜) --------------------------------------


def prefer(*chunk_ids: str):
    """주어진 chunk_id 순서대로 높은 점수를 주는 가짜 재정렬기. 나머지는 0점."""

    def reranker(query: str, candidates: list[SearchCandidate]) -> list[float]:
        return [
            float(len(chunk_ids) - chunk_ids.index(c.chunk.chunk_id))
            if c.chunk.chunk_id in chunk_ids
            else 0.0
            for c in candidates
        ]

    return reranker


def test_rerank_reorders_by_reranker_score_and_keeps_stage_scores():
    candidates = rrf_merge({"vector": ranked("x", "y", "z")}, top_k=5)

    results = rerank("질문", candidates, prefer("z", "x"), top_k=2)

    assert [r.chunk.chunk_id for r in results] == ["z", "x"]
    assert [r.rank for r in results] == [1, 2]
    # 이전 단계 점수는 남고 rerank 점수가 더해진다.
    assert {"vector", "rrf", "rerank"} <= set(results[0].stage_scores)
    assert results[0].score == results[0].stage_scores["rerank"] == 2.0


def test_rerank_rejects_wrong_number_of_scores():
    candidates = rrf_merge({"vector": ranked("x", "y")}, top_k=5)

    with pytest.raises(RerankerOutputError) as caught:
        rerank("질문", candidates, lambda q, c: [1.0], top_k=5)
    assert caught.value.code == "retrieval.invalid_rerank_scores"


def test_rerank_returns_empty_without_calling_reranker_for_no_candidates():
    def must_not_call(query, candidates):
        raise AssertionError("후보가 없으면 재정렬기를 부르지 않는다")

    assert rerank("질문", [], must_not_call, top_k=5) == []


def test_retriever_runs_variant_c_with_injected_reranker():
    # C = B 후보를 재정렬기로 다시 줄 세운 결과. 재정렬기가 종이팩을 1위로 올린다.
    retrieve = make_vector_retriever(
        make_index(), FakeEmbedder(), reranker=prefer("seodaemun-carton")
    )
    query = ResolvedQuery(search_query="서대문 페트병", district="서대문구")

    results = retrieve(query, variant="C", top_k=2)

    assert results[0].chunk.chunk_id == "seodaemun-carton"
    assert len(results) == 2
    assert {"vector", "rrf", "rerank"} <= set(results[0].stage_scores)


def test_rrf_merge_skips_missing_stage_score():
    # score가 없는 후보(None)도 순위로는 합치고, 단계 점수에는 숫자만 남긴다.
    no_score = [
        SearchCandidate(
            chunk=make_chunk("x", "district", ["서대문구"], "x"), rank=1, score=None
        )
    ]
    merged = rrf_merge({"vector": no_score}, top_k=5)

    assert merged[0].stage_scores == {"rrf": pytest.approx(1 / 61)}


def test_rerank_breaks_ties_by_previous_rank():
    # 재정렬 점수가 모두 같으면 chunk_id 순이 아니라 이전 단계(B) 순위를 유지한다.
    candidates = rrf_merge({"vector": ranked("zz", "aa")}, top_k=5)  # zz 1위, aa 2위

    results = rerank("질문", candidates, lambda q, c: [10.0, 10.0], top_k=2)

    assert [r.chunk.chunk_id for r in results] == ["zz", "aa"]
