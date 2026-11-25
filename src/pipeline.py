"""UI와 평가가 함께 호출하는 RAG 실행 흐름. 담당별 구현은 콜백으로 연결한다."""

from collections.abc import Callable
from datetime import datetime, timezone
from time import perf_counter
from typing import Protocol, TypeVar
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from src.common.errors import ApplicationError, ErrorCategory, describe_error
from src.contracts import (
    Chunk,
    Citation,
    GenerationResult,
    PipelineOptions,
    PipelineRequest,
    PipelineResponse,
    PlaceLookupResult,
    ResolvedQuery,
    RunRecord,
    SearchCandidate,
    StageRecord,
)
from src.observability.records import RunRecorder


class Retriever(Protocol):
    def __call__(
        self, query: ResolvedQuery, *, variant: str, top_k: int
    ) -> list[SearchCandidate]: ...


_Result = TypeVar("_Result")
_Model = TypeVar("_Model", bound=BaseModel)
_CORE_STAGES = ("resolve", "rewrite", "retrieve", "context", "generate", "citations")


class PipelineContractError(ApplicationError, ValueError):
    """콜백 결과가 공용 실행 규격을 어긴 경우. 이유별 code는 raise할 때 지정한다.

    ValueError를 함께 상속해 기존 except ValueError 처리와 호환한다.
    """

    code = "pipeline.contract_violation"
    category = ErrorCategory.CONTRACT_VIOLATION


class PipelineConfigurationError(ApplicationError, ValueError):
    """실행 옵션이 요구하는 콜백이 연결되지 않은 경우."""

    code = "pipeline.rewriter_not_configured"
    category = ErrorCategory.CONFIGURATION


def _validate_callback_result(model: type[_Model], value: object) -> _Model:
    # 생성 후 수정된 Pydantic 객체도 중첩 청크까지 다시 검사한다.
    payload = value.model_dump() if isinstance(value, BaseModel) else value
    try:
        return model.model_validate(payload)
    except ValidationError as error:
        # 검증 상세는 그대로 남기고, 평가가 콜백 규격 위반으로 분류할 수 있게 코드를 붙인다.
        raise PipelineContractError(
            str(error), code="pipeline.invalid_callback_result"
        ) from error


