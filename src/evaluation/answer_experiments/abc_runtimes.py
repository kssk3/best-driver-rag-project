"""같은 문항을 A/B/C 실검색과 리라이트 OFF로 비교하는 평가 팩토리."""

from hashlib import sha256
from typing import Literal

from src.config import RuntimeSettings
from src.evaluation.answer_experiments.answer_evaluation_runtimes import (
    _configured_model,
    _embedding_settings,
)
from src.generation.model_draft import SYSTEM_PROMPT, make_model_draft
from src.generation.pipeline_adapter import make_answer_generator
from src.infrastructure.embeddings import create_openai_embeddings
from src.infrastructure.stores import load_index
from src.pipeline import PipelineConfigurationError, RAGPipeline
from src.retrieval.regions import resolve_request
from src.retrieval.rerankers import (
    MAX_PASSAGE_CHARS,
    RERANK_SYSTEM_PROMPT,
    make_openai_reranker,
)
from src.retrieval.search import HYBRID_DEPTH, RRF_K, make_vector_retriever
from src.runtime import create_runtime


def create_abc_runtimes(settings: RuntimeSettings) -> dict[str, RAGPipeline]:
    """실행 설정의 생성 모델과 재정렬 모델을 사용해 세 독립 구성을 만든다."""
    base = settings.model_copy(deep=True)
    options = base.pipeline
    if options.rewrite_enabled or options.run_kind != "rag":
        raise PipelineConfigurationError(
            "A/B/C 비교에는 실검색(rag)과 리라이트 OFF가 필요합니다.",
            code="evaluation.unsupported_configuration",
        )
    model = _configured_model(base)
    versions = options.versions
    reranker_model = versions.pop("reranker_model", "").strip()
    if not reranker_model:
        raise PipelineConfigurationError(
            "pipeline.versions.reranker_model에 C 재정렬 모델 ID를 지정하세요.",
            code="evaluation.missing_reranker_model",
        )
    # OFF 실행에 다른 실험의 재정렬·리라이트 정보가 섞이지 않게 한다.
    for unused in ("reranker_prompt", "rewrite", "rewrite_catalog"):
        versions.pop(unused, None)

    index = load_index(base.index_path)
    embedding, dimensions = _embedding_settings(index.metadata.embedding_identity)
    embedder = create_openai_embeddings(embedding, dimensions)
    retrieve = make_vector_retriever(index, embedder)
    rerank = make_openai_reranker(reranker_model)
    retrieve_c = make_vector_retriever(index, embedder, reranker=rerank)
    generate = make_answer_generator(make_model_draft(model))
    versions.update(
        index=index.metadata.index_id,
        chunking=index.metadata.chunking_version,
        embedding=embedding,
        model=model,
        prompt=sha256(SYSTEM_PROMPT.encode()).hexdigest(),
    )
    depth = max(options.top_k, HYBRID_DEPTH)
    hybrid_policy = f"vector+bm25/rrf-v1(k={RRF_K},depth={depth})"
    policies = {
        "A": "vector-v1",
        "B": hybrid_policy,
        "C": f"{hybrid_policy}+llm-rerank-v1(passage_chars={MAX_PASSAGE_CHARS})",
    }
    pipelines: dict[str, RAGPipeline] = {}
    variants: tuple[Literal["A", "B", "C"], ...] = ("A", "B", "C")
    for variant in variants:
        config = base.model_copy(deep=True)
        config.pipeline.variant = variant
        config.pipeline.rewrite_enabled = False
        config.pipeline.run_kind = "rag"
        config.pipeline.versions["candidate_policy"] = policies[variant]
        if variant == "C":
            config.pipeline.versions.update(
                reranker_model=reranker_model,
                reranker_prompt=sha256(RERANK_SYSTEM_PROMPT.encode()).hexdigest(),
            )
        pipelines[variant] = create_runtime(
            config,
            resolver=resolve_request,
            retriever=retrieve_c if variant == "C" else retrieve,
            generator=generate,
        )
    return pipelines
