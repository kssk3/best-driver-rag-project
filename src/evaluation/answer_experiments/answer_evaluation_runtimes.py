import json
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path

from src.common.env import require_env
from src.common.errors import ApplicationError, ErrorCategory
from src.config import RuntimeSettings
from src.contracts import ResolvedQuery, SearchCandidate
from src.generation.model_draft import SYSTEM_PROMPT, make_model_draft
from src.generation.pipeline_adapter import make_answer_generator
from src.infrastructure.embeddings import create_openai_embeddings
from src.infrastructure.stores import load_index
from src.ingestion.preprocessed_bundle import load_preprocessed_bundle
from src.ingestion.preprocessed_chunking import chunk_preprocessed_documents
from src.pipeline import PipelineConfigurationError, RAGPipeline
from src.retrieval.regions import resolve_request
from src.retrieval.rerankers import (
    MAX_PASSAGE_CHARS,
    RERANK_SYSTEM_PROMPT,
    make_openai_reranker,
)
from src.retrieval.search import HYBRID_DEPTH, RRF_K, make_vector_retriever
from src.rewrite_dictionary import catalog
from src.rewrite_dictionary.runtime import (
    CATALOG_REWRITE_VERSION,
    make_catalog_rewriter,
)
from src.runtime import create_runtime


class MissingEvaluationModelError(ApplicationError, ValueError):
    code = "evaluation.missing_model"
    category = ErrorCategory.CONFIGURATION


def _configured_model(settings: RuntimeSettings) -> str:
    model = settings.pipeline.versions.get("model", "").strip()
    if not model:
        raise MissingEvaluationModelError(
            "실행 설정의 pipeline.versions.model에 모델 ID를 지정하세요."
        )
    return model


def _embedding_settings(raw_identity: str) -> tuple[str, int | None]:
    code = "evaluation.invalid_embedding_identity"
    try:
        identity = json.loads(raw_identity)
    except json.JSONDecodeError as error:
        raise PipelineConfigurationError(
            "색인의 임베딩 설정을 JSON으로 읽을 수 없습니다.", code=code
        ) from error
    if not isinstance(identity, dict) or identity.get("provider") != "openai":
        raise PipelineConfigurationError(
            "OpenAI 임베딩으로 만든 색인이 필요합니다.", code=code
        )
    model = identity.get("model")
    dimensions = identity.get("dimensions")
    if not isinstance(model, str) or not model.strip():
        raise PipelineConfigurationError(
            "색인에 임베딩 모델 ID가 필요합니다.", code=code
        )
    if dimensions is not None and (type(dimensions) is not int or dimensions < 1):
        raise PipelineConfigurationError(
            "색인의 임베딩 차원은 양의 정수여야 합니다.", code=code
        )
    return model, dimensions


def _a_runtime_factory(
    settings: RuntimeSettings, *, allow_rewrite: bool, allow_c: bool = False
) -> Callable[[bool], RAGPipeline]:
    """색인과 모델을 한 번 준비하고 실행별 리라이트 설정만 바꾼다.

    allow_c가 참이면 variant C(B 후보를 LLM으로 재정렬)도 받는다. 그때만 재정렬 모델이 필요하다.
    """
    config = settings.model_copy(deep=True)
    options = config.pipeline
    model = _configured_model(config)
    variants = ("A", "C") if allow_c else ("A",)
    if options.variant not in variants or (
        options.rewrite_enabled and not allow_rewrite
    ):
        raise PipelineConfigurationError(
            ("A 또는 C 검색으로 설정하세요." if allow_c else "A 검색으로 설정하세요.")
            if allow_rewrite
            else "A 검색과 리라이트 OFF로 설정하세요.",
            code="evaluation.unsupported_configuration",
        )
    reranker_model = options.versions.get("reranker_model", "").strip()
    if options.variant == "C" and not reranker_model:
        raise PipelineConfigurationError(
            "pipeline.versions.reranker_model에 C 재정렬 모델 ID를 지정하세요.",
            code="evaluation.missing_reranker_model",
        )

    index = load_index(config.index_path)
    embedding_model, dimensions = _embedding_settings(index.metadata.embedding_identity)
    require_env("OPENAI_API_KEY")
    embedder = create_openai_embeddings(embedding_model, dimensions)
    reranker = make_openai_reranker(reranker_model) if options.variant == "C" else None
    retrieve = make_vector_retriever(index, embedder, reranker=reranker)

    options.run_kind = "rag"
    for unused in (
        "candidate_policy",
        "reranker_model",
        "reranker_prompt",
        "rewrite",
        "rewrite_catalog",
    ):
        options.versions.pop(unused, None)
    options.versions.update(
        {
            "index": index.metadata.index_id,
            "chunking": index.metadata.chunking_version,
            "embedding": embedding_model,
            "model": model,
            "prompt": sha256(SYSTEM_PROMPT.encode()).hexdigest(),
        }
    )
    if options.variant == "C":
        # abc_runtimes.create_abc_runtimes의 C와 같은 후보 정책·재정렬 기록값이다.
        depth = max(options.top_k, HYBRID_DEPTH)
        options.versions.update(
            candidate_policy=(
                f"vector+bm25/rrf-v1(k={RRF_K},depth={depth})"
                f"+llm-rerank-v1(passage_chars={MAX_PASSAGE_CHARS})"
            ),
            reranker_model=reranker_model,
            reranker_prompt=sha256(RERANK_SYSTEM_PROMPT.encode()).hexdigest(),
        )
    generate = make_answer_generator(make_model_draft(model))

    def build(rewrite_enabled: bool) -> RAGPipeline:
        configured = config.model_copy(deep=True)
        pipeline = configured.pipeline
        pipeline.rewrite_enabled = rewrite_enabled
        rewriter = None
        if rewrite_enabled:
            rewriter = make_catalog_rewriter(catalog.CATALOG_PATH)
            pipeline.versions["rewrite"] = CATALOG_REWRITE_VERSION
            pipeline.versions["rewrite_catalog"] = sha256(
                catalog.CATALOG_PATH.read_bytes()
            ).hexdigest()
        return create_runtime(
            configured,
            resolver=resolve_request,
            retriever=retrieve,
            generator=generate,
            rewriter=rewriter,
        )

    return build


