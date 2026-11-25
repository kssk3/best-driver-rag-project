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


def create_a_runtime(settings: RuntimeSettings) -> RAGPipeline:
    """Run each development question through region resolution, A search and generation."""
    config = settings.model_copy(deep=True)
    options = config.pipeline
    model = _configured_model(config)
    if options.variant != "A" or options.rewrite_enabled:
        raise PipelineConfigurationError("A 검색과 리라이트 OFF로 설정하세요.")

    index = load_index(config.index_path)
    identity = json.loads(index.metadata.embedding_identity)
    if not isinstance(identity, dict) or identity.get("provider") != "openai":
        raise PipelineConfigurationError("OpenAI 임베딩으로 만든 색인이 필요합니다.")
    embedder = create_openai_embeddings(
        identity.get("model", ""), identity.get("dimensions")
    )
    retrieve = make_vector_retriever(index, embedder)

    options.run_kind = "rag"
    options.versions.update(
        {
            "index": index.metadata.index_id,
            "chunking": index.metadata.chunking_version,
            "embedding": identity["model"],
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


def create_color_runtime(settings: RuntimeSettings) -> RAGPipeline:
    config = settings.model_copy(deep=True)
    model = _configured_model(config)

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

    config.pipeline.run_kind = "fixed_evidence"
    config.pipeline.versions["prompt"] = sha256(SYSTEM_PROMPT.encode()).hexdigest()

    return create_runtime(
        config,
        resolver=lambda request: ResolvedQuery(
            search_query=request.question, district=request.district, dong=request.dong
        ),
        retriever=lambda *_args, **_kwargs: [
            SearchCandidate(chunk=color_chunk, rank=1)
        ],
        generator=make_answer_generator(make_model_draft(model)),
    )
