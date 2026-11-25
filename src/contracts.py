"""공용 입출력 규격.

담당: 양석호
상태: 기존 문서 규격과 담당 모듈을 연결하는 최소 실행 규격.
공용 규격은 Pydantic 모델로 정의한다.
필드와 호출 규격은 합의한 부분부터 추가하고 사용하는 담당자와 검토한다.
"""

import math
from datetime import date, datetime
from pathlib import PurePosixPath, PureWindowsPath
from typing import Literal, Self
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


# 공용 규격은 Pydantic 모델로 정의하기로 했다.
# 모델을 만들 때 필수 필드 누락과 타입 오류를 확인하기 위해 선택했다.
class SourceDocument(BaseModel):
    """원문 문서 한 건의 특정 버전을 전처리한 표현. 합의한 필드부터 추가하는 중이다."""

    # 원문 웹페이지나 XML/HWP/PDF 자료 하나를 SourceDocument로 보관한다.
    # 조례 본문과 각 별표/서식 첨부도 별도 문서로 만들고 아래 부모 참조로 연결한다.
    # 품목과 적용 조건을 기준으로 나누는 검색용 자료는 별도 Chunk 모델로 정의한다.
    # 이렇게 구분하면 검색용으로 나누더라도 원문과 출처를 연결할 수 있다.

    # 같은 원문 문서의 내용이 갱신돼도 유지하는 식별자다.
    # 수정된 문서인지 아예 다른 문서인지 구분하려고 버전과 분리했다.
    document_id: str

    # 같은 document_id 안에서 원문 내용의 변경을 구분하는 값이다.
    # 예: document_id="doc-001"을 유지하면서 version="v1"에서 "v2"로 변경한다.
    # 청크는 어느 시점의 원문에서 나왔는지 문서 ID와 버전을 함께 연결해야 한다.
    # 버전의 발급 방식은 아직 정하지 않았으므로 자동 증가나 기본값을 넣지 않는다.
    # 같은 원문을 HTML과 JSON으로 표현만 바꿨다면 문서 ID와 원문 버전은 유지한다.
    version: str

    # 원문에 명시된 시행일이다. 내부 문서 변경을 구분하는 version과 별도로 보존한다.
    # sources.json의 시행일은 YYYYMMDD 형식이므로 로더에서 날짜로 변환해 전달한다.
    # 확인할 수 없는 경우에는 None을 유지하고 현재 날짜나 부모 문서의 날짜로 추정하지 않는다.
    effective_date: date | None = None

    # 사람이 출처를 알아볼 수 있도록 원문에 적힌 문서 제목을 보존한다.
    # sources.json에서 조례 본문은 자치법규명, 첨부는 해당 별표_링크의 제목을 사용한다.
    # 제목이 같거나 개정 과정에서 달라져도 문서 식별은 document_id로 한다.
    title: str

    # 원본 PDF/HWP의 형식이 아니라 전처리 결과를 표현하는 형식이다.
    # 비교 결과를 저장할 때 문서 ID와 원문 버전만으로 두 표현을 덮어쓰지 않도록
    # content_format과 실험 조건도 함께 구분한다.
    content_format: Literal["html", "json"]

    # HTML/JSON 전처리 결과를 문자열로 보존한다. JSON 객체는 JSON 문자열로 전달한다.
    # 표의 항목 관계, 각주와 예외 조건을 유지하고 여기서 임의로 평문으로 바꾸지 않는다.
    # 실제 형식 파싱과 구조 검증은 로더에서 담당하며, 이 모델은 본문을 재작성하지 않는다.
    content: str

    # 사용자가 답변의 근거를 직접 확인할 수 있는 공식 웹페이지 또는 원문 파일 주소다.
    # document_id는 내부에서 문서를 식별하고, source_url은 외부 원문으로 연결한다.
    # 내려받은 파일의 로컬 저장 경로와 구분해 원문 출처 주소를 보존한다.
    source_url: str

    # 내려받아 보관한 원문 위치를 프로젝트 루트 기준 상대 경로로 기록한다.
    # 팀원마다 다른 PC의 절대 경로를 공유하지 않기 위해 선택했다.
    # 아직 보관하지 않았다면 None이며, source_url과 달리 인터넷 주소를 넣지 않는다.
    # sources.json의 본문_파일도 실제 보관 위치를 확인해 프로젝트 기준 경로로 맞춘다.
    raw_path: str | None = None

    # 구 목록이 없다는 이유만으로 공통 안내라고 판단하지 않도록 적용 범위를 구분한다.
    # district는 특정 구에 적용, common은 공통 안내, unknown은 적용 지역 미확인이다.
    # unknown을 별도로 보관하고 실제 검색에서 사용할지 판단하는 것은 검색 단계의 역할이다.
    scope_type: Literal["district", "common", "unknown"]

    # district일 때 적용되는 구 이름을 담는다. 예: ["서대문구"], ["송파구"].
    # 하나의 안내가 여러 구에 적용될 수 있으므로 문자열 하나 대신 목록으로 둔다.
    # common과 unknown은 빈 목록을 사용하며 두 의미는 scope_type으로 구분한다.
    districts: list[str]

    # 조례 본문은 부모가 없으므로 None이고, 각 첨부는 자신이 속한 본문의 ID를 넣는다.
    # sources.json의 별표_링크를 본문 content에 합치지 않고 문서별 출처를 유지하기로 했다.
    # 이 참조는 청크의 원문 연결과 다르다. 첨부도 나중에 자기 청크를 갖는 원문 문서다.
    parent_document_id: str | None = None

    # 같은 조례 ID라도 개정본마다 첨부가 달라질 수 있어 부모 버전도 함께 연결한다.
    # 첨부 자신의 version과 부모의 버전은 서로 다른 문서의 값이므로 같을 필요가 없다.
    parent_document_version: str | None = None

    # 이 모델은 전달받은 문서 데이터를 보관하며 본문을 직접 정제하지 않는다.
    # 표, 각주와 예외 조건이 실제로 보존됐는지는 수집/정제 단계에서 원문과 대조한다.
    # 기존 ID 유지와 내용 변경에 따른 버전 갱신은 이후 수집/색인 로직에서 처리한다.

    @field_validator("raw_path")
    @classmethod
    def _validate_raw_path(cls, value: str | None) -> str | None:
        """상대 경로 형식을 검사하고 운영체제에 따른 구분자 차이를 줄인다."""
        if value is None:
            return None

        # 현재 실행 OS와 무관하게 Windows 드라이브/UNC 경로도 식별한다.
        windows_path = PureWindowsPath(value)
        relative_path = PurePosixPath(value.replace("\\", "/"))
        if not value.strip() or not relative_path.parts:
            raise ValueError("raw_path는 빈 경로 대신 None을 사용해야 합니다.")
        if windows_path.anchor or relative_path.is_absolute() or ":" in value:
            raise ValueError(
                "raw_path는 URL이나 절대 경로가 아닌 상대 경로여야 합니다."
            )
        if ".." in relative_path.parts or "\0" in value:
            raise ValueError(
                "raw_path에는 상위 경로(..)나 NUL 문자를 넣을 수 없습니다."
            )

        # 파일을 읽거나 존재를 확인하지 않는다. 실제 파일 접근 시에는 로더에서
        # 프로젝트 루트와 결합하고, 심볼릭 링크 등을 해결한 경로와 존재 여부를 확인한다.
        return relative_path.as_posix()

    @model_validator(mode="after")
    def _validate_scope_and_districts(self) -> Self:
        """각 필드의 타입 검사 후 적용 범위와 구 목록의 조합을 확인한다."""
        # 특정 구에 적용된다고 표시했는데 구가 없으면 검색 제한을 정할 수 없다.
        if self.scope_type == "district":
            if not self.districts or any(
                not district.strip() for district in self.districts
            ):
                raise ValueError(
                    "district 범위에는 비어 있지 않은 구 이름이 필요합니다."
                )
        elif self.districts:
            # 값을 임의로 삭제하거나 공통/미확인 상태를 추정하지 않고 입력 오류를 알린다.
            raise ValueError(
                "common과 unknown 범위의 districts는 빈 목록이어야 합니다."
            )
        return self

    @model_validator(mode="after")
    def _validate_parent_reference(self) -> Self:
        """부모 문서의 ID와 버전을 함께 입력했는지 검사한다."""
        parent_id = self.parent_document_id
        parent_version = self.parent_document_version
        if parent_id is None and parent_version is None:
            return self
        if parent_id is None or parent_version is None:
            raise ValueError("부모 문서 ID와 버전은 함께 입력해야 합니다.")

        if not parent_id.strip() or not parent_version.strip():
            raise ValueError("부모 문서 ID와 버전은 빈 문자열일 수 없습니다.")
        if parent_id == self.document_id:
            raise ValueError("문서는 자기 자신을 부모 문서로 참조할 수 없습니다.")

        # 여기서는 참조의 형태만 검사한다. 실제 부모 문서와 버전의 존재 여부는
        # 문서 묶음을 읽거나 저장소에 연결할 때 확인해야 한다.
        return self


