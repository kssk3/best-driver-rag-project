import json
from hashlib import sha256
from pathlib import Path

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
from src.retrieval.search import make_vector_retriever
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


def create_a_runtime(settings: RuntimeSettings) -> RAGPipeline:
    """Run each development question through region resolution, A search and generation."""
    config = settings.model_copy(deep=True)
    options = config.pipeline
    model = _configured_model(config)
    if options.variant != "A" or options.rewrite_enabled:
        raise PipelineConfigurationError(
            "A 검색과 리라이트 OFF로 설정하세요.",
            code="evaluation.unsupported_configuration",
        )

    index = load_index(config.index_path)
    embedding_model, dimensions = _embedding_settings(index.metadata.embedding_identity)
    embedder = create_openai_embeddings(embedding_model, dimensions)
    retrieve = make_vector_retriever(index, embedder)

    options.run_kind = "rag"
    options.versions.update(
        {
            "index": index.metadata.index_id,
            "chunking": index.metadata.chunking_version,
            "embedding": embedding_model,
            "model": model,
            "prompt": sha256(SYSTEM_PROMPT.encode()).hexdigest(),
        }
    )
    return create_runtime(
        config,
        resolver=resolve_request,
        retriever=retrieve,
        generator=make_answer_generator(make_model_draft(model)),
    )


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
