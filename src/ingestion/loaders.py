"""출처 목록과 명시적인 전처리 문서 파일을 읽는다.

담당: 양석호
sources.json은 본문과 내부 버전이 없는 목록이므로 별도 입력 모델로 읽는다.
SourceDocument는 본문과 메타데이터가 모두 제공된 문서 파일에서만 구성한다.
원문 다운로드, HWP/PDF 추출과 ID/버전 발급은 수행하지 않는다.
"""

import json
from collections.abc import Mapping
from datetime import date
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Annotated, Self
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

from src.contracts import SourceDocument

# 번호의 선행 0, 제목과 URL의 원래 표기를 보존한다. 숫자를 문자열로 추정 변환하지 않는다.
_NonBlankString = Annotated[
    str, StringConstraints(strict=True, min_length=1, pattern=r"\S")
]


class SourceManifestError(ValueError):
    """파일 내용이 지원하는 출처 목록 형식과 맞지 않을 때 발생한다."""


def _validate_source_url(value: str) -> str:
    """주소를 요청하거나 정규화하지 않고 HTTP(S) 주소의 형태만 검사한다."""
    if any(character.isspace() or ord(character) < 32 for character in value):
        raise ValueError("출처 URL에는 공백이나 제어 문자를 넣을 수 없습니다.")
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        # 잘못된 포트 번호도 urlsplit 결과를 사용하는 시점에 확인한다.
        _ = parsed.port
    except ValueError as error:
        raise ValueError("유효한 HTTP(S) 출처 URL이 필요합니다.") from error
    if parsed.scheme not in {"http", "https"} or not hostname:
        raise ValueError("호스트가 있는 HTTP(S) 출처 URL이 필요합니다.")
    return value


class AttachmentLink(BaseModel):
    """한 조례/시행규칙의 별표_링크 항목. 부모는 이를 담은 SourceManifestEntry다."""

    # 전처리 결과의 다른 구조를 잘못 읽거나 새 필드를 조용히 버리지 않도록 오류로 알린다.
    model_config = ConfigDict(extra="forbid", strict=True)

    # 목록상의 번호다. 실제 별표 제N호나 내부 document_id로 해석하지 않는다.
    number: _NonBlankString = Field(alias="번호")
    title: _NonBlankString = Field(alias="제목")
    source_url: _NonBlankString = Field(alias="파일_URL")

    _check_source_url = field_validator("source_url")(_validate_source_url)


class SourceManifestEntry(BaseModel):
    """출처 목록 한 건과 그 문서에 포함된 첨부 링크. 추출된 본문 문서와 구분한다."""

    model_config = ConfigDict(extra="forbid", strict=True)

    district: _NonBlankString = Field(alias="구")
    title: _NonBlankString = Field(alias="자치법규명")
    # 수집처의 일련번호다. 개정 후 유지되는 내부 문서 ID나 버전이라고 가정하지 않는다.
    ordinance_serial: _NonBlankString = Field(alias="일련번호")
    effective_date: date = Field(alias="시행일")
    source_url: _NonBlankString = Field(alias="원문_URL")
    # 목록에 기재된 상대 경로만 보존한다. 파일 존재나 보관 완료를 의미하지 않으며
    # SourceDocument.raw_path로 옮길 때 실제 프로젝트 내 위치를 별도로 확인해야 한다.
    body_file: _NonBlankString = Field(alias="본문_파일")
    # 부모별로 목록을 유지하므로 다른 조례에서 같은 첨부 번호가 나와도 섞이지 않는다.
    # 삭제/별지/서식도 원래 순서대로 보존하고, 검색 대상 여부는 이 로더에서 결정하지 않는다.
    attachments: list[AttachmentLink] = Field(alias="별표_링크")
    attachment_status: _NonBlankString = Field(alias="별표_상태")

    _check_source_url = field_validator("source_url")(_validate_source_url)

    @field_validator("effective_date", mode="before")
    @classmethod
    def _parse_effective_date(cls, value: object) -> date:
        # YYYYMMDD를 명시적으로 읽는다. 숫자형 날짜를 타임스탬프로 해석하지 않는다.
        if (
            not isinstance(value, str)
            or len(value) != 8
            or not value.isascii()
            or not value.isdecimal()
        ):
            raise ValueError("시행일은 YYYYMMDD 형식의 8자리 문자열이어야 합니다.")
        try:
            return date(int(value[:4]), int(value[4:6]), int(value[6:]))
        except ValueError as error:
            raise ValueError(
                "시행일은 실제 달력에 존재하는 날짜여야 합니다."
            ) from error

    @field_validator("body_file")
    @classmethod
    def _validate_body_file(cls, value: str) -> str:
        relative_path = PurePosixPath(value.replace("\\", "/"))
        if (
            not relative_path.parts
            or relative_path.is_absolute()
            or PureWindowsPath(value).anchor
            or ":" in value
            or ".." in relative_path.parts
            or "\0" in value
        ):
            raise ValueError(
                "본문_파일은 상위 경로 이동이 없는 상대 파일 경로여야 합니다."
            )
        # 여기서 원본 파일을 열거나 다운로드하지 않는다. 선언된 경로 표기도 바꾸지 않는다.
        return value

    @model_validator(mode="after")
    def _check_attachment_numbers(self) -> Self:
        seen: set[str] = set()
        for index, attachment in enumerate(self.attachments):
            if attachment.number in seen:
                raise ValueError(
                    f"별표_링크[{index}].번호 {attachment.number!r}가 같은 부모 안에서 중복됩니다."
                )
            seen.add(attachment.number)
        return self


