"""공통 응답(dict)을 화면용 ViewResponse로 바꾸는 어댑터.

담당: 이승주
공용 규격(src/contracts.py)이 확정되기 전의 임시 가정이다.
규격의 필드명이 바뀌면 이 파일만 고친다.
"""


from dataclasses import dataclass
from typing import Literal

from src.contracts import RunRecord

ViewKind = Literal['fixture', 'demo', 'real']
STATUSES = ("answered", "needs_clarification", "insufficient_evidence", "error")


@dataclass(frozen=True)
class Candidate:
    chunk_id: str
    district: str | None
    score: float | None
    text: str


@dataclass(frozen=True)
class Citation:
    chunk_id: str
    source_url: str | None
    title: str | None = None
    source_location: str | None = None
    document_version: str | None = None


@dataclass(frozen=True)
class ViewResponse:
    request_id: str | None
    kind: ViewKind # 예시, 데모, 실제 실행 구분
    status: str
    answer: str | None
    required_fields: list[str]
    candidates: list[Candidate]
    model_inputs: list[str] | None # None은 알 수 없음, 빈 리스트는 실제로 없음
    citations: list[Citation]
    error: str | None


def to_view_response(raw: dict, kind: ViewKind) -> ViewResponse:
    status = raw.get('status')
    if status not in STATUSES:
        raise ValueError(f'알 수 없는 status: {status!r}')

    trace = raw.get('debug_trace') or {}
    model_inputs = trace.get('model_inputs')
    return ViewResponse(
        request_id=raw.get('request_id'),
        kind=kind,
        status=status,
        answer=raw.get('answer'),
        required_fields=list(raw.get('required_fields') or []),
        candidates=[
            Candidate(c['chunk_id'], c.get('district'), c.get('score'), c.get('text', ''))

            for c in trace.get('candidates', [])
        ],
        model_inputs=None if model_inputs is None else list(model_inputs),
        citations=[
            Citation(
                s['chunk_id'],
                s.get('source_url'),
                s.get('title'),
                s.get('source_location'),
                s.get('document_version'),
            )
            for s in raw.get('sources', [])
        ],
        error=raw.get('error'),
    )


PLACE_STATUSES = ('found', 'empty', 'unavailable', 'error')


@dataclass(frozen=True)
class Place:
    place_id: str
    name: str
    address: str | None
    latitude: float | None # 숫자가 아니거나 범위 밖이면 None (좌표누락)
    longitude: float | None
    source_url: str | None
    collection_types: list[str] # 빈 목록은 확인된 종류 없음을 나타냄


@dataclass(frozen=True)
class PlaceResult:
    status: str # PLACE_STATUSES
    kind: ViewKind
    places: list[Place]
    error: str | None


def _to_coordinate(value: object, limit: float) -> float | None:

    if isinstance(value, bool):
        return None
    
    try:
        number = float(value)
    
    except (TypeError, ValueError):
        return None

    # 좌표 값이 숫자이고 -limit~limit 범위 안이면 float, 아니면 None
    # 위도는 -90 이상 90 이하, 경도는 -180 이상 180 이하일 때만 True
    return number if -limit <= number <= limit else None


def to_place_result(raw: dict, kind: ViewKind) -> PlaceResult:

    status = raw.get('status')
    if status not in PLACE_STATUSES:
        raise ValueError(f'알 수 없는 장소 상태: {status!r}')

    places = [
        Place(
            place_id=item['place_id'],
            name=item['name'],
            address=item.get('address'),
            latitude=_to_coordinate(item.get('latitude'), 90),
            longitude=_to_coordinate(item.get('longitude'), 180),
            source_url=item.get('source_url'),
            collection_types=list(item.get('collection_types') or []),
        )
        for item in raw.get('places', [])
    ]
    return PlaceResult(status=status, kind=kind, places=places, error=raw.get('error'))


def _kind_of(record: RunRecord) -> ViewKind:
    return 'demo' if record.run_kind == 'demo' else 'real'


def run_record_to_view(record: RunRecord) -> ViewResponse:

    response = record.response
    resolved = record.resolved_query

    required: list[str] = []
    if response.status == 'needs_clarification':
        if resolved is None or resolved.district is None:
            required.append('district')
        elif resolved.dong is None and resolved.region_status in ('ambiguous', 'no_dong'):
            required.append('dong')

    return ViewResponse(
        request_id=response.request_id,
        kind=_kind_of(record),
        status=response.status,
        answer=response.answer,
        required_fields=required,
        candidates=[
            Candidate(
                c.chunk.chunk_id,
                ', '.join(c.chunk.districts) or None,
                c.score,
                c.chunk.content,
            )
            for c in record.candidates
        ],
        model_inputs=list(record.model_input_chunk_ids),
        citations=[
            Citation(c.chunk_id, c.source_url, c.title, c.source_location, c.document_version)
            for c in response.citations
        ],
        error=response.error,
    )


def run_record_to_places(record: RunRecord) -> PlaceResult:
    return to_place_result(record.response.places.model_dump(), _kind_of(record))