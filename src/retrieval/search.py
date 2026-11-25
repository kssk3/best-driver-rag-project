"""A/B/C 검색.

담당: 이명지
상태: A(Vector 단독)와 B(Vector + BM25, RRF)를 파이프라인 retriever 규격으로 구현했다.
C(B + reranker)는 다음 단계에서 추가한다.

흐름 (A):
    질문 → 임베딩 벡터 → 지역 필터(선택한 구 + 공통 문서) → 코사인 유사도 → 상위 k개
흐름 (B):
    A 상위 20개 + BM25(2글자 조각) 상위 20개 → RRF로 순위 합치기 → 상위 k개
"""

import html
import math
import re
from collections.abc import Callable

from rank_bm25 import BM25Plus

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


# 검색에서 빼는 원문 위치: (문서 ID, 위치 접두어).
# chunk_id는 청킹이 바뀌면 달라지므로 재청킹해도 유지되는 원문 위치로 지정한다.
EXCLUDED_SOURCES: tuple[tuple[str, str], ...] = (
    # 송파구 시행규칙 [별표 4] 쓰레기 배출 일시 및 장소 (2017.4.6. 개정)의 동별 배출 요일표.
    # 구청 웹 안내·지도와 요일이 달라 현재 일정으로 확인되지 않음(docs/jungeun/README.md
    # '사람 검수와 현재 제한'). 이 표만 보고 요일을 확정하지 않도록 검색에서 뺀다.
    # 현재 요일이 확정된 자료가 들어오면 이 항목을 지우고 다시 확인한다.
    ("songpa-rules:attachment:121237861", "table-2/"),
)


def is_excluded(chunk: Chunk) -> bool:
    """검색에서 빼기로 한 원문 위치(EXCLUDED_SOURCES)의 청크인지."""
    return any(
        chunk.source_document_id == document_id
        and chunk.source_location.startswith(location_prefix)
        for document_id, location_prefix in EXCLUDED_SOURCES
    )


def is_searchable(chunk: Chunk, district: str | None) -> bool:
    """검색 대상인지: 지역 필터를 통과하고 제외 목록에 없어야 한다. A·BM25가 함께 쓴다."""
    return is_in_region(chunk, district) and not is_excluded(chunk)


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
        if not is_searchable(entry.chunk, district):
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


# --- B 검색 재료: BM25(글자 일치) ---------------------------------------------

_TAG = re.compile(r"<[^>]+>")  # HTML 태그 <section ...>, <p> 등
_WORD = re.compile(r"[^\W_]+")  # 글자·숫자 덩어리 (문장부호·공백·밑줄에서 끊음)


def tokenize(text: str) -> list[str]:
    """BM25용으로 글을 2글자 조각(bigram)으로 쪼갠다.

    한국어는 조사가 붙어("페트병은", "페트병을") 띄어쓰기 단위로 비교하면 같은 단어를
    다른 단어로 본다. 2글자 조각으로 쪼개면 "페트", "트병"을 공유해 조사가 달라도 맞는다.
    1글자 단어("캔")는 조각이 안 나오므로 그대로 넣는다.
    HTML 청크의 태그는 본문이 아니므로 먼저 지운다.
    """

    # html 청크의 태그 지우기
    plain = html.unescape(_TAG.sub(" ", text)).lower()
    tokens: list[str] = []
    # 단어로 나누기
    for word in _WORD.findall(plain):
        # 1. 1글자는 그대로
        if len(word) == 1:
            tokens.append(word)
        # 2. 2글자씩 미끄러지며 자르기
        else:
            tokens.extend(word[i : i + 2] for i in range(len(word) - 1))
    return tokens