_SOURCE_MANIFEST = TypeAdapter(list[SourceManifestEntry])


def _unique_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """JSON 중복 키를 마지막 값으로 덮어써 출처 정보를 잃지 않게 한다."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise SourceManifestError(f"중복 JSON 필드 {key!r}가 있습니다.")
        result[key] = value
    return result


def load_source_manifest(path: str | Path) -> list[SourceManifestEntry]:
    """UTF-8 출처 목록을 읽고 문서 순서와 부모별 첨부 관계를 보존해 반환한다.

    UTF-8 BOM도 허용한다. 형식 오류는 파일 경로와 문제 위치를 포함한
    SourceManifestError로 알리며, 파일 접근 오류는 FileNotFoundError 등으로 전달한다.
    입력 전체가 유효할 때만 반환하고, 본문/버전/저장 경로를 만들어 채우지 않는다.
    """
    manifest_path = Path(path)
    try:
        raw_text = manifest_path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as error:
        raise SourceManifestError(
            f"{manifest_path}: UTF-8 JSON 파일이 필요합니다."
        ) from error

    try:
        payload = json.loads(raw_text, object_pairs_hook=_unique_json_keys)
    except json.JSONDecodeError as error:
        raise SourceManifestError(
            f"{manifest_path}: JSON 문법 오류 ({error.lineno}행 {error.colno}열): {error.msg}"
        ) from error
    except SourceManifestError as error:
        raise SourceManifestError(f"{manifest_path}: {error}") from error

    try:
        entries = _SOURCE_MANIFEST.validate_python(payload, strict=True)
    except ValidationError as error:
        details = "; ".join(
            f"{'.'.join(map(str, item['loc'])) or '최상위 목록'}: {item['msg']}"
            for item in error.errors(include_input=False, include_url=False)
        )
        raise SourceManifestError(
            f"{manifest_path}: 출처 목록 형식 오류: {details}"
        ) from error

    seen: set[str] = set()
    for index, entry in enumerate(entries):
        if entry.ordinance_serial in seen:
            raise SourceManifestError(
                f"{manifest_path}: [{index}].일련번호 {entry.ordinance_serial!r}가 중복됩니다."
            )
        seen.add(entry.ordinance_serial)
    return entries


class SourceDocumentLoadError(ValueError):
    """본문 파일 또는 명시적으로 전달된 문서 메타데이터를 읽을 수 없다."""


class _BasicHTMLParser(HTMLParser):
    """전처리 HTML의 태그 존재와 명백한 잘림만 확인한다."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.has_element = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.has_element = True

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.has_element = True


def _read_content_file(path: Path) -> str:
    try:
        # BOM은 파일 인코딩 표식으로 처리하고, 본문의 줄바꿈과 들여쓰기는 그대로 둔다.
        with path.open(encoding="utf-8-sig", newline="") as handle:
            return handle.read()
    except UnicodeDecodeError as error:
        raise SourceDocumentLoadError(
            f"{path}: UTF-8 본문 파일이 필요합니다."
        ) from error


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"표준 JSON에서 허용하지 않는 값 {value!r}입니다.")


def _read_json_value(text: str, location: str) -> object:
    try:
        return json.loads(
            text,
            object_pairs_hook=_unique_json_keys,
            parse_constant=_reject_json_constant,
        )
    except json.JSONDecodeError as error:
        raise SourceDocumentLoadError(
            f"{location}: JSON 문법 오류 ({error.lineno}행 {error.colno}열): {error.msg}"
        ) from error
    except ValueError as error:
        raise SourceDocumentLoadError(f"{location}: {error}") from error


