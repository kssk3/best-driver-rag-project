"""팀원 콜백과 실행 기록을 공용 파이프라인에 연결한다."""

from collections.abc import Callable

from src.config import RuntimeSettings
from src.contracts import (
    Chunk,
    GenerationResult,
    PipelineRequest,
    PlaceLookupResult,
    ResolvedQuery,
    SearchCandidate,
)
from src.observability.records import RunRecorder
from src.pipeline import RAGPipeline


def create_runtime(
    settings: RuntimeSettings,
    *,
    resolver: Callable[[PipelineRequest], ResolvedQuery],
    retriever: Callable[..., list[SearchCandidate]],
    generator: Callable[[PipelineRequest, list[Chunk]], GenerationResult],
    rewriter: Callable[[ResolvedQuery], str] | None = None,
    place_lookup: Callable[[PipelineRequest, ResolvedQuery], PlaceLookupResult] | None = None,
) -> RAGPipeline:
    """실제 모델/검색 제공자는 호출자가 준비한다. 초기화만으로 외부 요청하지 않는다."""
    return RAGPipeline(
        resolver=resolver,
        retriever=retriever,
        generator=generator,
        rewriter=rewriter,
        place_lookup=place_lookup,
        recorder=RunRecorder(settings.runs_path),
        options=settings.pipeline.model_copy(deep=True),
    )
