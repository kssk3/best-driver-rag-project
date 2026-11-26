"""청크 집합 지문(src/ingestion/chunk_fingerprint.py) 테스트. 합성 청크만 사용한다."""

from src.contracts import Chunk
from src.ingestion.chunk_fingerprint import chunks_fingerprint


def make_chunk(chunk_id: str, **changes) -> Chunk:
    base = dict(
        chunk_id=chunk_id,
        source_document_id="doc-a",
        source_document_version="v1",
        title="합성 제목",
        content_format="html",
        content=f"<p>{chunk_id}</p>",
        source_url="https://example.invalid/a",
        source_location="조문/조[1]",
        scope_type="district",
        districts=["서대문구"],
        chunking_version="v1",
    )
    return Chunk(**(base | changes))


CHUNKS = [make_chunk("c1"), make_chunk("c2")]


def test_chunk_models_and_their_json_dicts_give_the_same_fingerprint() -> None:
    as_dicts = [c.model_dump(mode="json") for c in CHUNKS]
    assert chunks_fingerprint(CHUNKS) == chunks_fingerprint(as_dicts)


def test_fingerprint_ignores_order() -> None:
    assert chunks_fingerprint(CHUNKS) == chunks_fingerprint(reversed(CHUNKS))


def test_fingerprint_changes_with_fields_that_are_not_in_the_chunk_id() -> None:
    first = chunks_fingerprint(CHUNKS)
    for change in (
        {"title": "다른 제목"},
        {"districts": ["송파구"]},
        {"conditions": ["일반주택"]},
    ):
        assert chunks_fingerprint([make_chunk("c1", **change), CHUNKS[1]]) != first