def _validate_document_content(document: SourceDocument, location: str) -> None:
    if not document.content.strip():
        raise SourceDocumentLoadError(f"{location}: content는 비어 있을 수 없습니다.")
    if document.content_format == "json":
        _read_json_value(document.content, location)
        return

    parser = _BasicHTMLParser()
    try:
        parser.feed(document.content)
        # HTMLParser는 close 시 미완성 태그도 텍스트로 처리하므로 그 전에 확인한다.
        if parser.rawdata.startswith("<"):
            raise ValueError("완성되지 않은 HTML 태그 또는 주석이 있습니다.")
        parser.close()
        if not parser.has_element:
            raise ValueError("HTML 본문에는 HTML 요소가 필요합니다.")
    except (ValueError, AssertionError) as error:
        raise SourceDocumentLoadError(
            f"{location}: HTML 기본 검사 오류: {error}"
        ) from error
    # HTML5 전체 문법, 표의 의미, 각주 연결을 검증하거나 HTML을 안전화하지 않는다.
    # 원문 대조와 화면 표시 시 HTML 처리 정책은 별도로 필요하다.


def _source_document_from_data(payload: object, location: str) -> SourceDocument:
    if not isinstance(payload, dict):
        raise SourceDocumentLoadError(f"{location}: 문서 한 건은 JSON 객체여야 합니다.")
    unknown = set(payload) - set(SourceDocument.model_fields)
    if unknown:
        raise SourceDocumentLoadError(
            f"{location}: SourceDocument에 없는 필드: {', '.join(sorted(unknown))}. "
            "출처 목록은 load_source_manifest로 읽고 본문은 별도로 제공해야 합니다."
        )
    try:
        document = SourceDocument.model_validate(payload)
    except ValidationError as error:
        details = "; ".join(
            f"{'.'.join(map(str, item['loc'])) or '문서'}: {item['msg']}"
            for item in error.errors(include_input=False, include_url=False)
        )
        raise SourceDocumentLoadError(
            f"{location}: 문서 규격 오류: {details}"
        ) from error
    for field in ("document_id", "version", "title", "source_url"):
        if not getattr(document, field).strip():
            raise SourceDocumentLoadError(
                f"{location}: {field}는 비어 있을 수 없습니다."
            )
    try:
        _validate_source_url(document.source_url)
    except ValueError as error:
        raise SourceDocumentLoadError(f"{location}: source_url: {error}") from error
    _validate_document_content(document, location)
    return document


def load_source_documents(path: str | Path) -> list[SourceDocument]:
    """명시한 JSON 파일에서 이미 본문과 메타데이터를 갖춘 문서들을 읽는다.

    JSON 배열 또는 {"documents": [...], "is_synthetic": ..., "description": ...}
    포장을 지원한다. 폴더를 탐색하거나 sources.json에서 본문/ID/버전을 추정하지 않는다.
    부모는 다른 파일에 있을 수 있으므로 존재 여부는 강제하지 않고 모델의 참조 형태만
    검사한다. 원본 저장 파일의 존재, HTML 의미 정확성, 이용 가능 여부는 검증하지 않는다.
    """
    source_path = Path(path)
    payload = _read_json_value(_read_content_file(source_path), str(source_path))
    if isinstance(payload, dict):
        unknown = set(payload) - {"documents", "is_synthetic", "description"}
        if unknown or "documents" not in payload:
            raise SourceDocumentLoadError(
                f"{source_path}: 문서 JSON 배열 또는 documents 목록이 필요합니다."
            )
        payload = payload["documents"]
    if not isinstance(payload, list):
        raise SourceDocumentLoadError(
            f"{source_path}: documents는 JSON 배열이어야 합니다."
        )

    documents: list[SourceDocument] = []
    seen: set[tuple[str, str, str]] = set()
    for index, row in enumerate(payload):
        location = f"{source_path}: documents[{index}]"
        document = _source_document_from_data(row, location)
        key = (document.document_id, document.version, document.content_format)
        if key in seen:
            raise SourceDocumentLoadError(
                f"{location}: 같은 문서/버전/형식이 중복됩니다: {key!r}"
            )
        seen.add(key)
        documents.append(document)
    return documents


def load_preprocessed_content(
    path: str | Path, *, metadata: Mapping[str, object]
) -> SourceDocument:
    """단일 HTML/JSON 본문 파일과 호출자가 제공한 출처 정보를 연결한다.

    파일명을 ID/버전/원본 경로로 해석하지 않는다. metadata에는 SourceDocument의
    content/content_format을 제외한 필수 값을 제공한다. 원본 raw_path를 생략하면
    모델 기본값 None을 유지한다. 본문은 UTF-8 BOM만 제외하고 원래 문자열을 보존한다.
    """
    source_path = Path(path)
    content_format = source_path.suffix.lower().removeprefix(".")
    if content_format not in {"html", "json"}:
        raise SourceDocumentLoadError(
            f"{source_path}: .html 또는 .json 본문 파일만 지원합니다."
        )
    forbidden = {"content", "content_format"}.intersection(metadata)
    if forbidden:
        raise SourceDocumentLoadError(
            f"{source_path}: metadata에 {', '.join(sorted(forbidden))}를 넣을 수 없습니다."
        )
    payload = dict(metadata)
    payload["content_format"] = content_format
    payload["content"] = _read_content_file(source_path)
    return _source_document_from_data(payload, str(source_path))