def bm25_search(
    index: IndexSnapshot,
    query: str,
    district: str | None,
    top_k: int,
) -> list[SearchCandidate]:
    """BM25 검색: 지역 필터를 통과한 청크를 질문과 겹치는 2글자 조각이 많은 순으로 top_k개.

    질문과 겹치는 조각이 하나도 없는 청크는 '글자로 맞은 문서'가 아니므로 뺀다.
    그래서 결과가 top_k개보다 적을 수 있다.

    BM25Okapi 대신 BM25Plus를 쓴다. Okapi는 절반 넘는 문서에 나오는 조각의 가중치(IDF)가
    음수가 되어, 같은 구 이름처럼 흔한 조각만 겹치면 점수가 음수로 뒤집힌다.
    Plus는 가중치가 항상 양수지만 겹치지 않아도 작은 기본 점수를 주므로, 겹침은 따로 검사한다.

    Raises:
        RetrievalError: top_k가 1보다 작을 때.

    흐름 한눈에:
    지역 필터 → 질문 자르기 → 문서 자르기 → BM25 점수 → 겹친 것만 → 정렬 → 상위 k개 포장
    ②          ③            ⑤         ⑥         ⑧      ⑨        ⑩
    """

    # ① "상위 0개" 같은 말 안 되는 요청은 빈 결과로 숨기지 않고 오류로 알림 (A와 같은 규칙)
    if top_k < 1:
        raise RetrievalError("top_k는 1 이상이어야 합니다.")

    # ② 색인 전체에서 "서대문구 문서 + 공통 문서"만 남김 (송파·지역 미확인 제외)
    #    → [서대문 페트병, 서대문 종이팩, 공통 페트병]
    chunks = [e.chunk for e in index.entries if is_searchable(e.chunk, district)]

    # ③ 질문을 2글자 조각으로: "종이팩" → ["종이", "이팩"]
    query_tokens = tokenize(query)
    # ④ 찾을 문서가 없거나(지역에 문서 0개), 질문에 글자가 없으면("?!") 바로 빈 결과
    if not chunks or not query_tokens:
        return []

    # 지역마다 대상 청크가 달라 질문마다 만든다. 청크 수가 수백 개라 충분히 빠르다.
    # ⑤ 문서들도 전부 조각으로 자름 (corpus = "문서 묶음"이라는 뜻)
    #    → [["서대","대문","페트","트병"], ["서대","대문","종이","이팩"], ["공통","페트","트병"]]
    corpus = [tokenize(chunk.content) for chunk in chunks]
    # ⑥ BM25Plus에 문서 묶음을 넣어 계산기를 만들고, 질문 조각으로 문서마다 점수를 매김
    #    → [2.77, 5.44, 2.77]  (문서 순서 그대로)
    scores = BM25Plus(corpus).get_scores(query_tokens)

    # ⑦ 질문 조각을 집합으로: {"종이", "이팩"}  (겹침 검사를 빠르게 하려고)
    query_set = set(query_tokens)
    # ⑧ zip = 점수·문서·조각을 같은 순서끼리 한 줄로 묶음
    #      (2.77, 서대문 페트병, [서대·대문·페트·트병])
    #      (5.44, 서대문 종이팩, [서대·대문·종이·이팩])
    #      (2.77, 공통 페트병,   [공통·페트·트병])
    #    if 교집합이 있으면만 남김 → 서대문 종이팩만 통과 ({"종이","이팩"} 겹침)
    #    → [(5.44, 서대문 종이팩)]
    #    float(): BM25 라이브러리가 numpy 숫자를 줘서 보통 숫자로 바꿈
    scored = [
        (float(score), chunk)
        for score, chunk, tokens in zip(scores, chunks, corpus)
        if query_set & set(tokens)  # 질문과 겹치는 조각이 있는 청크만
    ]

    # ⑨ 점수 높은 순 (마이너스를 붙여 내림차순), 점수가 같으면 chunk_id 순
    #    → 실행할 때마다 순서가 같게 (A와 같은 규칙)
    #       순서가 실행마다 바뀌면 Hit@k 점수와 테스트가 코드와 상관없이 바뀔 수 있음(비교, 재현에 영향)
    #       chunk_id는 문서마다 고유하고 안바뀌는 값이므로 동점이어도 항상 같은 순서
    scored.sort(key=lambda item: (-item[0], item[1].chunk_id))
    # ⑩ 앞에서 top_k개만 잘라서, 1위부터 번호를 붙여 파이프라인 규격(SearchCandidate)으로 포장
    #    enumerate(..., start=1) → 1, 2, 3 ... 순위 번호
    #    stage_scores={"bm25": ...} → 나중에 RRF·화면에서 "BM25 단계 점수"를 볼 수 있게 기록
    return [
        SearchCandidate(
            chunk=chunk, rank=rank, score=score, stage_scores={"bm25": score}
        )
        for rank, (score, chunk) in enumerate(scored[:top_k], start=1)
    ]


# --- B 검색: A(Vector) + BM25를 RRF로 합치기 ---------------------------------

# RRF 상수. 순위 점수 1/(RRF_K + 순위)에서 1위와 2위의 차이를 완만하게 만든다.
# 원 논문(Cormack et al., 2009)과 LangChain EnsembleRetriever의 기본값 60을 쓴다.
RRF_K = 60