def create_a_runtime(settings: RuntimeSettings) -> RAGPipeline:
    """기존 팀 A 답변 평가에서 리라이트를 끈 구성을 유지한다."""
    return _a_runtime_factory(settings, allow_rewrite=False)(False)


def create_a_catalog_runtime(settings: RuntimeSettings) -> RAGPipeline:
    """설정한 팀 색인과 확장 사전을 실제 챗봇 검색에 연결한다. variant는 A 또는 C다."""
    return _a_runtime_factory(settings, allow_rewrite=True, allow_c=True)(
        settings.pipeline.rewrite_enabled
    )


def create_a_rewrite_comparison(settings: RuntimeSettings) -> dict[str, RAGPipeline]:
    """같은 팀 A 검색기와 답변 모델을 쓰는 리라이트 OFF/ON 두 실행을 반환한다."""
    build = _a_runtime_factory(settings, allow_rewrite=True)
    return {"rewrite-off": build(False), "rewrite-on": build(True)}


def create_fixed_evidence_runtime(
    settings: RuntimeSettings,
    candidates: list[SearchCandidate],
    *,
    replay_index: str | None = None,
) -> RAGPipeline:
    """Generate from supplied candidates and record their observed versions."""
    config = settings.model_copy(deep=True)
    model = _configured_model(config)
    options = config.pipeline
    options.run_kind = "fixed_evidence"
    versions = options.versions
    versions.update(model=model, prompt=sha256(SYSTEM_PROMPT.encode()).hexdigest())
    for key in ("index", "embedding", "replay_index"):
        versions.pop(key, None)
    if isinstance(replay_index, str) and replay_index.strip():
        versions["replay_index"] = replay_index

    for key, observed in (
        ("data", {c.chunk.source_document_version for c in candidates}),
        ("chunking", {c.chunk.chunking_version for c in candidates}),
    ):
        versions.pop(key, None)
        versions.pop(f"{key}_versions", None)
        if len(observed) == 1:
            versions[key] = observed.pop()
        elif observed:
            versions[f"{key}_versions"] = json.dumps(
                sorted(observed), ensure_ascii=False
            )

    return create_runtime(
        config,
        resolver=lambda request: ResolvedQuery(
            search_query=request.question, district=request.district, dong=request.dong
        ),
        retriever=lambda *_args, **_kwargs: candidates,
        generator=make_answer_generator(make_model_draft(model)),
    )


def create_color_runtime(settings: RuntimeSettings) -> RAGPipeline:
    project = Path(__file__).resolve().parents[3]
    bundle = load_preprocessed_bundle(
        project / "data/handoff/jungeun/ordinance-handoff-2026-11-24",
        project_root=project,
        version="v1",
    )
    documents = [
        doc
        for doc in bundle.documents
        if doc.document_id == "seodaemun-rules:attachment:160561037"
    ]
    [color_chunk] = [
        chunk
        for chunk in chunk_preprocessed_documents(documents)
        if chunk.content_format == "json" and chunk.source_location == "table-1/row[0]"
    ]

    return create_fixed_evidence_runtime(
        settings, [SearchCandidate(chunk=color_chunk, rank=1)]
    )
