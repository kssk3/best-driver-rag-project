"""파일 입력부터 청크까지 출처, 표현 형식, 표와 예외 조건을 보존하는지 확인한다."""

import json
from pathlib import Path

import pytest

from src.contracts import SourceDocument
from src.ingestion.chunking import chunk_documents
from src.ingestion.loaders import (
    SourceDocumentLoadError,
    load_preprocessed_content,
    load_source_documents,
    load_source_manifest,
)


FIXTURES = Path(__file__).parents[1] / "fixtures"
HTML_CONTENT = (
    '<table><tr><th>품목</th><th>안내</th></tr>\r\n'
    '<tr><td>합성 품목 A</td><td>합성 안내 B</td></tr></table>\r\n'
    '<p>비고: 합성 조건 X일 때 적용. 합성 조건 Y는 제외.</p>'
)
JSON_CONTENT = (
    '{\r\n  "rows": [{"item": "합성 품목 A", "guidance": "합성 안내 B"}],\r\n'
    '  "notes": ["합성 조건 X일 때 적용"], "exceptions": ["합성 조건 Y 제외"]\r\n}'
)


@pytest.fixture
def metadata():
    return {
        "document_id": "synthetic-annex-2",
        "version": "source-revision-1",
        "title": "합성 표와 비고",
        "source_url": "https://example.org/annex-2.hwp",
        "scope_type": "district",
        "districts": ["서대문구"],
        "parent_document_id": "synthetic-ordinance",
        "parent_document_version": "parent-revision-3",
    }


def write_document_bundle(path, rows):
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.mark.parametrize(("suffix", "content"), [("html", HTML_CONTENT), ("json", JSON_CONTENT)])
def test_input_table_notes_and_metadata_survive_loading_and_chunking(tmp_path, metadata, suffix, content):
    path = tmp_path / f"input.{suffix}"
    path.write_bytes(("\ufeff" + content).encode("utf-8"))

    document = load_preprocessed_content(path, metadata=metadata)
    [chunk] = chunk_documents([document])

    assert document.content == content
    assert chunk.content == content
    assert document.content_format == chunk.content_format == suffix
    assert document.raw_path is None
    assert chunk.source_document_id == metadata["document_id"]
    assert chunk.source_document_version == metadata["version"]
    assert chunk.source_document_version != document.parent_document_version
    assert chunk.source_url == metadata["source_url"]
    assert chunk.title == metadata["title"]
    assert chunk.scope_type == metadata["scope_type"]
    assert chunk.districts == metadata["districts"]
    assert chunk.source_location == "문서 전체"
    assert chunk.conditions == []


def test_existing_fixture_variants_load_as_separate_stable_chunks():
    documents = load_source_documents(FIXTURES / "preprocessing_variants.json")
    first = chunk_documents(documents)
    second = chunk_documents(documents)

    assert len(first) == 2
    assert {chunk.content_format for chunk in first} == {"html", "json"}
    assert len({chunk.chunk_id for chunk in first}) == 2
    assert [chunk.model_dump() for chunk in first] == [chunk.model_dump() for chunk in second]
    assert [chunk.content for chunk in first] == [document.content for document in documents]


def test_family_fixture_keeps_direct_attachment_sources():
    documents = load_source_documents(FIXTURES / "source_document_family.json")
    chunks = chunk_documents(documents)
    assert len(chunks) == len(documents) == 3
    for document, chunk in zip(documents, chunks, strict=True):
        assert chunk.source_document_id == document.document_id
        assert chunk.source_document_version == document.version
        if document.parent_document_id is not None:
            assert chunk.source_document_id != document.parent_document_id


@pytest.mark.parametrize(
    "change",
    [
        {"document_id": "synthetic-other-source"},
        {"version": "source-revision-2"},
        {"source_url": "https://example.org/other-source.hwp"},
        {"content": HTML_CONTENT + "<p>추가 합성 예외</p>"},
    ],
)
def test_source_or_content_changes_produce_different_chunk_ids(metadata, change):
    base = {**metadata, "content_format": "html", "content": HTML_CONTENT}
    [original] = chunk_documents([SourceDocument(**base)])
    [changed] = chunk_documents([SourceDocument(**{**base, **change})])
    assert original.chunk_id != changed.chunk_id


def test_chunking_version_changes_chunk_identity(metadata):
    document = SourceDocument(**metadata, content_format="html", content=HTML_CONTENT)
    [original] = chunk_documents([document])
    [changed] = chunk_documents([document], chunking_version="whole-document-v2")
    assert original.chunk_id != changed.chunk_id


