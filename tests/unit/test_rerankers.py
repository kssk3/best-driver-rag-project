"""LLM 재정렬기 단위 테스트. 실제 모델 대신 정해진 답을 돌려주는 가짜 채팅 모델을 쓴다."""

import json

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

import src.retrieval.rerankers as rerankers
from src.contracts import Chunk, SearchCandidate
from src.infrastructure.chat_models import ModelOutputError
from src.retrieval.rerankers import (
    MAX_PASSAGE_CHARS,
    make_llm_reranker,
    make_openai_reranker,
    passage_text,
)
from src.retrieval.search import RerankerOutputError, RetrievalError, rerank


def candidate(chunk_id: str, content: str, rank: int) -> SearchCandidate:
    chunk = Chunk(
        chunk_id=chunk_id,
        source_document_id=f"synthetic-{chunk_id}",
        source_document_version="v1",
        title="합성 안내",
        content_format="html",
        content=content,
        source_url="https://example.org/guide",
        source_location="합성 별표 1",
        scope_type="district",
        districts=["서대문구"],
        chunking_version="synthetic-v1",
    )
    return SearchCandidate(chunk=chunk, rank=rank, score=1.0)


CANDIDATES = [
    candidate("pet", "<p>페트병은 라벨을 떼고 &amp; 압착</p>", 1),
    candidate("carton", "<p>종이팩은 씻어서 말린 뒤</p>", 2),
]


def fake_chat(reply: str, seen: list | None = None):
    """정해진 reply를 돌려주고, 받은 메시지를 seen에 기록하는 가짜 채팅 모델."""

    def respond(messages):
        if seen is not None:
            seen.append(messages)
        return AIMessage(content=reply)

    return RunnableLambda(respond)


def test_llm_reranker_returns_model_scores_in_candidate_order():
    reranker = make_llm_reranker(fake_chat('{"scores": [3, 9]}'))
    assert reranker("종이팩 버리는 법", CANDIDATES) == [3.0, 9.0]


def test_llm_reranker_sends_question_and_plain_passages_as_data():
    seen: list = []
    reranker = make_llm_reranker(fake_chat('{"scores": [1, 1]}', seen))

    reranker("종이팩 버리는 법", CANDIDATES)

    (system, human) = seen[0]
    payload = json.loads(human[1])
    assert system[0] == "system"
    assert payload["question"] == "종이팩 버리는 법"
    # HTML 태그를 빼고 엔티티를 풀어 보낸다. 순서 번호(index)로 점수와 후보를 맞춘다.
    assert payload["passages"] == [
        {"index": 0, "text": "페트병은 라벨을 떼고 & 압착"},
        {"index": 1, "text": "종이팩은 씻어서 말린 뒤"},
    ]


def test_llm_reranker_truncates_long_passages():
    seen: list = []
    long = [candidate("long", "가" * (MAX_PASSAGE_CHARS + 500), 1)]
    make_llm_reranker(fake_chat('{"scores": [5]}', seen))("질문", long)

    payload = json.loads(seen[0][1][1])
    assert len(payload["passages"][0]["text"]) == MAX_PASSAGE_CHARS


def wardrobe_row(chunk_id: str, size: str, price: str) -> SearchCandidate:
    """송파 장롱 표처럼 머리글·문단이 길고 행마다 규격·금액만 다른 JSON 표 청크."""

    def cell(row: int, col: int, text: str) -> dict:
        return {
            "cell_id": f"table-1-r{row}-c{col}",
            "colspan": 1,
            "inherited_from_previous_row": True,
            "origin_col": col,
            "origin_row": row,
            "rowspan": 2,
            "text": text,
        }

    content = {
        "header_rows": [
            {
                "cells": [
                    cell(0, c, t) for c, t in enumerate(["품목", "규격", "금액"])
                ],
                "row": 0,
            }
        ],
        # 앞 1,200자를 다 차지할 만큼 긴 문단 (실제 별표의 제목·단위·주석)
        "paragraphs": ["대형폐기물 수집·운반 수수료 부과기준 (단위: 원)\n" * 40],
        "row": {
            "cells": [cell(62, c, t) for c, t in enumerate(["장롱", size, price])],
            "row": 62,
        },
        "table_id": "table-1",
    }
    base = candidate(chunk_id, "-", 1)
    chunk = base.chunk.model_copy(
        update={
            "content_format": "json",
            "content": json.dumps(content, ensure_ascii=False),
        }
    )
    return base.model_copy(update={"chunk": chunk})


