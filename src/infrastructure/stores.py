"""명시한 로컬 JSON 색인만 읽고 원자적으로 교체한다. 운영 DB 선택과는 별개다."""

import math
import os
import tempfile
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.contracts import Chunk


def validate_vector(value) -> list[float]:
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError("벡터는 비어 있지 않은 수치 목록이어야 합니다.")
    if any(type(number) not in (float, int) for number in value):
        raise ValueError("벡터에는 유한한 수치만 사용할 수 있습니다.")
    try:
        normalized = [float(number) for number in value]
    except OverflowError as error:
        raise ValueError("벡터 수치가 지원 범위를 초과했습니다.") from error
    if not all(math.isfinite(number) for number in normalized):
        raise ValueError("벡터에는 유한한 수치만 사용할 수 있습니다.")
    return normalized


class SourceVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str
    version: str
    content_format: Literal["html", "json"]


class IndexMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["local-index-v1"] = "local-index-v1"
    index_id: str = Field(min_length=1)
    embedding_identity: str = Field(min_length=1)
    dimension: int = Field(gt=0, strict=True)
    chunking_version: str = Field(min_length=1)
    source_document_versions: list[SourceVersion]


class IndexEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chunk: Chunk
    vector: list[float]

    @field_validator("vector", mode="before")
    @classmethod
    def _check_vector(cls, value):
        return validate_vector(value)


def source_versions(chunks: list[Chunk]) -> list[SourceVersion]:
    keys = {
        (c.source_document_id, c.source_document_version, c.content_format)
        for c in chunks
    }
    return [
        SourceVersion(document_id=i, version=v, content_format=f)
        for i, v, f in sorted(keys)
    ]


class IndexSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metadata: IndexMetadata
    entries: list[IndexEntry] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_consistency(self) -> Self:
        chunks = [entry.chunk for entry in self.entries]
        if len({chunk.chunk_id for chunk in chunks}) != len(chunks):
            raise ValueError("색인 안의 chunk_id는 고유해야 합니다.")
        if any(len(entry.vector) != self.metadata.dimension for entry in self.entries):
            raise ValueError("벡터 차원이 색인 메타데이터와 다릅니다.")
        if {chunk.chunking_version for chunk in chunks} != {
            self.metadata.chunking_version
        }:
            raise ValueError("청킹 버전과 색인 메타데이터가 다릅니다.")
        if self.metadata.source_document_versions != source_versions(chunks):
            raise ValueError("문서 버전 목록과 색인 내용이 다릅니다.")
        return self


def save_index(index: IndexSnapshot, path: str | Path) -> None:
    # 가변 목록이 생성 후 바뀌었더라도 기존 파일을 건드리기 전에 재검사한다.
    checked = IndexSnapshot.model_validate(index.model_dump())
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(checked.model_dump_json(indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def load_index(path: str | Path) -> IndexSnapshot:
    return IndexSnapshot.model_validate_json(Path(path).read_text(encoding="utf-8-sig"))
