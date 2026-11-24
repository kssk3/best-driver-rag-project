"""XML 인라인 내용 유무와 첨부 파일 확보·추출 상태의 구분 검사."""

import hashlib
import json

from src.ingestion.annexes import preprocess_attachments


def test_download_and_extraction_do_not_inherit_ambiguous_xml_flags(
    tmp_path, monkeypatch
):
    attachments = tmp_path / "run" / "attachments"
    attachments.mkdir(parents=True)
    raw = b"synthetic attachment"
    (attachments / "123_456.hwp").write_bytes(raw)
    source = {
        "parent_mst": "123",
        "attachment_id": "456",
        "title": "합성 별표",
        "deleted_marker": False,
        "collection_status": "link_only",
        "content_present": False,
        "download_status": "downloaded",
        "raw_path": "attachments/123_456.hwp",
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
    }
    path = attachments / "manifest.json"
    path.write_text(json.dumps({"source_run_id": "synthetic", "records": [source]}))
    before = path.read_bytes()

    def convert(_args, *, stdout, **_kwargs):
        stdout.write(
            b"<HwpDoc><BodyText><Paragraph><Text>readable content</Text>"
            b"</Paragraph></BodyText></HwpDoc>"
        )

    monkeypatch.setattr("src.ingestion.annexes.subprocess.run", convert)
    output = tmp_path / "processed"
    summary = preprocess_attachments(path, output)
    result = json.loads((output / "123_456.json").read_text())
    assert "collection_status" not in result
    assert "content_present" not in result
    assert result["xml_listing"]["collection_status"] == "link_only"
    assert result["xml_listing"]["content_present"] is False
    assert result["download_status"] == "downloaded"
    assert result["processing_status"] == "structure_extracted_pending_review"
    assert result["extracted_text_present"] is True
    assert result["schema_version"] == "jungeun-annex-draft-v2"
    assert summary["records"][0]["extracted_text_present"] is True
    assert path.read_bytes() == before
