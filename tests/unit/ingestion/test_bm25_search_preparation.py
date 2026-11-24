"""실제 팀 검색기와 구분한 합성 토큰화·BM25 예시 검사."""

import re

from rank_bm25 import BM25Okapi

from src.ingestion.search_preparation import normalize_search_text


def test_known_term_restoration_can_match_toy_bm25_query():
    raw = "무색 폴리\n   에틸렌테레프\n   탈레이트 (PET)병"
    corpus = [raw, "신문지 종이류 배출", "유리병 색상별 배출"]

    def tokenize(text):
        return re.findall(r"[가-힣]+|[A-Za-z]+", text)

    query = tokenize("폴리에틸렌테레프탈레이트")
    before = BM25Okapi([tokenize(text) for text in corpus])
    after = BM25Okapi(
        [tokenize(normalize_search_text(text)["text"]) for text in corpus]
    )
    assert before.get_scores(query)[0] == 0
    assert after.get_scores(query)[0] > 0
    assert after.get_scores(query)[0] > after.get_scores(query)[1]
    assert corpus[0] == raw
