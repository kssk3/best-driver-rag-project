"""원문 문서의 적용 범위와 부모 문서 연결에 대한 계약 검사."""

import json
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.contracts import SourceDocument


@pytest.fixture
def document_data() -> dict[str, str]:
    return {
        "document_id": "synthetic-doc-001",
        "version": "v1",
        "title": "합성 검증용 분리배출 안내",
        "content_format": "html",
        "content": "<p>실제 배출 규칙이 아닌 합성 검증용 안내 본문</p>",
        "source_url": "https://example.org/recycling-guide.pdf",
    }


@pytest.mark.parametrize(
    ("scope_type", "districts"),
    [
        ("district", ["서대문구"]),
        ("district", ["서대문구", "송파구"]),
        ("common", []),
        ("unknown", []),
    ],
)
def test_scope_survives_serialization(document_data, scope_type, districts):
    document = SourceDocument(
        **document_data, scope_type=scope_type, districts=districts
    )

    restored = SourceDocument.model_validate_json(document.model_dump_json())

    assert restored.scope_type == scope_type
    assert restored.districts == districts


@pytest.mark.parametrize(
    ("scope_type", "districts", "message"),
    [
        ("district", [], "구 이름이 필요"),
        ("district", [""], "구 이름이 필요"),
        ("district", ["송파구", "  "], "구 이름이 필요"),
        ("common", ["송파구"], "빈 목록이어야"),
        ("unknown", ["송파구"], "빈 목록이어야"),
    ],
)
def test_inconsistent_scope_is_rejected(document_data, scope_type, districts, message):
    with pytest.raises(ValidationError, match=message):
        SourceDocument(**document_data, scope_type=scope_type, districts=districts)


def test_document_without_parent_keeps_both_references_empty(document_data):
    document = SourceDocument(
        **document_data, scope_type="district", districts=["송파구"]
    )

    assert document.parent_document_id is None
    assert document.parent_document_version is None
    assert document.raw_path is None


def test_attachments_reference_exact_parent_version():
    fixture_path = (
        Path(__file__).parents[1] / "fixtures" / "source_document_family.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert fixture["is_synthetic"] is True
    parent, *attachments = [
        SourceDocument.model_validate(row) for row in fixture["documents"]
    ]
    assert parent.effective_date == date(2025, 12, 31)
    assert attachments[0].effective_date is None

    for attachment in attachments:
        restored = SourceDocument.model_validate_json(attachment.model_dump_json())
        assert (restored.parent_document_id, restored.parent_document_version) == (
            parent.document_id,
            parent.version,
        )
        assert restored.document_id != parent.document_id
        assert restored.source_url != parent.source_url
        assert restored.version != parent.version
        assert restored.title == attachment.title
        assert restored.title != parent.title
        assert restored.effective_date == attachment.effective_date
        assert restored.raw_path == attachment.raw_path
        assert restored.content_format == attachment.content_format
        assert restored.content == attachment.content


@pytest.mark.parametrize(
    ("parent_id", "parent_version", "message"),
    [
        ("parent-001", None, "함께 입력"),
        (None, "v1", "함께 입력"),
        ("", "v1", "빈 문자열"),
        ("  ", "v1", "빈 문자열"),
        ("parent-001", "", "빈 문자열"),
        ("parent-001", "  ", "빈 문자열"),
        ("synthetic-doc-001", "v1", "자기 자신"),
    ],
)
def test_invalid_parent_references_are_rejected(
    document_data, parent_id, parent_version, message
):
    with pytest.raises(ValidationError, match=message):
        SourceDocument(
            **document_data,
            scope_type="district",
            districts=["송파구"],
            parent_document_id=parent_id,
            parent_document_version=parent_version,
        )


def test_source_metadata_alone_does_not_create_an_extracted_document(document_data):
    del document_data["content"]

    with pytest.raises(ValidationError) as error:
        SourceDocument(**document_data, scope_type="district", districts=["송파구"])

    assert any(item["loc"] == ("content",) for item in error.value.errors())


@pytest.mark.parametrize(
    ("raw_path", "expected"),
    [
        (None, None),
        ("data/raw/조례.xml", "data/raw/조례.xml"),
        (r"data\raw\별표.hwp", "data/raw/별표.hwp"),
    ],
)
def test_raw_path_is_portable_and_survives_serialization(
    document_data, raw_path, expected
):
    document = SourceDocument(
        **document_data, scope_type="district", districts=["송파구"], raw_path=raw_path
    )

    restored = SourceDocument.model_validate_json(document.model_dump_json())

    assert restored.raw_path == expected


@pytest.mark.parametrize(
    "raw_path",
    [
        "",
        "  ",
        ".",
        "../source.xml",
        "data/../source.xml",
        r"data\..\source.hwp",
        "/tmp/source.xml",
        r"C:\raw\source.hwp",
        "C:source.hwp",
        r"\raw\source.hwp",
        r"\\server\share\source.pdf",
        "https://example.org/source.pdf",
        "file:///tmp/source.pdf",
        "data/raw/source\0.pdf",
    ],
)
def test_non_project_raw_paths_are_rejected(document_data, raw_path):
    with pytest.raises(ValidationError, match="raw_path"):
        SourceDocument(
            **document_data,
            scope_type="district",
            districts=["송파구"],
            raw_path=raw_path,
        )


def test_preprocessing_variants_preserve_original_identity_and_content():
    fixture_path = (
        Path(__file__).parents[1] / "fixtures" / "preprocessing_variants.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert fixture["is_synthetic"] is True
    documents = [SourceDocument.model_validate(row) for row in fixture["documents"]]

    assert {document.content_format for document in documents} == {"html", "json"}
    assert (
        len({(document.document_id, document.version) for document in documents}) == 1
    )
    assert len({document.source_url for document in documents}) == 1
    assert len({document.raw_path for document in documents}) == 1
    for document, source in zip(documents, fixture["documents"], strict=True):
        restored = SourceDocument.model_validate_json(document.model_dump_json())
        assert restored.content_format == source["content_format"]
        assert restored.content == source["content"]


@pytest.mark.parametrize("content_format", ["pdf", "hwp", "xml"])
def test_original_file_type_is_not_used_as_preprocessing_format(
    document_data, content_format
):
    document_data["content_format"] = content_format

    with pytest.raises(ValidationError) as error:
        SourceDocument(**document_data, scope_type="district", districts=["송파구"])

    assert any(item["loc"] == ("content_format",) for item in error.value.errors())