class Chunk(BaseModel):
    """하나의 원문 버전과 전처리 표현에 연결된 검색용 청크."""

    chunk_id: str = Field(min_length=1)

    # 청크 하나는 SourceDocument 한 건의 특정 버전에서만 만들기로 했다.
    # 여러 문서를 합치면 출처와 개정 버전을 함께 추적해야 하므로 단일 참조를 선택했다.
    # 조례 본문과 별표가 함께 필요하면 각 문서의 청크를 답변 단계에서 함께 사용한다.
    # 별표에서 만든 청크는 조례 본문이 아니라 해당 별표 문서를 직접 가리킨다.
    source_document_id: str

    # 원문 ID가 유지돼도 내용은 개정될 수 있으므로 버전을 필수로 함께 보관한다.
    # 이 값은 청크 자체의 버전이나 부모 조례 버전이 아닌 직접 출처 문서의 version이다.
    source_document_version: str

    # 최소 인계본에서는 원문 표현과 출처를 청크에도 보존해 형식별 색인을 구분한다.
    # 표와 각주를 손상하지 않는 문서 단위 청킹을 기본으로 사용한다.
    title: str
    content_format: Literal["html", "json"]
    content: str = Field(min_length=1)
    source_url: str
    source_location: str = Field(min_length=1)
    scope_type: Literal["district", "common", "unknown"]
    districts: list[str]
    conditions: list[str] = Field(default_factory=list)
    chunking_version: str = Field(min_length=1)

    # 실제 문서 존재 여부와 본문이 한 문서에서 나왔는지는 청킹/색인 단계에서 확인한다.

    @field_validator("source_document_id", "source_document_version")
    @classmethod
    def _validate_source_reference(cls, value: str) -> str:
        """출처를 추적할 수 없는 빈 식별자와 버전을 거부한다."""
        if not value.strip():
            raise ValueError("청크의 원문 문서 ID와 버전은 빈 문자열일 수 없습니다.")
        return value

    @model_validator(mode="after")
    def _validate_region_scope(self) -> Self:
        if self.scope_type == "district":
            if not self.districts or any(
                not district.strip() for district in self.districts
            ):
                raise ValueError("district 청크에는 적용 구가 필요합니다.")
        elif self.districts:
            raise ValueError(
                "common과 unknown 청크의 districts는 빈 목록이어야 합니다."
            )
        return self


