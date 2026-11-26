"""질문 다듬기 프롬프트와 버전을 공용 런타임에 연결."""

from collections.abc import Callable

from src.config import RuntimeSettings
from src.contracts import (
    Chunk,
    GenerationResult,
    PipelineRequest,
    PlaceLookupResult,
    ResolvedQuery,
)
from src.pipeline import RAGPipeline, Retriever
from src.query.errors import RewriteConfigurationError
from src.query.rewrite import QUERY_REWRITE_PROMPT_VERSION, make_prompt_rewriter
from src.runtime import create_runtime


def create_prompt_rewrite_runtime(
    settings: RuntimeSettings,
    *,
    resolver: Callable[[PipelineRequest], ResolvedQuery],
    retriever: Retriever,
    generator: Callable[[PipelineRequest, list[Chunk]], GenerationResult],
    invoke: Callable[[str, str], str] | None = None,
    place_lookup: Callable[[PipelineRequest, ResolvedQuery], PlaceLookupResult]
    | None = None,
) -> RAGPipeline:
    """정제가 켜지면 P09 콜백과 버전을 연결하고 꺼지면 원질문을 사용."""
    configured = settings.model_copy(deep=True)
    rewriter = None
    if configured.pipeline.rewrite_enabled:
        if invoke is None:
            raise RewriteConfigurationError(
                "P09를 켜려면 질문 다듬기 모델 호출을 지정해야 합니다."
            )
        configured.pipeline.versions["rewrite"] = QUERY_REWRITE_PROMPT_VERSION
        rewriter = make_prompt_rewriter(invoke)
    else:
        configured.pipeline.versions.pop("rewrite", None)

    return create_runtime(
        configured,
        resolver=resolver,
        retriever=retriever,
        generator=generator,
        rewriter=rewriter,
        place_lookup=place_lookup,
    )