# 합치기 전에 A와 BM25에서 각각 가져올 후보 수. 한쪽에서 6위 이하인 문서도
# 다른 쪽에서 높으면 최종 top_k에 들어올 수 있도록 top_k보다 넉넉히 본다.
HYBRID_DEPTH = 20


class RetrievalVariantError(ApplicationError, ValueError):
    """지원하지 않는 검색 방식(variant)을 요청함. 실행 설정 문제다."""

    code = "retrieval.unsupported_variant"
    category = ErrorCategory.CONFIGURATION


def rrf_merge(
    ranked_lists: dict[str, list[SearchCandidate]], top_k: int, k: int = RRF_K
) -> list[SearchCandidate]:
    """여러 검색 결과를 순위 기준(RRF)으로 합친다.

    문서마다 각 목록에서의 순위로 1/(k + 순위)를 구해 더한다. 점수 단위가 다른
    검색(코사인 유사도 0~1, BM25 0~수십)을 그대로 더할 수 없어 '몇 위였나'만 쓴다.
    한 목록에만 있는 문서는 그 목록의 점수만 받는다. 양쪽 모두 높은 문서가 위로 온다.

    stage_scores에는 각 단계의 원래 점수와 합친 rrf 점수를 함께 남긴다.

    Raises:
        RetrievalError: top_k가 1보다 작을 때.

    흐름 한눈에:
    빈 장부 준비 → 목록마다 → 후보마다 순위 점수 누적 + 원래 점수 기록 → 합계로 정렬 → 상위 k개 포장
    ②            ③           ④ ⑤ ⑥ ⑦                                  ⑧           ⑨ ⑩
    """

    # ① "상위 0개" 같은 잘못된 요청은 오류로 (A, BM25와 같은 규칙)
    if top_k < 1:
        raise RetrievalError("top_k는 1 이상이어야 합니다.")

    # ② 빈 장부 3개 준비. 모두 chunk_id를 키로 써서 "같은 문서"를 하나로 모은다.
    rrf_scores: dict[str, float] = {}
    chunks: dict[str, Chunk] = {}
    stage_scores: dict[str, dict[str, float]] = {}

    # ③ 목록을 하나씩: 처음엔 stage="vector", 다음엔 stage="bm25"
    for stage, candidates in ranked_lists.items():
        # ④ 그 목록 안의 후보를 하나씩
        for candidate in candidates:
            chunk_id = candidate.chunk.chunk_id
            # ⑤ 핵심 한 줄: "지금까지 점수 + 이번 목록에서의 순위 점수"
            #    .get(chunk_id, 0.0) = 처음 보는 문서면 0에서 시작
            #    vector 돌 때: x = 0 + 1/61,  y = 0 + 1/62
            #    bm25   돌 때: y = 1/62 + 1/61  ← 두 번째로 만나서 누적됨
            rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0.0) + 1 / (
                k + candidate.rank
            )
            # ⑥ 청크 본체 저장 (같은 문서는 덮어써도 같은 내용)
            chunks[chunk_id] = candidate.chunk
            # ⑦ 단계별 원래 점수 기록
            #    setdefault = "없으면 빈 dict를 만들고, 그 dict를 돌려줘"
            #    → x: {"vector": 0.9}
            #    → y: {"vector": 0.8, "bm25": 12}
            stage_scores.setdefault(chunk_id, {})[stage] = candidate.score

    # ⑧ chunk_id들을 RRF 점수 높은 순으로 정렬, 동점이면 chunk_id 순 (재현성)
    #    y = 1/62 + 1/61 = 0.0325,  x = 1/61 = 0.0164  →  ["y", "x"]
    ordered = sorted(rrf_scores, key=lambda cid: (-rrf_scores[cid], cid))
    return [
        SearchCandidate(
            chunk=chunks[cid],  # ⑥에서 저장한 청크
            rank=rank,  # 새 순위 1, 2, 3...
            score=rrf_scores[cid],  # 최종 점수 = RRF 점수
            # ⑨ {**a, "rrf": ...} = a의 내용을 펼쳐서 복사하고 "rrf"를 하나 더 추가
            #   원본 a는 안바뀜
            #    y: {"vector": 0.8, "bm25": 12, "rrf": 0.0325}
            stage_scores={**stage_scores[cid], "rrf": rrf_scores[cid]},
        )
        # ⑩ 앞에서 top_k개만 잘라서 1위부터 번호 붙이기
        for rank, cid in enumerate(ordered[:top_k], start=1)
    ]


# --- C 검색: B 후보를 재정렬기로 다시 줄 세우기 --------------------------------

