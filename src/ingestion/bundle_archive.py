"""전처리 인계 ZIP에서 입력 자료만 보관한다. 수집/전처리 코드는 실행하지 않는다."""

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
from zipfile import ZipFile


def extract_bundle(archive: Path, destination: Path) -> Path:
    """해시를 대조한 XML/JSON/HWP와 목록만 새 폴더에 저장한다.

    HWP는 raw_path로 참조할 보관 원본이다. 직접 파싱하지 않는다.
    검색 응답 XML, 코드, 리뷰 화면과 미리보기는 RAG 입력에 포함하지 않는다.
    """
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError("기존 입력 폴더를 덮어쓸 수 없습니다.")
    with ZipFile(archive) as zipped:
        infos = [info for info in zipped.infolist() if not info.is_dir()]
        if len(infos) > 2000 or sum(i.file_size for i in infos) > 100_000_000:
            raise ValueError("인계 ZIP 크기 또는 파일 수 한도를 초과했습니다.")
        names = [i.filename for i in infos]
        if len(set(names)) != len(names):
            raise ValueError("ZIP에 중복 경로가 있습니다.")
        manifests = [n for n in names if n.endswith("/bundle_manifest.json") or n == "bundle_manifest.json"]
        if len(manifests) != 1:
            raise ValueError("하나의 bundle_manifest.json이 필요합니다.")
        prefix = manifests[0][:-len("bundle_manifest.json")]
        for info in infos:
            path = PurePosixPath(info.filename)
            if (path.is_absolute() or ".." in path.parts or "\\" in info.filename
                    or ":" in info.filename or not info.filename.startswith(prefix)
                    or stat.S_ISLNK(info.external_attr >> 16)):
                raise ValueError("ZIP에 지원하지 않는 경로가 있습니다.")
        manifest = json.loads(zipped.read(manifests[0]))
        if manifest.get("schema_version") != "jungeun-handoff-bundle-v2":
            raise ValueError("지원하지 않는 인계 ZIP 규격입니다.")
        listed = {}
        for item in manifest["files"]:
            path = item["path"]
            if path in listed:
                raise ValueError("번들 목록에 중복 경로가 있습니다.")
            listed[path] = item
        expected = {n[len(prefix):] for n in names if n != manifests[0]}
        if set(listed) != expected:
            raise ValueError("ZIP과 번들 파일 목록이 다릅니다.")
        selected = {}
        for path, item in listed.items():
            data = zipped.read(prefix + path)
            if len(data) != item["size_bytes"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
                raise ValueError("번들 파일 크기 또는 SHA256이 다릅니다.")
            if (re.fullmatch(r"processed/(body|annex)/[A-Za-z0-9_-]+\.(json|xml)", path)
                    or re.fullmatch(r"raw/[A-Za-z0-9_-]+/body\.xml", path)
                    or re.fullmatch(r"raw/attachments/[0-9_]+\.hwp", path)
                    or path in {"raw/manifest.json", "raw/attachments/manifest.json",
                                "review/human_review_overlays.json", "review/review_status.json"}):
                selected[path] = data
        if not selected:
            raise ValueError("전처리 입력 파일이 없습니다.")
        destination.mkdir(parents=True, exist_ok=False)
        (destination / "bundle_manifest.json").write_bytes(zipped.read(manifests[0]))
        for path, data in selected.items():
            target = destination / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        (destination / "import_manifest.json").write_text(json.dumps({
            "archive_sha256": hashlib.sha256(Path(archive).read_bytes()).hexdigest(),
            "verified_files": len(listed), "stored_files": sorted(selected),
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return destination
