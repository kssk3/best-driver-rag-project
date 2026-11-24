"""표와 각주를 유지하는 최소 청킹. 문서 전체를 하나의 청크로 전달한다.

담당: 양석호
표의 행이나 문장을 임의로 자르면 공통 비고와 예외 조건이 떨어질 수 있어,
초기 인계본은 입력 문서 한 건의 전체 본문을 보존한다. 품목별 분할은 후속 구현이다.
"""

import hashlib
import json
from collections.abc import Iterable

from src.contracts import Chunk, SourceDocument


def chunk_documents(
    documents: Iterable[SourceDocument],
    *,
    max_characters: int = 20_000,
    chunking_version: str = "whole-document-v1",
) -> list[Chunk]:
    """문서마다 청크 하나를 만들고 한도를 넘는 문서는 명확하게 거부한다.

    max_characters는 Python 문자열의 문자 수이며 모델 토큰 한도가 아니다.
    초과 문서의 일부를 버리거나 자동 분할하지 않는다. HTML/JSON 내용과 출처를
    그대로 보존하며 conditions 목록은 자동 추출하지 않는다.
    """
    if isinstance(max_characters, bool) or not isinstance(max_characters, int) or max_characters < 1:
        raise ValueError("max_characters는 1 이상의 정수여야 합니다.")
    if not isinstance(chunking_version, str) or not chunking_version.strip():
        raise ValueError("chunking_version은 비어 있지 않은 문자열이어야 합니다.")

    chunks: list[Chunk] = []
    seen: set[tuple[str, str, str]] = set()
    for document in documents:
        if not isinstance(document, SourceDocument):
            raise TypeError("chunk_documents에는 SourceDocument 목록이 필요합니다.")
        source_key = (document.document_id, document.version, document.content_format)
        if source_key in seen:
            raise ValueError(f"같은 문서/버전/형식이 중복됩니다: {source_key!r}")
        seen.add(source_key)
        if not document.content.strip():
            raise ValueError(f"문서 {document.document_id!r}의 content가 비어 있습니다.")
        if len(document.content) > max_characters:
            raise ValueError(
                f"문서 {document.document_id!r} ({document.version}/{document.content_format})가 "
                f"문자 수 한도 {max_characters}를 초과했습니다: {len(document.content)}. "
                "표와 비고를 보존할 분할 정책 또는 명시적인 한도 조정이 필요합니다."
            )

        # 같은 입력과 청킹 규칙이면 ID가 유지된다. HTML/JSON이나 원문 버전이
        # 달라지면 별도 결과가 되며, 원문 URL이 다른 출처도 구분한다.
        identity = {
            "document_id": document.document_id,
            "version": document.version,
            "content_format": document.content_format,
            "content": document.content,
            "source_url": document.source_url,
            "chunking_version": chunking_version,
        }
        digest = hashlib.sha256(
            json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        chunks.append(
            Chunk(
                chunk_id=f"chunk-{digest}",
                source_document_id=document.document_id,
                source_document_version=document.version,
                title=document.title,
                content_format=document.content_format,
                content=document.content,
                source_url=document.source_url,
                source_location="문서 전체",
                scope_type=document.scope_type,
                districts=list(document.districts),
                # 조건을 없다고 판단한 것이 아니라 별도 구조화하지 않은 상태다.
                # 조건과 예외의 본문은 content에 그대로 남긴다.
                conditions=[],
                chunking_version=chunking_version,
            )
        )
    return chunks
