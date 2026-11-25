"""A/B/C 검색.

담당: 이명지
상태: A(Vector 단독) 검색을 파이프라인 retriever 규격으로 구현하는 단계.
B(BM25 + Vector, RRF)와 C(B + reranker)는 다음 단계에서 추가한다.

흐름 (A):
    질문 → 임베딩 벡터 → 지역 필터(선택한 구 + 공통 문서) → 코사인 유사도 → 상위 k개
"""

import math
from collections.abc import Callable

from src.common.errors import ApplicationError, ErrorCategory
from src.contracts import Chunk, ResolvedQuery, SearchCandidate
from src.infrastructure.embeddings import EmbeddingProvider
from src.infrastructure.stores import IndexSnapshot

Retriever = Callable[..., list[SearchCandidate]]


# top_k가 0 이하 혹은
# 질문 벡터 차원이 다를 때
# 즉 입력에서 잘못될 때 잡는 오류
class RetrievalError(ApplicationError, ValueError):
    code = "retrieval.invalid_query"
    category = ErrorCategory.INVALID_INPUT


# 임베딩과 색인이 다른 경우 (설정에 문제 있을 때) 잡는 오류
class RetrievalConfigError(RetrievalError):
    code = "retrieval.embedding_mismatch"
    category = ErrorCategory.CONFIGURATION


def is_in_region(chunk: Chunk, district: str | None) -> bool:
    """청크가 이 지역의 검색 대상인지 판단한다.

    - 공통 문서(scope_type="common")는 어느 구에서나 검색 대상이다.
    - 구 문서(scope_type="district")는 districts에 해당 구가 있을 때만 대상이다.
    - 적용 지역을 모르는 문서(scope_type="unknown")는 다른 구 규칙일 수 있어 제외한다.
    - 구를 모르면(district=None) 공통 문서만 대상이다.
    팀 규칙: district가 비었다고 공통으로 보지 않고 scope_type으로 판단한다.
    """

    if chunk.scope_type == "common":  # 공통 문서인지?
        return True
    if (
        chunk.scope_type == "district" and district in chunk.districts
    ):  # 이 구 문서인지?
        return True
    return False


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """두 벡터가 얼마나 같은 방향인지(-1 ~ 1). 클수록 뜻이 비슷하다.

    공식: (a·b) / (|a| × |b|)
      - a·b (내적) = 같은 자리끼리 곱해서 모두 더한 값
      - |a| (크기) = 각 값을 제곱해서 더한 뒤 제곱근
    크기가 0인 벡터는 방향이 없어 비교할 수 없으므로 0.0을 돌려준다.
    """
    dot = sum(x * y for x, y in zip(a, b))  # ① 내적: 같은 자리끼리 곱해서 더하기
    norm_a = math.sqrt(sum(x * x for x in a))  # ② a의 크기
    norm_b = math.sqrt(sum(y * y for y in b))  # ② b의 크기
    if norm_a == 0 or norm_b == 0:  # 크기 0이면 비교 불가
        return 0.0
    return dot / (norm_a * norm_b)  # ③ 점수 = 내적 ÷ (크기 × 크기)


def vector_search(
    index: IndexSnapshot,
    query_vector: list[float],
    district: str | None,
    top_k: int,
) -> list[SearchCandidate]:
    """A 검색: 지역 필터를 통과한 청크를 질문과의 코사인 유사도 순으로 top_k개 돌려준다.

    Raises:
        ValueError: 질문 벡터 차원이 색인과 다르거나 top_k가 1보다 작을 때.
            (오류를 빈 결과로 숨기지 않는다 → 파이프라인이 error로 기록)
    """
    if top_k < 1:
        raise RetrievalError("top_k는 1 이상이어야 합니다.")
    if len(query_vector) != index.metadata.dimension:
        raise RetrievalError("질문 벡터 차원이 색인과 다릅니다.")

    scored: list[tuple[float, Chunk]] = []
    for entry in index.entries:
        if not is_in_region(entry.chunk, district):
            continue
        scored.append((cosine_similarity(query_vector, entry.vector), entry.chunk))

    #   점수가 같으면 chunk_id 순으로 정렬해 실행할 때마다 순서가 같게 한다.
    scored.sort(key=lambda item: (-item[0], item[1].chunk_id))  # 점수 높은 순
    top = scored[:top_k]  # 앞에서 top_k개

    return [
        SearchCandidate(
            chunk=chunk, rank=rank, score=score, stage_scores={"vector": score}
        )
        for rank, (score, chunk) in enumerate(top, start=1)
    ]


def make_vector_retriever(
    index: IndexSnapshot, embedder: EmbeddingProvider
) -> Retriever:
    """파이프라인 retriever 규격 `(ResolvedQuery, *, variant, top_k)`에 맞춘 A 검색을 만든다.

    색인을 만든 임베딩과 다른 임베딩으로 질문을 바꾸면 벡터를 비교할 수 없어 처음에 막는다.
    """
    if embedder.identity != index.metadata.embedding_identity:
        raise RetrievalConfigError("질문 임베딩이 색인을 만든 임베딩과 다릅니다.")

    def retrieve(
        query: ResolvedQuery, *, variant: str, top_k: int
    ) -> list[SearchCandidate]:
        if variant != "A":
            # B/C는 아직 없다. 빈 목록을 돌려주면 "근거 없음"으로 오해되므로 오류로 알린다.
            raise NotImplementedError(f"검색 방식 {variant}는 아직 구현 전입니다.")
        query_vector = embedder.embed_query(query.search_query)
        return vector_search(index, query_vector, query.district, top_k)

    return retrieve
