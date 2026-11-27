"""공통 응답(dict)을 화면용 ViewResponse로 바꾸는 어댑터.

공용 규격(src/contracts.py)의 필드명이 바뀌면 이 파일만 고친다.
"""

from dataclasses import dataclass, field
from typing import Literal

from src.contracts import RunRecord

ViewKind = Literal["fixture", "demo", "fixed_evidence", "real"]
STATUSES = ("answered", "needs_clarification", "insufficient_evidence", "error")


@dataclass(frozen=True)
class Candidate:
    chunk_id: str
    district: str | None
    score: float | None
    text: str
    rank: int | None = None  # 최종 순위. 예시 응답에는 없다.
    conditions: list[str] = field(
        default_factory=list
    )  # 청크가 가진 조건. 비어 있으면 모름
    stage_scores: dict[str, float] = field(default_factory=dict)  # 검색 단계별 점수
    districts: list[str] = field(default_factory=list)  # 청크가 적용되는 구 목록
    scope_type: str | None = None  # district, common, unknown. 예시 응답에는 없다.


@dataclass(frozen=True)
class StageError:
    name: str  # 실패한 단계 이름
    error_code: str | None
    error: str | None


@dataclass(frozen=True)
class Citation:
    chunk_id: str
    source_url: str | None
    title: str | None = None
    source_location: str | None = None
    document_version: str | None = None
    document_id: str | None = (
        None  # 별표는 '<조례 문서>:attachment:<번호>' 꼴이라 소속 조례를 알 수 있다
    )


@dataclass(frozen=True)
class ViewResponse:
    request_id: str | None
    kind: ViewKind  # 예시, 데모, 실제 실행 구분
    status: str
    answer: str | None
    required_fields: list[str]
    candidates: list[Candidate]
    model_inputs: list[str] | None  # None은 알 수 없음, 빈 리스트는 실제로 없음
    citations: list[Citation]
    error: str | None
    request_conditions: dict[str, str] = field(
        default_factory=dict
    )  # 사용자가 넣은 조건
    stage_errors: list[StageError] = field(
        default_factory=list
    )  # 실패한 단계(답변은 유지됐을 수 있다)
    error_code: str | None = (
        None  # 응답을 오류로 만든 최초 원인 코드(status가 error일 때만)
    )
    # 지역 해석 상태. 지원 밖 안내처럼 채울 항목이 없는 정상 안내를 구분하는 데 쓴다.
    region_status: str | None = None


def to_view_response(raw: dict, kind: ViewKind) -> ViewResponse:
    status = raw.get("status")
    if status not in STATUSES:
        raise ValueError(f"알 수 없는 status: {status!r}")

    trace = raw.get("debug_trace") or {}
    model_inputs = trace.get("model_inputs")
    return ViewResponse(
        request_id=raw.get("request_id"),
        kind=kind,
        status=status,
        answer=raw.get("answer"),
        required_fields=list(raw.get("required_fields") or []),
        candidates=[
            Candidate(
                c["chunk_id"], c.get("district"), c.get("score"), c.get("text", "")
            )
            for c in trace.get("candidates", [])
        ],
        model_inputs=None if model_inputs is None else list(model_inputs),
        citations=[
            Citation(
                s["chunk_id"],
                s.get("source_url"),
                s.get("title"),
                s.get("source_location"),
                s.get("document_version"),
                s.get("document_id"),
            )
            for s in raw.get("sources", [])
        ],
        error=raw.get("error"),
    )


def _kind_of(record: RunRecord) -> ViewKind:
    if record.run_kind in ("demo", "fixed_evidence"):
        return record.run_kind
    return "real"


def run_record_to_view(record: RunRecord) -> ViewResponse:

    response = record.response
    resolved = record.resolved_query

    required: list[str] = []
    if response.status == "needs_clarification":
        if resolved is None or resolved.district is None:
            required.append("district")
        elif resolved.dong is None and resolved.region_status in (
            "ambiguous",
            "no_dong",
        ):
            required.append("dong")

    return ViewResponse(
        request_id=response.request_id,
        kind=_kind_of(record),
        status=response.status,
        answer=response.answer,
        required_fields=required,
        candidates=[
            Candidate(
                c.chunk.chunk_id,
                ", ".join(c.chunk.districts) or None,
                c.score,
                c.chunk.content,
                rank=c.rank,
                conditions=list(c.chunk.conditions),
                stage_scores=dict(c.stage_scores),
                districts=list(c.chunk.districts),
                scope_type=c.chunk.scope_type,
            )
            for c in record.candidates
        ],
        model_inputs=list(record.model_input_chunk_ids),
        citations=[
            Citation(
                c.chunk_id,
                c.source_url,
                c.title,
                c.source_location,
                c.document_version,
                c.document_id,
            )
            for c in response.citations
        ],
        error=response.error,
        request_conditions=dict(record.request.conditions),
        error_code=response.error_code,
        region_status=resolved.region_status if resolved else None,
        stage_errors=[
            StageError(s.name, s.error_code, s.error)
            for s in record.stages
            if s.status == "error"
        ],
    )
