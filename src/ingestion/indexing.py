"""청크 전체에서 새 색인 스냅샷을 만든다. 이전 색인과 자동 병합하지 않는다."""

from dataclasses import dataclass, field
import hashlib
import json

from src.contracts import Chunk
from src.infrastructure.embeddings import EmbeddingProvider
from src.infrastructure.stores import (
    IndexEntry, IndexMetadata, IndexSnapshot, source_versions, validate_vector,
)


@dataclass
class MemoryEmbeddingCache:
    """같은 객체를 다음 build에 전달하면 재사용. 프로세스 종료 시 사라진다.

    정확한 본문과 모델/설정 identity를 함께 키로 쓴다. 출처와 청크 ID는 합치지 않는다.
    """

    vectors: dict[tuple[str, str], list[float]] = field(default_factory=dict)


def build_index(
    chunks: list[Chunk], embedder: EmbeddingProvider,
    *, cache: MemoryEmbeddingCache | None = None,
) -> IndexSnapshot:
    if not chunks:
        raise ValueError("색인을 만들 청크가 없습니다.")
    identity = embedder.identity
    if not isinstance(identity, str) or not identity.strip():
        raise ValueError("임베딩 provider identity가 필요합니다.")
    if len({chunk.chunk_id for chunk in chunks}) != len(chunks):
        raise ValueError("chunk_id가 중복되었습니다.")
    versions = {chunk.chunking_version for chunk in chunks}
    if len(versions) != 1:
        raise ValueError("한 색인은 같은 청킹 버전으로 만들어야 합니다.")
    cache = cache if cache is not None else MemoryEmbeddingCache()
    texts = list(dict.fromkeys(chunk.content for chunk in chunks))
    missing = [text for text in texts if (identity, text) not in cache.vectors]
    generated = embedder.embed_documents(missing) if missing else []
    if not isinstance(generated, list) or len(generated) != len(missing):
        raise ValueError("임베딩 결과 개수가 요청한 본문 개수와 다릅니다.")
    pending = {text: validate_vector(vector) for text, vector in zip(missing, generated)}
    vectors = {text: pending[text] if text in pending else validate_vector(
        cache.vectors[identity, text]
    ) for text in texts}
    dimensions = {len(vector) for vector in vectors.values()}
    if len(dimensions) != 1:
        raise ValueError("임베딩 결과의 벡터 차원이 서로 다릅니다.")
    entries = [IndexEntry(chunk=chunk, vector=vectors[chunk.content]) for chunk in chunks]
    signature = json.dumps(
        {"embedding_identity": identity, "entries": [entry.model_dump() for entry in entries]},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    snapshot = IndexSnapshot(
        metadata=IndexMetadata(
            index_id="index-" + hashlib.sha256(signature.encode()).hexdigest(),
            embedding_identity=identity, dimension=dimensions.pop(),
            chunking_version=versions.pop(), source_document_versions=source_versions(chunks),
        ), entries=entries,
    )
    # 전체 결과를 검사한 뒤에만 캐시에 반영하여 실패한 배치를 남기지 않는다.
    cache.vectors.update({(identity, text): vector[:] for text, vector in pending.items()})
    return snapshot