class RAGPipeline:
    """실제 검색/생성 정책을 주입하고 후보, 모델 입력과 인용을 각각 기록한다."""

    def __init__(
        self,
        *,
        resolver: Callable[[PipelineRequest], ResolvedQuery],
        retriever: Retriever,
        generator: Callable[[PipelineRequest, list[Chunk]], GenerationResult],
        rewriter: Callable[[ResolvedQuery], str] | None = None,
        place_lookup: Callable[[PipelineRequest, ResolvedQuery], PlaceLookupResult]
        | None = None,
        recorder: RunRecorder | None = None,
        options: PipelineOptions | None = None,
    ) -> None:
        self.resolver = resolver
        self.retriever = retriever
        self.generator = generator
        self.rewriter = rewriter
        self.place_lookup = place_lookup
        self.recorder = recorder
        self.options = (options or PipelineOptions()).model_copy(deep=True)

    def run(self, request: PipelineRequest) -> RunRecord:
        """호출마다 새 실행 ID를 만들고 실패도 error 상태의 기록으로 반환한다."""
        run_id = uuid4().hex
        started_at = datetime.now(timezone.utc)
        started = perf_counter()
        # 콜백이 전달받은 객체를 수정해도 원질문, 설정과 검색 원본을 보존한다.
        original = request.model_copy(deep=True)
        options = self.options.model_copy(deep=True)
        stages: list[StageRecord] = []
        warnings: list[str] = []
        candidates: list[SearchCandidate] = []
        evidence: list[Chunk] = []
        resolved: ResolvedQuery | None = None
        search_query: str | None = None

        def stage(name: str, operation: Callable[[], _Result]) -> _Result:
            began = perf_counter()
            try:
                result = operation()
            except Exception as error:
                info = describe_error(error)
                stages.append(
                    StageRecord(
                        name=name,
                        status="error",
                        duration_ms=(perf_counter() - began) * 1000,
                        error=info.detail,
                        error_code=info.code,
                    )
                )
                raise
            stages.append(
                StageRecord(
                    name=name,
                    status="ok",
                    duration_ms=(perf_counter() - began) * 1000,
                )
            )
            return result

        def resolve() -> ResolvedQuery:
            result = _validate_callback_result(
                ResolvedQuery, self.resolver(original.model_copy(deep=True))
            )
            if not result.search_query.strip():
                raise PipelineContractError(
                    "해석된 검색 질의는 빈 문자열일 수 없습니다.",
                    code="pipeline.empty_search_query",
                )
            if result.status == "needs_clarification":
                if (
                    not result.clarification_question
                    or not result.clarification_question.strip()
                ):
                    raise PipelineContractError(
                        "확인이 필요한 경우 추가 질문을 제공해야 합니다.",
                        code="pipeline.missing_clarification_question",
                    )
            elif (
                original.district
                and result.district
                and original.district != result.district
            ):
                raise PipelineContractError(
                    "해석된 지역이 요청에서 지정한 지역과 다릅니다.",
                    code="pipeline.region_mismatch",
                )
            return result.model_copy(deep=True)

        try:
            resolved = stage("resolve", resolve)
            search_query = resolved.search_query
            if resolved.status == "needs_clarification":
                response = PipelineResponse(
                    request_id=original.request_id,
                    run_id=run_id,
                    status="needs_clarification",
                    answer=resolved.clarification_question or "",
                )
            else:
                if options.rewrite_enabled:

                    def rewrite() -> str:
                        if self.rewriter is None:
                            raise PipelineConfigurationError(
                                "리라이트가 활성화됐지만 rewriter가 연결되지 않았습니다."
                            )
                        value = self.rewriter(resolved.model_copy(deep=True))
                        if not isinstance(value, str) or not value.strip():
                            raise PipelineContractError(
                                "리라이트 결과는 비어 있지 않은 문자열이어야 합니다.",
                                code="pipeline.invalid_rewrite_output",
                            )
                        return value

                    try:
                        search_query = stage("rewrite", rewrite)
                    except Exception as error:
                        # 응답은 계속 진행하므로 코드는 rewrite 단계 기록에만 남는다.
                        detail = describe_error(error).detail
                        warnings.append(
                            f"리라이트 실패로 기존 검색 질의를 사용합니다: {detail}"
                        )

                retrieval_query = resolved.model_copy(
                    update={"search_query": search_query}, deep=True
                )

                def retrieve() -> list[SearchCandidate]:
                    found = self.retriever(
                        retrieval_query.model_copy(deep=True),
                        variant=options.variant,
                        top_k=options.top_k,
                    )
                    if not isinstance(found, list):
                        raise PipelineContractError(
                            "검색 결과는 SearchCandidate 목록이어야 합니다.",
                            code="pipeline.invalid_retrieval_result",
                        )
                    return [
                        _validate_callback_result(SearchCandidate, item).model_copy(
                            deep=True
                        )
                        for item in found
                    ]

                candidates = stage("retrieve", retrieve)

                def select_context() -> list[Chunk]:
                    selected: list[Chunk] = []
                    seen: set[str] = set()
                    total = 0
                    district = resolved.district or original.district
                    for candidate in candidates:
                        chunk = candidate.chunk
                        if chunk.chunk_id in seen:
                            raise PipelineContractError(
                                f"검색 후보의 chunk_id가 중복됩니다: {chunk.chunk_id}",
                                code="pipeline.duplicate_chunk_id",
                            )
                        seen.add(chunk.chunk_id)
                        applicable = chunk.scope_type == "common" or (
                            chunk.scope_type == "district"
                            and district is not None
                            and district in chunk.districts
                        )
                        if not applicable or len(selected) >= options.top_k:
                            continue
                        # 표 뒤 각주와 예외 조건이 잘리지 않도록 청크 전체를 선택하거나 제외한다.
                        if total + len(chunk.content) > options.max_context_chars:
                            warnings.append(
                                f"본문 길이 제한으로 청크 전체를 제외했습니다: {chunk.chunk_id}"
                            )
                            continue
                        selected.append(chunk.model_copy(deep=True))
                        total += len(chunk.content)
                    return selected

                evidence = stage("context", select_context)
                # 생성기는 원질문 기준으로 답하되, 지역은 해석된 구·동을 받는다.
                # 질문에 동만 쓴 경우(예: 연희동) 원래 요청에는 구가 비어 있어서
                # 검색과 같은 근거를 받아도 지역 조건을 확인하지 못하기 때문이다.
                # 실행 기록(record.request)에는 원래 요청을 그대로 남긴다.
                generation_request = original.model_copy(
                    update={
                        # 해석된 구/동(resolved)이 있으면 그걸 쓰고,
                        # 없으면 사용자가 화면에서 고른 값(original)을 씀.
                        "district": resolved.district or original.district,
                        "dong": resolved.dong or original.dong,
                    },
                    deep=True,
                )
                generated = stage(
                    "generate",
                    lambda: _validate_callback_result(
                        GenerationResult,
                        self.generator(
                            generation_request,
                            [item.model_copy(deep=True) for item in evidence],
                        ),
                    ),
                )

                def citations() -> list[Citation]:
                    by_id = {chunk.chunk_id: chunk for chunk in evidence}
                    if generated.status == "answered" and not generated.cited_chunk_ids:
                        raise PipelineContractError(
                            "answered 응답에는 실제 모델 입력 근거의 인용이 필요합니다.",
                            code="pipeline.missing_citation",
                        )
                    result: list[Citation] = []
                    cited: set[str] = set()
                    for chunk_id in generated.cited_chunk_ids:
                        if chunk_id not in by_id:
                            raise PipelineContractError(
                                f"모델에 전달하지 않은 청크를 인용했습니다: {chunk_id}",
                                code="pipeline.citation_outside_evidence",
                            )
                        if chunk_id in cited:
                            continue
                        cited.add(chunk_id)
                        chunk = by_id[chunk_id]
                        result.append(
                            Citation(
                                chunk_id=chunk.chunk_id,
                                document_id=chunk.source_document_id,
                                document_version=chunk.source_document_version,
                                source_url=chunk.source_url,
                                source_location=chunk.source_location,
                                title=chunk.title,
                            )
                        )
                    return result

                response = PipelineResponse(
                    request_id=original.request_id,
                    run_id=run_id,
                    status=generated.status,
                    answer=generated.answer,
                    citations=stage("citations", citations),
                )
        except Exception as error:
            # 화면에는 원래 예외 메시지 대신 클래스에 고정된 안내 문구를 보인다.
            info = describe_error(error)
            response = PipelineResponse(
                request_id=original.request_id,
                run_id=run_id,
                status="error",
                answer=info.user_message,
                error=info.detail,
                error_code=info.code,
            )

        executed = {item.name for item in stages}
        for name in _CORE_STAGES:
            if name not in executed:
                stages.append(StageRecord(name=name, status="skipped", duration_ms=0))
        stages.sort(key=lambda item: _CORE_STAGES.index(item.name))

        # 장소 조회 실패는 문서 검색/생성 결과와 별도로 표시한다.
        if (
            self.place_lookup is not None
            and resolved is not None
            and resolved.status == "resolved"
        ):
            try:
                response.places = stage(
                    "place_lookup",
                    lambda: _validate_callback_result(
                        PlaceLookupResult,
                        self.place_lookup(
                            original.model_copy(deep=True),
                            resolved.model_copy(deep=True),
                        ),
                    ),
                )
                # 콜백이 예외 대신 실패 결과를 돌려준 경우도 단계 기록에 실패로 남긴다.
                # stage()가 방금 추가한 place_lookup 기록이며, 응답과 places는 그대로 둔다.
                if response.places.status == "error":
                    reported = (response.places.error or "").strip()
                    stages[-1] = stages[-1].model_copy(
                        update={
                            "status": "error",
                            "error": reported
                            or "장소 조회 콜백이 실패 상태를 반환했습니다.",
                            "error_code": "pipeline.place_lookup_failed",
                        }
                    )
            except Exception as error:
                # 코드는 place_lookup 단계 기록에 남고, 문서 답변 상태는 바꾸지 않는다.
                response.places = PlaceLookupResult(
                    status="error", error=describe_error(error).detail
                )
        else:
            stages.append(
                StageRecord(name="place_lookup", status="skipped", duration_ms=0)
            )

        record = RunRecord(
            run_id=run_id,
            request_id=original.request_id,
            run_kind=options.run_kind,
            started_at=started_at,
            request=original,
            options=options,
            resolved_query=resolved,
            search_query=search_query,
            candidates=candidates,
            model_input_chunk_ids=[chunk.chunk_id for chunk in evidence],
            response=response,
            stages=stages,
            duration_ms=(perf_counter() - started) * 1000,
            warnings=warnings,
        )
        # duration_ms는 기록 파일 저장 전까지의 파이프라인 실행 시간이다.
        if self.recorder is not None:
            began = perf_counter()
            try:
                self.recorder.write(record)
            except Exception as error:
                info = describe_error(error)
                record.stages.append(
                    StageRecord(
                        name="record",
                        status="error",
                        duration_ms=(perf_counter() - began) * 1000,
                        error=info.detail,
                        error_code=info.code,
                    )
                )
                record.response.status = "error"
                # 앞 단계에서 이미 실패했다면 최초 원인 코드를 유지한다.
                if record.response.error_code is None:
                    record.response.error_code = info.code
                record.response.error = (
                    record.response.error + "; " if record.response.error else ""
                ) + f"실행 기록 저장 실패: {info.detail}"
        return record
