"""합성 원본으로 검수 재적용·버전 범위·입력 보존 검사."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from src.ingestion.annexes import (
    apply_review_overlay,
    load_review_overlays,
    preprocess_attachments,
)


@pytest.fixture
def source_and_overlay(tmp_path: Path) -> tuple[Path, Path, dict]:
    folder = tmp_path / "source-run" / "attachments"
    folder.mkdir(parents=True)
    raw = b"synthetic-hwp-for-overlay-test"
    (folder / "123_456.hwp").write_bytes(raw)
    record = {
        "parent_mst": "123",
        "attachment_id": "456",
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "raw_path": "attachments/123_456.hwp",
        "download_status": "downloaded",
        "deleted_marker": False,
        "title": "합성 별표",
    }
    manifest = folder / "manifest.json"
    manifest.write_text(json.dumps({"source_run_id": "test", "records": [record]}))
    overlay = {
        **{k: record[k] for k in ("parent_mst", "attachment_id", "raw_sha256")},
        "updates": {
            "content_role": "signage_specification",
            "human_review_status": "classification_confirmed",
            "human_review": {"reviewer": "synthetic-test", "decision": "합성 검수"},
            "structured_image_summary": {"fixture": "합성 그림 설명"},
            "retrieval_decision": "exclude_from_item_disposal_search",
        },
    }
    path = tmp_path / "review-overlays.json"
    path.write_text(json.dumps({"records": [overlay]}, ensure_ascii=False))
    return manifest, path, overlay


def fake_conversion(_args, *, stdout, **_kwargs):
    """외부 변환 대신 최소 구조 XML 반환."""
    stdout.write(
        b"<HwpDoc><BodyText><Paragraph><Text>test</Text>"
        b"</Paragraph></BodyText></HwpDoc>"
    )


def test_reextraction_reapplies_reviews_without_changing_inputs(
    source_and_overlay, tmp_path, monkeypatch
):
    manifest, overlay_path, overlay = source_and_overlay
    before_manifest = manifest.read_bytes()
    before_overlay = overlay_path.read_bytes()
    monkeypatch.setattr("src.ingestion.annexes.subprocess.run", fake_conversion)
    for name in ("first", "again"):
        output = tmp_path / name
        summary = preprocess_attachments(manifest, output, overlay_path)
        result = json.loads((output / "123_456.json").read_text())
        for field, expected in overlay["updates"].items():
            assert result[field] == expected
            assert summary["records"][0][field] == expected
        assert result["usage_status"] == "index_and_model_use_unreviewed"
    assert manifest.read_bytes() == before_manifest
    assert overlay_path.read_bytes() == before_overlay


def test_optional_overlay_keeps_original_pending_behavior(
    source_and_overlay, tmp_path, monkeypatch
):
    manifest, _, _ = source_and_overlay
    monkeypatch.setattr("src.ingestion.annexes.subprocess.run", fake_conversion)
    output = tmp_path / "unreviewed"
    preprocess_attachments(manifest, output)
    result = json.loads((output / "123_456.json").read_text())
    assert result["human_review_status"] == "pending"
    assert result["content_role"] == "annex"
    assert "human_review" not in result


@pytest.mark.parametrize(
    "invalid", ["hash", "duplicate", "unmatched", "field", "shape"]
)
def test_invalid_overlay_stops_before_output_or_conversion(
    source_and_overlay, tmp_path, monkeypatch, invalid
):
    manifest, overlay_path, overlay = source_and_overlay
    overlay = deepcopy(overlay)
    records = [overlay]
    if invalid == "hash":
        overlay["raw_sha256"] = "0" * 64
    elif invalid == "duplicate":
        records.append(deepcopy(overlay))
    elif invalid == "unmatched":
        overlay["attachment_id"] = "999"
    elif invalid == "field":
        overlay["updates"]["usage_status"] = "approved"
    else:
        overlay["updates"]["human_review"] = "not-a-record"
    overlay_path.write_text(json.dumps({"records": records}))
    output = tmp_path / "invalid-output"

    def unexpected_conversion(*_args, **_kwargs):
        pytest.fail("잘못된 검수에 외부 변환 실행")

    monkeypatch.setattr("src.ingestion.annexes.subprocess.run", unexpected_conversion)
    with pytest.raises(ValueError):
        preprocess_attachments(manifest, output, overlay_path)
    assert not output.exists()


def test_apply_returns_independent_copy(source_and_overlay):
    manifest, overlay_path, _ = source_and_overlay
    source = json.loads(manifest.read_text())["records"][0]
    original = deepcopy(source)
    overlay = load_review_overlays(overlay_path, [source])["123", "456"]
    original_overlay = deepcopy(overlay)
    updated = apply_review_overlay(source, overlay)
    updated["human_review"]["reviewer"] = "changed-copy"
    assert source == original
    assert overlay == original_overlay
