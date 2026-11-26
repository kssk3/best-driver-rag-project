"""합성 자료로 공용 연결만 확인하는 데모. 실제 RAG 품질 평가에 사용하지 않는다."""

import re

from src.config import RuntimeSettings
from src.contracts import (
    GenerationResult,
    PipelineRequest,
    ResolvedQuery,
    SearchCandidate,
)
from src.infrastructure.embeddings import DemoHashEmbeddings
from src.infrastructure.stores import load_index
from src.runtime import create_runtime


def create_demo_pipeline(settings: RuntimeSettings):
    """로컬 해시 색인과 근거 인용 예시를 연결한다. 외부 모델은 호출하지 않는다."""
    if settings.pipeline.variant != "A":
        raise ValueError(
            "데모는 A 연결 형태만 제공합니다. 실제 B/C 검색 콜백을 연결해야 합니다."
        )
    index = load_index(settings.index_path)
    embedder = DemoHashEmbeddings(dimensions=index.metadata.dimension)
    if index.metadata.embedding_identity != embedder.identity:
        raise ValueError(
            "데모 임베더와 색인의 모델/설정이 다릅니다. --demo로 만든 색인을 지정하세요."
        )

    def resolver(request: PipelineRequest) -> ResolvedQuery:
        if request.district not in {"서대문구", "송파구"}:
            return ResolvedQuery(
                search_query=request.question,
                status="needs_clarification",
                clarification_question="서대문구와 송파구 중 어느 구의 안내가 필요한가요?",
            )
        if request.dong:
            return ResolvedQuery(
                search_query=request.question,
                district=request.district,
                status="needs_clarification",
                clarification_question="이 합성 데모는 동별 안내를 제공하지 않습니다.",
            )
        return ResolvedQuery(search_query=request.question, district=request.district)

    def retriever(
        query: ResolvedQuery, *, variant: str, top_k: int
    ) -> list[SearchCandidate]:
        if variant != "A":
            raise ValueError("실제 B/C 검색은 담당자 콜백을 연결해야 합니다.")
        vector = embedder.embed_query(query.search_query)
        tokens = re.findall(r"[A-Za-z0-9가-힣]{2,}", query.search_query.casefold())
        ranked = []
        for entry in index.entries:
            chunk = entry.chunk
            if chunk.scope_type == "unknown":
                continue
            if chunk.scope_type == "district" and query.district not in chunk.districts:
                continue
            # 해시 충돌을 의미상 유사함으로 오해하지 않도록 합성 예제는 명시적인 단어도 확인한다.
            # 이 제한과 해시 벡터는 실제 A 검색이나 성능 기준을 구현한 것이 아니다.
            if not any(token in chunk.content.casefold() for token in tokens):
                continue
            score = sum(a * b for a, b in zip(vector, entry.vector, strict=True))
            ranked.append((score, chunk))
        ranked.sort(key=lambda pair: (-pair[0], pair[1].chunk_id))
        return [
            SearchCandidate(
                chunk=chunk, rank=rank, score=score, stage_scores={"demo_hash": score}
            )
            for rank, (score, chunk) in enumerate(ranked[:top_k], 1)
        ]

    def generator(request, evidence):
        if not evidence:
            return GenerationResult(
                status="insufficient_evidence",
                answer="합성 데모에 해당 근거가 없습니다.",
            )
        first = evidence[0]
        return GenerationResult(
            status="answered",
            answer=f"[합성 데모: 모델 생성 아님]\n{first.content}",
            cited_chunk_ids=[first.chunk_id],
        )

    options = settings.pipeline.model_copy(deep=True)
    options.run_kind = "demo"
    options.versions.update(
        {
            "index": index.metadata.index_id,
            "embedding": index.metadata.embedding_identity,
            "chunking": index.metadata.chunking_version,
            "generation": "demo-quote-v1",
            "region": "demo-explicit-district-v1",
        }
    )
    if options.rewrite_enabled:
        options.versions["rewrite"] = "demo-whitespace-only-v1"
    runtime_settings = settings.model_copy(update={"pipeline": options}, deep=True)
    return create_runtime(
        runtime_settings,
        resolver=resolver,
        retriever=retriever,
        generator=generator,
        rewriter=lambda query: " ".join(query.search_query.split()),
    )