# 아래 타입은 최소 인계용 호출 경계다. 각 팀원의 내부 구현과 모델 선택은 강제하지 않는다.
ResponseStatus = Literal[
    "answered", "needs_clarification", "insufficient_evidence", "error"
]


class PipelineRequest(BaseModel):
    request_id: str = Field(default_factory=lambda: uuid4().hex)
    question: str = Field(min_length=1)
    district: str | None = None
    dong: str | None = None
    conditions: dict[str, str] = Field(default_factory=dict)

    @field_validator("question")
    @classmethod
    def _question_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("질문은 빈 문자열일 수 없습니다.")
        return value


class ResolvedQuery(BaseModel):
    search_query: str = Field(min_length=1)
    district: str | None = None
    dong: str | None = None
    status: Literal["resolved", "needs_clarification"] = "resolved"
    clarification_question: str | None = None
    # 팀이 정한 지역 해석 4상태. 파이프라인 분기용 status(2개)와 따로 전달한다.
    # None = 지역 해석 안 함
    region_status: Literal["ok", "ambiguous", "unsupported", "no_dong"] | None = None
    candidate_districts: list[str] = Field(default_factory=list)


class PipelineOptions(BaseModel):
    variant: Literal["A", "B", "C"] = "A"
    rewrite_enabled: bool = False
    top_k: int = Field(default=5, ge=1)
    max_context_chars: int = Field(default=12000, ge=1)
    run_kind: Literal["demo", "rag", "fixed_evidence"] = "rag"
    # 데이터/색인/모델/프롬프트/지역/별칭 등 실제 사용한 버전을 호출자가 제공한다.
    # API 키를 포함한 설정 전체를 이 기록 필드에 넣지 않는다.
    versions: dict[str, str] = Field(default_factory=dict)