def test_passage_keeps_json_row_size_and_price_within_limit():
    # 정은님 리뷰: 원문 JSON 앞 1,200자만 자르면 두 행이 똑같아져 규격·금액을 구분할 수 없었다.
    wide = passage_text(wardrobe_row("wide", "너비 100cm 이상(쪽당)", "15,000"))
    narrow = passage_text(wardrobe_row("narrow", "너비 100cm 미만(쪽당)", "10,000"))

    assert len(wide) <= MAX_PASSAGE_CHARS
    assert "너비 100cm 이상(쪽당)" in wide and "15,000" in wide
    assert "너비 100cm 미만(쪽당)" in narrow and "10,000" in narrow
    assert wide != narrow


@pytest.mark.parametrize(
    "reply",
    [
        "점수는 3, 9입니다",  # JSON이 아님
        '{"score": [3, 9]}',  # 키 이름이 다름
        '{"scores": ["3", "9"]}',  # 숫자가 아니라 문자열
        '{"scores": [3, 11]}',  # 0~10 범위 밖
        '{"scores": [3, true]}',  # bool은 점수가 아님
    ],
)
def test_llm_reranker_rejects_malformed_output(reply):
    reranker = make_llm_reranker(fake_chat(reply))
    with pytest.raises(ModelOutputError) as caught:
        reranker("질문", CANDIDATES)
    assert caught.value.code == "infrastructure.llm_invalid_output"


def test_wrong_score_count_is_caught_by_rerank():
    # 형식은 맞지만 개수가 다르면 어느 점수가 어느 후보인지 몰라 rerank가 막는다.
    reranker = make_llm_reranker(fake_chat('{"scores": [7]}'))
    with pytest.raises(RerankerOutputError):
        rerank("질문", CANDIDATES, reranker, top_k=5)


def test_rerank_with_llm_scores_reorders_candidates():
    reranker = make_llm_reranker(fake_chat('{"scores": [2, 8]}'))
    results = rerank("종이팩 버리는 법", CANDIDATES, reranker, top_k=2)

    assert [r.chunk.chunk_id for r in results] == ["carton", "pet"]
    assert results[0].stage_scores["rerank"] == 8.0


def test_rerank_rejects_non_positive_top_k():
    reranker = make_llm_reranker(fake_chat('{"scores": [1, 1]}'))
    with pytest.raises(RetrievalError):
        rerank("질문", CANDIDATES, reranker, top_k=0)


class FakeOpenAIChat:
    """create_chat_model 대신 쓰는 가짜 모델. bind()에 넘어온 옵션을 기록한다."""

    def __init__(self):
        self.bound_options = None

    def bind(self, **options):
        self.bound_options = options
        return fake_chat('{"scores": [1, 2]}')


@pytest.mark.parametrize(
    ("temperature", "expected_options"),
    [
        # 기본(None): temperature를 보내지 않는다. gpt-6-luna는 0을 거부(400)한다.
        (None, {"response_format": {"type": "json_object"}}),
        # 값을 주면 그대로 보낸다 (temperature를 지원하는 모델용).
        (0, {"response_format": {"type": "json_object"}, "temperature": 0}),
    ],
)
def test_openai_reranker_binds_json_format_and_optional_temperature(
    monkeypatch, temperature, expected_options
):
    # 진짜 OpenAI(키·네트워크·비용) 대신 가짜 모델을 만들도록 테스트 동안만 바꿔치기한다.
    fake = FakeOpenAIChat()
    created_with = []

    def fake_create_chat_model(settings):
        created_with.append(settings)
        return fake

    monkeypatch.setattr(rerankers, "create_chat_model", fake_create_chat_model)

    reranker = make_openai_reranker("gpt-6-luna", temperature=temperature)

    assert created_with[0].model == "gpt-6-luna"
    assert fake.bound_options == expected_options
    assert reranker("질문", CANDIDATES) == [1.0, 2.0]
