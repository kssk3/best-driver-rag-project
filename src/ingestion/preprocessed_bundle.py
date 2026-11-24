"""PR 8의 전처리 묶음을 JSON과 XML 유래 HTML의 동일 문서 쌍으로 읽는다.

수집과 HWP 추출을 다시 수행하지 않는다. 원문/변환 XML의 해시와 부모 관계를
검사하고, 제공된 JSON 문자열과 검수 범위를 그대로 보존한다. 원문 버전은 호출자가
명시한다. 수집처 ID가 바뀐 개정본의 기존 ID 연결은 identities로만 지정한다.
"""

from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from html import escape
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import parse_qs, urlsplit

from src.contracts import SourceDocument
from src.ingestion.xml_adapter import xml_to_html


class PreprocessedBundleError(ValueError):
    """묶음의 형식, 해시 또는 문서 연결을 확인할 수 없다."""


@dataclass
class PreparedBundle:
    documents: list[SourceDocument]
    report: dict


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PreprocessedBundleError(f"{field}: 비어 있지 않은 문자열이 필요합니다.")
    return value


def _mapping(value: object, field: str) -> dict:
    if not isinstance(value, dict):
        raise PreprocessedBundleError(f"{field}: JSON 객체가 필요합니다.")
    return value


def _list(value: object, field: str) -> list:
    if not isinstance(value, list):
        raise PreprocessedBundleError(f"{field}: JSON 배열이 필요합니다.")
    return value