def test_oversized_document_is_rejected_without_truncating_or_splitting(metadata):
    document = SourceDocument(**metadata, content_format="html", content=HTML_CONTENT)
    with pytest.raises(ValueError, match=metadata["document_id"]):
        chunk_documents([document], max_characters=len(HTML_CONTENT) - 1)
    [chunk] = chunk_documents([document], max_characters=len(HTML_CONTENT))
    assert chunk.content == HTML_CONTENT


@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
def test_invalid_chunk_limits_are_rejected(limit):
    with pytest.raises(ValueError, match="max_characters"):
        chunk_documents([], max_characters=limit)


def test_array_bundle_preserves_parent_reference_without_requiring_parent_in_file(tmp_path, metadata):
    row = {**metadata, "content_format": "html", "content": HTML_CONTENT}
    path = write_document_bundle(tmp_path / "documents.json", [row])
    [document] = load_source_documents(path)
    assert document.parent_document_id == metadata["parent_document_id"]
    assert document.parent_document_version == metadata["parent_document_version"]


def test_duplicate_source_representation_is_rejected_by_loader_and_chunker(tmp_path, metadata):
    row = {**metadata, "content_format": "html", "content": HTML_CONTENT}
    path = write_document_bundle(tmp_path / "duplicates.json", [row, row])
    with pytest.raises(SourceDocumentLoadError, match="중복"):
        load_source_documents(path)
    document = SourceDocument(**row)
    with pytest.raises(ValueError, match="중복"):
        chunk_documents([document, document])


@pytest.mark.parametrize(
    ("suffix", "content"),
    [
        ("html", "  \r\n"),
        ("html", "<table><tr"),
        ("html", "합성 일반 텍스트"),
        ("json", '{"rows": '),
        ("json", '{"rows": [], "rows": [1]}'),
        ("json", '{"value": NaN}'),
        ("json", '{"value": Infinity}'),
    ],
)
def test_bad_content_reports_the_file_path(tmp_path, metadata, suffix, content):
    path = tmp_path / f"invalid.{suffix}"
    path.write_bytes(content.encode("utf-8"))
    with pytest.raises(SourceDocumentLoadError) as error:
        load_preprocessed_content(path, metadata=metadata)
    assert str(path) in str(error.value)


@pytest.mark.parametrize("field", ["content", "content_format"])
def test_metadata_cannot_override_file_content_or_format(tmp_path, metadata, field):
    path = tmp_path / "input.html"
    path.write_text(HTML_CONTENT, encoding="utf-8")
    with pytest.raises(SourceDocumentLoadError, match=field):
        load_preprocessed_content(path, metadata={**metadata, field: "override"})


def test_missing_metadata_is_not_guessed_from_filename(tmp_path, metadata):
    path = tmp_path / "guessed-doc-v1.html"
    path.write_text(HTML_CONTENT, encoding="utf-8")
    del metadata["version"]
    with pytest.raises(SourceDocumentLoadError, match="version"):
        load_preprocessed_content(path, metadata=metadata)


def test_source_manifest_remains_a_separate_input_type():
    manifest_path = FIXTURES / "source_manifest.json"
    entries = load_source_manifest(manifest_path)
    assert entries
    assert any(entry.attachments for entry in entries)
    with pytest.raises(SourceDocumentLoadError, match="load_source_manifest"):
        load_source_documents(manifest_path)


@pytest.mark.parametrize("payload", [{"rows": []}, {"documents": {}}, None])
def test_document_bundle_requires_an_explicit_document_list(tmp_path, payload):
    path = write_document_bundle(tmp_path / "wrong-shape.json", payload)
    with pytest.raises(SourceDocumentLoadError):
        load_source_documents(path)


def test_filesystem_and_encoding_errors_are_not_hidden(tmp_path, metadata):
    with pytest.raises(FileNotFoundError):
        load_source_documents(tmp_path / "missing.json")
    with pytest.raises(OSError):
        load_source_documents(tmp_path)
    path = tmp_path / "not-utf8.html"
    path.write_bytes(b"\xff\xfe\x00\x01")
    with pytest.raises(SourceDocumentLoadError, match="UTF-8"):
        load_preprocessed_content(path, metadata=metadata)


def test_source_documents_do_not_silently_drop_unknown_metadata(tmp_path, metadata):
    row = {**metadata, "content_format": "html", "content": HTML_CONTENT, "unreviewed_field": 1}
    path = write_document_bundle(tmp_path / "unknown.json", [row])
    with pytest.raises(SourceDocumentLoadError, match="unreviewed_field"):
        load_source_documents(path)
