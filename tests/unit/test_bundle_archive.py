"""자료 외 파일 배제와 손상된 인계 ZIP의 쓰기 중단을 검증한다."""

import hashlib
import json
from zipfile import ZipFile

import pytest

from src.ingestion.bundle_archive import extract_bundle


def archive(path, *, extra=None, corrupt=False):
    files = {
        "processed/body/example.json": b"{}",
        "code/do_not_run.py": b"raise RuntimeError()",
        "raw/example/body.xml": b"<LawService/>",
        "raw/example/search_1.xml": b"private-search",
    }
    files.update(extra or {})
    manifest = {
        "schema_version": "jungeun-handoff-bundle-v2",
        "files": [
            {
                "path": name,
                "size_bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
            for name, data in files.items()
        ],
    }
    if corrupt:
        files["processed/body/example.json"] = b"bad"
    with ZipFile(path, "w") as zipped:
        zipped.writestr("bundle/bundle_manifest.json", json.dumps(manifest))
        for name, data in files.items():
            zipped.writestr("bundle/" + name, data)


def test_archive_only_copies_data_and_refuses_overwrite(tmp_path):
    path, target = tmp_path / "data.zip", tmp_path / "input"
    archive(path)
    assert extract_bundle(path, target) == target
    assert (target / "processed/body/example.json").exists()
    assert not (target / "code").exists()
    assert not (target / "raw/example/search_1.xml").exists()
    with pytest.raises(FileExistsError):
        extract_bundle(path, target)


@pytest.mark.parametrize(
    "extra,corrupt",
    [({"../escape.json": b"{}"}, False), ({"C:/bad": b"{}"}, False), ({}, True)],
)
def test_bad_archive_does_not_write_partial_data(tmp_path, extra, corrupt):
    path, target = tmp_path / "data.zip", tmp_path / "input"
    archive(path, extra=extra, corrupt=corrupt)
    with pytest.raises(ValueError):
        extract_bundle(path, target)
    assert not target.exists()
