"""공통 응답(dict)을 화면용 ViewResponse로 바꾸는 어댑터.

담당: 이승주
상태: 공용 규격(src/contracts.py)이 확정되기 전의 임시 가정이다.
규격의 필드명이 바뀌면 이 파일만 고친다.
"""


from dataclasses import dataclass
from typing import Literal


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


@dataclass(frozen=True)
class ViewResponse:
    request_id: str | None
    kind: Literal['fixture', 'real'] # 예시와 실제 실행 구분
    status: str
    answer: str | None
    required_fields: list[str]
    candidates: list[Candidate]
    model_inputs: list[str] | None # None은 알 수 없음, 빈 리스트는 실제로 없음
    citations: list[Citation]
    error: str | None


def to_view_response(raw: dict, kind: Literal['fixture', 'real']) -> ViewResponse:
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
            Citation(s['chunk_id'], s.get('source_url')) for s in raw.get('sources', [])
        ],
        error=raw.get('error'),
    )