# 재정렬기: (질문, 후보 목록) → 후보마다 관련도 점수(클수록 관련 있음), 후보와 같은 순서·개수.
# 어떤 모델을 쓸지는 아직 정하지 않았으므로 밖에서 넘겨받는다(의존성 주입).
# 실제 모델(cross-encoder, LLM 등)은 이 모양의 함수만 만들면 끼울 수 있다.
Reranker = Callable[[str, list[SearchCandidate]], list[float]]


class RerankerOutputError(ApplicationError, ValueError):
    """재정렬기가 후보 수와 다른 개수의 점수를 돌려줌. 어느 점수가 어느 후보인지 알 수 없다."""

    code = "retrieval.invalid_rerank_scores"
    category = ErrorCategory.CONTRACT_VIOLATION


def rerank(
    query: str,
    candidates: list[SearchCandidate],
    reranker: Reranker,
    top_k: int,
) -> list[SearchCandidate]:
    """재정렬기 점수로 후보를 다시 줄 세워 top_k개를 돌려준다.

    이전 단계 점수(vector, bm25, rrf)는 stage_scores에 남기고 "rerank" 점수를 더한다.
    점수가 같으면 chunk_id 순으로 정해 실행할 때마다 순서가 같게 한다.

    Raises:
        RetrievalError: top_k가 1보다 작을 때.
        RerankerOutputError: 재정렬기 점수 개수가 후보 수와 다를 때.
    """
    if top_k < 1:
        raise RetrievalError("top_k는 1 이상이어야 합니다.")
    if not candidates:
        return []

    scores = reranker(query, candidates)
    if len(scores) != len(candidates):
        raise RerankerOutputError(
            f"재정렬 점수 {len(scores)}개가 후보 {len(candidates)}개와 다릅니다."
        )

    paired = sorted(
        zip(scores, candidates), key=lambda item: (-item[0], item[1].chunk.chunk_id)
    )
    return [
        SearchCandidate(
            chunk=candidate.chunk,
            rank=rank,
            score=float(score),
            stage_scores={**candidate.stage_scores, "rerank": float(score)},
        )
        for rank, (score, candidate) in enumerate(paired[:top_k], start=1)
    ]


def make_vector_retriever(
    index: IndexSnapshot,
    embedder: EmbeddingProvider,
    reranker: Reranker | None = None,
) -> Retriever:
    """파이프라인 retriever 규격 `(ResolvedQuery, *, variant, top_k)`에 맞춘 검색을 만든다.

    - variant "A": Vector 단독
    - variant "B": Vector + BM25를 RRF로 합침 (각각 HYBRID_DEPTH개씩 본 뒤 top_k개)
    - variant "C": B 후보 HYBRID_DEPTH개를 재정렬기로 다시 줄 세워 top_k개.
      재정렬기를 넘기지 않았으면 C를 쓸 수 없다 → RetrievalVariantError
    - 그 밖: RetrievalVariantError

    색인을 만든 임베딩과 다른 임베딩으로 질문을 바꾸면 벡터를 비교할 수 없어 처음에 막는다.
    """
    if embedder.identity != index.metadata.embedding_identity:
        raise RetrievalConfigError("질문 임베딩이 색인을 만든 임베딩과 다릅니다.")

    def retrieve(
        query: ResolvedQuery, *, variant: str, top_k: int
    ) -> list[SearchCandidate]:
        # 빈 목록을 돌려주면 "근거 없음"으로 오해되므로 오류로 알린다.
        if variant not in ("A", "B", "C"):
            raise RetrievalVariantError(f"지원하지 않는 검색 방식입니다: {variant!r}")
        if variant == "C" and reranker is None:
            raise RetrievalVariantError("C 검색에 쓸 재정렬기가 설정되지 않았습니다.")

        query_vector = embedder.embed_query(query.search_query)
        if variant == "A":
            return vector_search(index, query_vector, query.district, top_k)

        depth = max(top_k, HYBRID_DEPTH)
        hybrid = rrf_merge(
            {
                "vector": vector_search(index, query_vector, query.district, depth),
                "bm25": bm25_search(index, query.search_query, query.district, depth),
            },
            # B는 top_k개만, C는 재정렬할 후보를 넉넉히(depth개) 받는다.
            top_k if variant == "B" else depth,
        )
        if variant == "B":
            return hybrid
        assert reranker is not None  # 위에서 확인함 (타입 검사기용)
        return rerank(query.search_query, hybrid, reranker, top_k)

    return retrieve