class SearchCandidate(BaseModel):
    chunk: Chunk
    rank: int = Field(ge=1)
    score: float | None = Field(default=None, allow_inf_nan=False)
    stage_scores: dict[str, float] = Field(default_factory=dict)

    @field_validator("stage_scores")
    @classmethod
    def _finite_stage_scores(cls, value: dict[str, float]) -> dict[str, float]:
        if any(not math.isfinite(score) for score in value.values()):
            raise ValueError("검색 단계 점수는 유한한 수치여야 합니다.")
        return value


class GenerationResult(BaseModel):
    status: Literal["answered", "needs_clarification", "insufficient_evidence"]
    answer: str
    cited_chunk_ids: list[str] = Field(default_factory=list)

    @field_validator("answer")
    @classmethod
    def _answer_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("답변 또는 대응 안내는 빈 문자열일 수 없습니다.")
        return value


class Citation(BaseModel):
    chunk_id: str
    document_id: str
    document_version: str
    source_url: str
    source_location: str
    title: str


class PlaceResult(BaseModel):
    place_id: str
    name: str
    address: str
    latitude: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    longitude: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)
    source_url: str
    collection_types: list[str] = Field(default_factory=list)


class PlaceLookupResult(BaseModel):
    status: Literal["found", "empty", "unavailable", "error"] = "unavailable"
    places: list[PlaceResult] = Field(default_factory=list)
    error: str | None = None


class PipelineResponse(BaseModel):
    request_id: str
    run_id: str
    status: ResponseStatus
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    places: PlaceLookupResult = Field(default_factory=PlaceLookupResult)
    # error는 기록용 내부 상세("타입: 메시지")이며 화면에는 answer를 표시한다.
    error: str | None = None
    # 실패 원인 코드(<도메인>.<이유>, docs/ERRORS.md). status가 error일 때만 채운다.
    error_code: str | None = None


class StageRecord(BaseModel):
    name: str
    status: Literal["ok", "skipped", "error"]
    duration_ms: float = Field(ge=0, allow_inf_nan=False)
    error: str | None = None
    # 이 단계를 실패시킨 원인 코드. 평가는 (단계 이름, error_code)로 실패를 분류한다.
    error_code: str | None = None


class RunRecord(BaseModel):
    run_id: str
    request_id: str
    run_kind: Literal["demo", "rag", "fixed_evidence"]
    started_at: datetime
    request: PipelineRequest
    options: PipelineOptions
    resolved_query: ResolvedQuery | None = None
    search_query: str | None = None
    candidates: list[SearchCandidate] = Field(default_factory=list)
    model_input_chunk_ids: list[str] = Field(default_factory=list)
    response: PipelineResponse
    stages: list[StageRecord] = Field(default_factory=list)
    duration_ms: float = Field(ge=0, allow_inf_nan=False)
    warnings: list[str] = Field(default_factory=list)


class EvaluationCase(BaseModel):
    case_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    district: str | None = None
    dong: str | None = None
    conditions: dict[str, str] = Field(default_factory=dict)
    # 아래 정답 관련 필드는 사후 평가용이다. 검색/리라이트/생성 요청에 전달하지 않는다.
    expected_status: ResponseStatus | None = None
    reference_answer: str | None = None
    allowed_chunk_ids: list[str] = Field(default_factory=list)