def _unique_keys(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise PreprocessedBundleError(f"중복 JSON 필드: {key}")
        result[key] = value
    return result


def _invalid_constant(value: str):
    raise PreprocessedBundleError("NaN/Infinity는 표준 JSON 값이 아닙니다.")


def _decode_json(payload: bytes, label: str) -> tuple[dict, str]:
    try:
        # 바이트로 읽어 CRLF를 LF로 바꾸지 않는다. BOM만 인코딩 표식으로 처리한다.
        text = payload.decode("utf-8-sig")
        data = json.loads(text, object_pairs_hook=_unique_keys, parse_constant=_invalid_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PreprocessedBundleError(f"{label}: 올바른 UTF-8 JSON이 필요합니다.") from error
    return _mapping(data, label), text


def _safe_file(base: Path, relative: object) -> Path:
    name = _text(relative, "파일 경로")
    parts = PurePosixPath(name.replace("\\", "/"))
    if parts.is_absolute() or PureWindowsPath(name).anchor or ".." in parts.parts or ":" in name or "\0" in name:
        raise PreprocessedBundleError("파일 경로는 상위 이동이 없는 상대 경로여야 합니다.")
    path = (base / Path(*parts.parts)).resolve()
    if not path.is_relative_to(base.resolve()):
        raise PreprocessedBundleError("파일 경로가 지정한 묶음 영역을 벗어납니다.")
    if not path.is_file():
        raise PreprocessedBundleError(f"필수 파일이 없습니다: {parts.as_posix()}")
    return path


def _hash(value: object, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-fA-F]{64}", value) is None:
        raise PreprocessedBundleError(f"{label}: SHA256 값이 필요합니다.")
    return value.lower()


class _BundleFiles:
    def __init__(self, root: Path):
        self.root = root
        manifest, _ = _decode_json(_safe_file(root, "bundle_manifest.json").read_bytes(), "bundle_manifest.json")
        if manifest.get("schema_version") != "jungeun-handoff-bundle-v2":
            raise PreprocessedBundleError("지원하는 전처리 묶음 v2가 아닙니다.")
        self.files = {}
        for record in _list(manifest.get("files"), "bundle_manifest.files"):
            record = _mapping(record, "bundle_manifest.files 항목")
            path = _text(record.get("path"), "bundle_manifest.files.path").replace("\\", "/")
            if path in self.files:
                raise PreprocessedBundleError(f"bundle_manifest 파일 경로 중복: {path}")
            self.files[path] = record

    def read(self, base: Path, relative: object) -> tuple[Path, bytes]:
        path = _safe_file(base, relative)
        if not path.is_relative_to(self.root):
            raise PreprocessedBundleError("사용 파일이 묶음 루트 밖에 있습니다.")
        name = path.relative_to(self.root).as_posix()
        record = self.files.get(name)
        if record is None:
            raise PreprocessedBundleError(f"bundle_manifest에 사용 파일이 없습니다: {name}")
        payload = path.read_bytes()
        expected_size = record.get("size_bytes")
        if type(expected_size) is not int or expected_size != len(payload):
            raise PreprocessedBundleError(f"파일 크기 불일치: {name}")
        self.check_hash(payload, record.get("sha256"), name)
        return path, payload

    @staticmethod
    def check_hash(payload: bytes, expected: object, label: str) -> None:
        if hashlib.sha256(payload).hexdigest() != _hash(expected, label):
            raise PreprocessedBundleError(f"SHA256 불일치: {label}")

    def json(self, base: Path, relative: object) -> tuple[Path, dict, str]:
        path, payload = self.read(base, relative)
        data, text = _decode_json(payload, path.relative_to(self.root).as_posix())
        return path, data, text


def _index(records: object, keys: tuple[str, ...], label: str) -> dict[tuple[str, ...], dict]:
    result = {}
    for record in _list(records, label):
        record = _mapping(record, label)
        key = tuple(_text(record.get(name), f"{label}.{name}") for name in keys)
        if key in result:
            raise PreprocessedBundleError(f"{label}: 문서 식별자가 중복됩니다.")
        result[key] = record
    return result


def _same(left: dict, right: dict, fields: tuple[str, ...], label: str) -> None:
    for field in fields:
        if field not in left or field not in right or left[field] != right[field]:
            raise PreprocessedBundleError(f"{label}: {field} 메타데이터가 일치하지 않습니다.")


_BODY_FIELDS = ("document_id", "title", "district", "mst", "effective_date", "source_url", "raw_path", "raw_sha256")
_ANNEX_FIELDS = ("document_id", "parent_mst", "attachment_id", "annex_key", "title", "district", "effective_date", "source_url", "deleted_marker")
_OVERLAY_FIELDS = {"content_role", "human_review_status", "human_review", "retrieval_decision", "structured_image_summary"}


def _metadata(data: dict) -> dict:
    title = _text(data.get("title"), "title")
    district = _text(data.get("district"), "district")
    url = _text(data.get("source_url"), "source_url")
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or any(char.isspace() for char in url):
        raise PreprocessedBundleError("source_url: 공백 없는 HTTP(S) 출처가 필요합니다.")
    date_text = _text(data.get("effective_date"), "effective_date")
    if re.fullmatch(r"[0-9]{8}", date_text) is None:
        raise PreprocessedBundleError("effective_date는 YYYYMMDD여야 합니다.")
    try:
        effective_date = datetime.strptime(date_text, "%Y%m%d").date()
    except ValueError as error:
        raise PreprocessedBundleError("effective_date가 유효한 날짜가 아닙니다.") from error
    return {"title": title, "source_url": url, "effective_date": effective_date, "scope_type": "district", "districts": [district]}


def _validate_body_xml(payload: bytes, data: dict) -> str:
    try:
        text = payload.decode("utf-8-sig")
        if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", text, re.IGNORECASE):
            raise PreprocessedBundleError("본문 XML의 DTD/entity 선언은 지원하지 않습니다.")
        root = ET.fromstring(text)
    except (UnicodeDecodeError, ET.ParseError) as error:
        raise PreprocessedBundleError("본문 원본이 올바른 UTF-8 XML이 아닙니다.") from error
    for tag, key in (("자치법규일련번호", "mst"), ("자치법규명", "title"), ("시행일자", "effective_date")):
        if root.findtext(f"./자치법규기본정보/{tag}") != data[key]:
            raise PreprocessedBundleError(f"본문 XML과 JSON의 {key}가 일치하지 않습니다.")
    if parse_qs(urlsplit(data["source_url"]).query).get("ordinSeq") != [data["mst"]]:
        raise PreprocessedBundleError("본문 출처 ordinSeq가 MST와 일치하지 않습니다.")
    return text


def _relative_raw(path: Path, project_root: Path) -> str | None:
    return path.relative_to(project_root).as_posix() if path.is_relative_to(project_root) else None


def load_preprocessed_bundle(
    bundle_root: Path,
    *,
    project_root: Path,
    version: str,
    identities: dict[str, str] | None = None,
) -> PreparedBundle:
    """제공된 본문/첨부를 보존하고 논리문서마다 JSON, HTML 쌍을 반환한다.

    sources는 논리문서당 한 항목이다. 행정 서식/표지판도 documents에는 보관하고
    index_eligible=False로 구분한다. 삭제 첨부는 skipped에만 남긴다.
    identities의 키는 원래 본문 document_id 또는 부모ID:attachment:첨부ID다.
    파일이나 수집처 번호가 달라진 문서의 동일성/개정 여부는 자동 추정하지 않는다.
    """
    version = _text(version, "version")
    root, project = Path(bundle_root).resolve(), Path(project_root).resolve()
    identities = {} if identities is None else dict(identities)
    for key, value in identities.items():
        _text(key, "identities key")
        _text(value, "identities value")
    files = _BundleFiles(root)
    body_dir, annex_dir, raw_dir = root / "processed/body", root / "processed/annex", root / "raw"
    _, body_manifest, _ = files.json(body_dir, "processing_manifest.json")
    _, annex_manifest, _ = files.json(annex_dir, "annex_manifest.json")
    _, raw_manifest, _ = files.json(raw_dir, "manifest.json")
    _, raw_annex_manifest, _ = files.json(raw_dir / "attachments", "manifest.json")
    _, overlay_file, _ = files.json(root / "review", "human_review_overlays.json")
    run_id = _text(raw_manifest.get("run_id"), "raw manifest run_id")
    for manifest in (body_manifest, annex_manifest, raw_annex_manifest):
        if manifest.get("source_run_id") != run_id:
            raise PreprocessedBundleError("manifest의 source_run_id가 일치하지 않습니다.")
    body_records = _index(body_manifest.get("documents"), ("document_id",), "본문 manifest")
    raw_records = _index(raw_manifest.get("records"), ("document_id",), "원본 manifest")
    if set(body_records) != set(raw_records):
        raise PreprocessedBundleError("본문 처리 목록과 원본 문서 목록이 다릅니다.")
    annex_records = _index(annex_manifest.get("records"), ("parent_mst", "attachment_id"), "첨부 manifest")
    raw_annex_records = _index(raw_annex_manifest.get("records"), ("parent_mst", "attachment_id"), "첨부 원본 manifest")
    if set(annex_records) != set(raw_annex_records):
        raise PreprocessedBundleError("첨부 처리 목록과 원본 첨부 목록이 다릅니다.")
    overlays = _index(overlay_file.get("records"), ("parent_mst", "attachment_id"), "검수 overlay")
    documents, sources, skipped = [], [], []
    parents, attachment_inventory = {}, {}
    used_ids, used_keys, used_overlays = set(), set(), set()

    def identity(source_key: str) -> str:
        document_id = identities.get(source_key, source_key)
        if document_id in used_ids or source_key in used_keys:
            raise PreprocessedBundleError("내부 document_id 또는 source_key가 중복됩니다.")
        used_ids.add(document_id)
        used_keys.add(source_key)
        return document_id

    def add_pair(data: dict, source_key: str, document_id: str, json_path: Path, json_text: str,
                 xml_path: Path, html: str, raw_path: Path, role: str, parent_id: str | None = None):
        metadata = _metadata(data) | {
            "document_id": document_id, "version": version,
            "raw_path": _relative_raw(raw_path, project),
            "parent_document_id": parent_id,
            "parent_document_version": version if parent_id is not None else None,
        }
        for content_format, content in (("json", json_text), ("html", html)):
            documents.append(SourceDocument(**metadata, content_format=content_format, content=content))
        sources.append({
            "document_id": document_id, "source_key": source_key, "role": role,
            "index_eligible": role not in {"administrative_form", "signage_specification"},
            "raw_sha256": data["raw_sha256"], "raw_path": metadata["raw_path"],
            "input_path": json_path.relative_to(root).as_posix(),
            "xml_path": xml_path.relative_to(root).as_posix(),
            "human_review_status": data.get("human_review_status", "pending"),
            "human_review": data.get("human_review"), "usage_status": data.get("usage_status"),
            "parent_document_id": parent_id, "source_url": data["source_url"],
        })

    for (source_key,), record in body_records.items():
        json_path, data, json_text = files.json(body_dir, record.get("output_file"))
        if data.get("schema_version") != "jungeun-body-draft-v2":
            raise PreprocessedBundleError("지원하는 본문 JSON v2가 아닙니다.")
        _same(data, record, ("document_id", "raw_sha256"), "본문 manifest")
        _same(data, raw_records[(source_key,)], _BODY_FIELDS, "본문 원본")
        mst = _text(data.get("mst"), "본문 MST")
        if mst in parents:
            raise PreprocessedBundleError("본문 MST가 중복됩니다.")
        raw_path, payload = files.read(raw_dir, data.get("raw_path"))
        files.check_hash(payload, data.get("raw_sha256"), "본문 원본")
        html = xml_to_html(_validate_body_xml(payload, data))
        document_id = identity(source_key)
        parents[mst] = (data, document_id)
        inventory = _index(data.get("attachments"), ("parent_mst", "attachment_id"), "본문 첨부 목록")
        raw_inventory = _index(raw_records[(source_key,)].get("attachments"), ("parent_mst", "attachment_id"), "원본 본문 첨부 목록")
        if inventory != raw_inventory:
            raise PreprocessedBundleError("본문 JSON과 원본 manifest의 첨부 목록이 다릅니다.")
        for key, item in inventory.items():
            if key[0] != mst or key in attachment_inventory:
                raise PreprocessedBundleError("본문 첨부 목록의 부모 MST 또는 중복 연결 오류입니다.")
            attachment_inventory[key] = item
        add_pair(data, source_key, document_id, json_path, json_text, raw_path, html, raw_path, "body")
    if set(attachment_inventory) != set(annex_records):
        raise PreprocessedBundleError("본문 첨부 목록과 첨부 처리 목록이 다릅니다.")

    for key, record in annex_records.items():
        mst, attachment_id = key
        if mst not in parents:
            raise PreprocessedBundleError("첨부의 부모 MST가 본문 목록에 없습니다.")
        parent, parent_id = parents[mst]
        _same(record, parent, ("document_id", "district", "effective_date"), "첨부 부모")
        _same(record, raw_annex_records[key], _ANNEX_FIELDS, "첨부 원본")
        _same(record, attachment_inventory[key], ("parent_mst", "attachment_id", "annex_key", "title", "source_url", "deleted_marker"), "본문-첨부 연결")
        if parse_qs(urlsplit(record["source_url"]).query).get("flSeq") != [attachment_id]:
            raise PreprocessedBundleError("첨부 source_url의 flSeq가 attachment_id와 다릅니다.")
        source_key = f"{parent['document_id']}:attachment:{attachment_id}"
        if type(record.get("deleted_marker")) is not bool:
            raise PreprocessedBundleError("deleted_marker는 bool이어야 합니다.")
        if record["deleted_marker"]:
            if record.get("processing_status") != "excluded_deleted":
                raise PreprocessedBundleError("삭제 첨부의 처리 상태가 일치하지 않습니다.")
            skipped.append({"source_key": source_key, "parent_document_id": parent_id,
                            "reason": "deleted", "role": "deleted", "title": record["title"],
                            "source_url": record["source_url"], "human_review_status": record.get("human_review_status")})
            continue
        json_path, data, json_text = files.json(annex_dir, record.get("output_file"))
        _same(data, record, _ANNEX_FIELDS + ("schema_version", "raw_path", "raw_sha256", "extracted_xml", "extracted_xml_sha256", "content_role", "human_review_status", "processing_status"), "첨부 JSON")
        if data.get("schema_version") != "jungeun-annex-draft-v2":
            raise PreprocessedBundleError("지원하는 첨부 JSON v2가 아닙니다.")
        _same(data, raw_annex_records[key], ("raw_path", "raw_sha256", "download_status"), "첨부 원본 파일")
        raw_path, raw_bytes = files.read(raw_dir, data.get("raw_path"))
        files.check_hash(raw_bytes, data.get("raw_sha256"), "첨부 원본")
        xml_path, xml_bytes = files.read(annex_dir, data.get("extracted_xml"))
        files.check_hash(xml_bytes, data.get("extracted_xml_sha256"), "첨부 구조 XML")
        try:
            html = xml_to_html(xml_bytes.decode("utf-8-sig"))
        except UnicodeDecodeError as error:
            raise PreprocessedBundleError("첨부 구조 XML은 UTF-8이어야 합니다.") from error
        if key in overlays:
            overlay = overlays[key]
            if _hash(overlay.get("raw_sha256"), "검수 overlay") != _hash(data["raw_sha256"], "첨부 원본"):
                raise PreprocessedBundleError("검수 overlay가 다른 원본 해시를 가리킵니다.")
            updates = _mapping(overlay.get("updates"), "검수 updates")
            if not set(updates).issubset(_OVERLAY_FIELDS):
                raise PreprocessedBundleError("검수 overlay에 지원하지 않는 변경 필드가 있습니다.")
            _same(data, updates, tuple(updates), "검수 overlay 적용 결과")
            _same(record, updates, tuple(updates), "검수 overlay manifest")
            review = _mapping(updates.get("human_review"), "human_review")
            _same(review, data, ("parent_mst", "attachment_id"), "검수 부모/첨부")
            used_overlays.add(key)
        elif "structured_image_summary" in data or "human_review" in data:
            raise PreprocessedBundleError("사람 검수 보완에 대응하는 overlay가 없습니다.")
        if "structured_image_summary" in data:
            summary = _mapping(data["structured_image_summary"], "structured_image_summary")
            supplement = '<aside data-review-overlay="image-summary">' + escape(json.dumps(summary, ensure_ascii=False), quote=False) + "</aside>"
            # JSON에 이미 있는 검수 보완을 XML 표현에도 같은 키/값으로 전달한다.
            html = html.replace("</body>", supplement + "</body>") if "</body>" in html else html + supplement
        role = _text(data.get("content_role"), "content_role")
        if role not in {"annex", "administrative_form", "signage_specification"}:
            raise PreprocessedBundleError("지원하지 않는 첨부 content_role입니다.")
        add_pair(data, source_key, identity(source_key), json_path, json_text, xml_path, html, raw_path, role, parent_id)
    if used_overlays != set(overlays):
        raise PreprocessedBundleError("현재 문서에 대응하지 않는 검수 overlay가 있습니다.")
    if set(identities) - used_keys:
        raise PreprocessedBundleError("identities에 현재 문서와 연결되지 않는 source_key가 있습니다.")
    return PreparedBundle(documents, {"source_run_id": run_id, "version": version, "sources": sources, "skipped": skipped})
