"""공식 첨부 HWP의 셀·병합·문단 추출. 로컬 검수용 내부 형식.

hwp5proc는 pyhwp 임시 환경에서 실행. 설치되지 않으면 명시적 실패.
외부 모델·색인 입력과 사람이 조건을 승인한 기록은 생성하지 않는다.
"""

import argparse
import hashlib
import json
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from copy import deepcopy
from pathlib import Path
from urllib.parse import parse_qs, urlparse, urlunparse
from urllib.request import urlopen

from src.ingestion.search_preparation import prepare_table_rows

REVIEW_UPDATE_FIELDS = {
    "content_role",
    "human_review_status",
    "human_review",
    "structured_image_summary",
    "retrieval_decision",
}


def _validate_review_overlay(overlay: dict) -> tuple[str, str]:
    """검수 기록으로 바꿀 수 있는 필드와 원본 식별자 확인."""
    required = {"parent_mst", "attachment_id", "raw_sha256", "updates"}
    if not isinstance(overlay, dict) or set(overlay) != required:
        raise ValueError("검수 오버레이의 식별자·해시·updates 확인 필요")
    for field in ("parent_mst", "attachment_id"):
        value = overlay[field]
        if not isinstance(value, str) or not value.isascii() or not value.isdigit():
            raise ValueError(f"검수 오버레이의 {field} 확인 필요")
    if not isinstance(overlay["raw_sha256"], str) or not re.fullmatch(
        r"[0-9a-f]{64}", overlay["raw_sha256"]
    ):
        raise ValueError("검수 오버레이의 원본 SHA256 확인 필요")
    updates = overlay["updates"]
    if (
        not isinstance(updates, dict)
        or not updates
        or not set(updates) <= REVIEW_UPDATE_FIELDS
    ):
        raise ValueError("검수 오버레이의 updates 허용 필드 확인 필요")
    for field, value in updates.items():
        if field in {"human_review", "structured_image_summary"}:
            if not isinstance(value, dict) or not value:
                raise ValueError(f"검수 오버레이의 {field}는 기록 객체 필요")
        elif not isinstance(value, str) or not value.strip():
            raise ValueError(f"검수 오버레이의 {field}는 빈 값이 아닌 문자열 필요")
    return overlay["parent_mst"], overlay["attachment_id"]


def load_review_overlays(
    path: Path, sources: list[dict]
) -> dict[tuple[str, str], dict]:
    """원본 목록과 정확히 일치하는 검수만 반환. 중복·미매칭·해시 차이는 중단."""
    document = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(document, dict)
        or set(document) != {"records"}
        or not isinstance(document.get("records"), list)
    ):
        raise ValueError("검수 오버레이 records 목록 필요")
    source_map = {}
    for source in sources:
        key = (source["parent_mst"], source["attachment_id"])
        if key in source_map:
            raise ValueError("원본 목록에 중복된 부모 MST·첨부 ID")
        source_map[key] = source
    overlays = {}
    for overlay in document["records"]:
        key = _validate_review_overlay(overlay)
        if key in overlays:
            raise ValueError("중복 검수 오버레이")
        source = source_map.get(key)
        if source is None:
            raise ValueError("원본 목록과 미매칭 검수 오버레이")
        if source.get("raw_sha256") != overlay["raw_sha256"]:
            raise ValueError("검수 오버레이 원본 해시 불일치")
        if source.get("download_status") != "downloaded" or source.get(
            "deleted_marker"
        ):
            raise ValueError("검수 오버레이는 내려받은 비삭제 첨부만 적용 가능")
        overlays[key] = deepcopy(overlay)
    return overlays


def apply_review_overlay(record: dict, overlay: dict) -> dict:
    """식별자·해시 일치 시 검수 필드만 복사한 새 결과 반환. 입력은 보존."""
    key = _validate_review_overlay(overlay)
    if key != (record.get("parent_mst"), record.get("attachment_id")):
        raise ValueError("검수 오버레이 부모 MST·첨부 ID 불일치")
    if record.get("raw_sha256") != overlay["raw_sha256"]:
        raise ValueError("검수 오버레이 원본 해시 불일치")
    result = deepcopy(record)
    result.update(deepcopy(overlay["updates"]))
    return result


def download_attachments(manifest_path: Path, review: dict) -> Path:
    """검토한 공식 첨부만 새 attachments 폴더에 저장. 삭제 파일 제외."""
    from src.ingestion.source_review import validate_review

    validate_review(review)
    manifest_path = manifest_path.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    folder = manifest_path.parent / "attachments"
    folder.mkdir(exist_ok=False)
    records = []
    for document in manifest["records"]:
        if document.get("collection_status") != "body_saved":
            continue
        for attachment in document["attachments"]:
            result = {
                **attachment,
                "document_id": document["document_id"],
                "district": document["district"],
                "effective_date": document["effective_date"],
                "download_review": review,
            }
            if attachment["deleted_marker"]:
                result["download_status"] = "skipped_deleted"
            else:
                try:
                    parsed = urlparse(attachment["source_url"])
                    aid = attachment["attachment_id"]
                    if (
                        parsed.hostname != "www.law.go.kr"
                        or not parsed.path.endswith("/flDownload.do")
                        or not aid.isascii()
                        or not aid.isdigit()
                        or attachment["parent_mst"] != document["mst"]
                        or parse_qs(parsed.query).get("flSeq") != [aid]
                    ):
                        raise ValueError("공식 첨부 URL·부모·식별자 확인 필요")
                    url = urlunparse(parsed._replace(scheme="https"))
                    with urlopen(url, timeout=30) as response:
                        if urlparse(response.url).hostname not in {
                            "law.go.kr",
                            "www.law.go.kr",
                        }:
                            raise ValueError("공식 호스트 밖 응답")
                        raw = response.read()
                    if not raw.startswith(bytes.fromhex("d0cf11e0a1b11ae1")):
                        raise ValueError("지원하는 HWP5 형식 아님")
                    target = folder / f"{document['mst']}_{aid}.hwp"
                    target.write_bytes(raw)
                    result.update(
                        download_status="downloaded",
                        raw_path=str(target.relative_to(manifest_path.parent)),
                        raw_sha256=hashlib.sha256(raw).hexdigest(),
                        size_bytes=len(raw),
                    )
                except (OSError, ValueError) as error:
                    result.update(
                        download_status="error", error_type=type(error).__name__
                    )
                time.sleep(0.5)
            records.append(result)
            (folder / "manifest.json").write_text(
                json.dumps(
                    {
                        "source_run_id": manifest["run_id"],
                        "records": records,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
    return folder / "manifest.json"


def _text(node: ET.Element) -> str:
    # 표 중첩 제외, 문단·고정폭 공백 보존
    if node.tag == "Text":
        return node.text or ""
    if node.tag == "Tab":
        return "\t"
    if node.tag == "TableControl":
        return ""
    if node.tag == "TCPSControl":
        # 글자 겹침의 textlength는 길이가 아닌 BSTR 원문. 숫자·글리프 변환 제외
        parts = [node.text or ""]
        for child in node:
            parts.extend((_text(child), child.tail or ""))
        rendered = "".join(parts)
        if rendered.strip():
            return rendered
        return node.get("textlength", "") or rendered
    if node.tag == "ControlChar":
        name = node.get("name", "")
        if name == "PARAGRAPH_BREAK":
            return "\n"
        if name in {"FIXWIDTH_SPACE", "NBSPACE", "TAB"}:
            return " "
        return node.get("char", "")
    return "".join(_text(child) for child in node)


def extract_hwp_xml(xml_path: Path) -> dict:
    """셀 좌표와 병합 범위를 보존. 행은 원본 셀 ID로 연결."""
    root = ET.parse(xml_path).getroot()
    parents = {child: parent for parent in root.iter() for child in parent}

    def ancestor(node, tag):
        current = parents.get(node)
        while current is not None:
            if current.tag == tag:
                return current
            current = parents.get(current)
        return None

    blocks = []
    tables = []
    body = root.find("BodyText")
    if body is None:
        raise ValueError("HWP 본문 없음")
    for node in body.iter():
        if node.tag == "Paragraph" and ancestor(node, "TableCell") is None:
            text = _text(node)
            blocks.append({"type": "paragraph", "text": text})
        if node.tag != "TableControl":
            continue
        table_id = f"table-{len(tables) + 1}"
        table_body = node.find("TableBody")
        if table_body is None:
            raise ValueError("표 구조 확인 필요")
        cells = []
        grid = {}
        for cell in table_body.findall("./TableRow/TableCell"):
            row, col = int(cell.attrib["row"]), int(cell.attrib["col"])
            rowspan = int(cell.attrib["rowspan"])
            colspan = int(cell.attrib["colspan"])
            cell_id = f"{table_id}-r{row}-c{col}"
            paragraphs = [
                _text(p)
                for p in cell.iter("Paragraph")
                if ancestor(p, "TableCell") is cell
            ]
            cells.append(
                {
                    "cell_id": cell_id,
                    "row": row,
                    "col": col,
                    "rowspan": rowspan,
                    "colspan": colspan,
                    "paragraphs": paragraphs,
                    "text": "".join(paragraphs).strip(),
                    "embedded_object_count": sum(
                        n.tag in {"Picture", "ShapePicture"} for n in cell.iter()
                    ),
                }
            )
            for rr in range(row, row + rowspan):
                for cc in range(col, col + colspan):
                    if (rr, cc) in grid:
                        raise ValueError("병합 셀 중복 좌표")
                    grid[rr, cc] = cell_id
        rows, cols = int(table_body.attrib["rows"]), int(table_body.attrib["cols"])
        if any(r >= rows or c >= cols for r, c in grid):
            raise ValueError("표 범위 밖 셀")
        table = {
            "table_id": table_id,
            "rows": rows,
            "cols": cols,
            "cells": cells,
            "row_cell_ids": [
                [grid.get((r, c)) for c in range(cols)] for r in range(rows)
            ],
            "preceding_paragraphs": [
                b["text"] for b in blocks if b["type"] == "paragraph"
            ],
        }
        table["rows_for_search"] = prepare_table_rows(table)
        tables.append(table)
        blocks.append({"type": "table", "table_id": table_id})
    # 별표·별지 제목에서 구획을 바꾸고 본문 속 참조는 제외
    section = ""
    section_deleted = False
    table_map = {t["table_id"]: t for t in tables}
    for block in blocks:
        if block["type"] == "paragraph":
            text = block["text"].strip()
            if re.match(
                r"^(?:[〔【\[]\s*)?별(?:표|지)\s*(?:제\s*)?\d+"
                r"(?:\s*의\s*\d+)?(?:\s*호\s*서식)?"
                r"(?:\s*[〕】\]])?(?=\s*(?:$|<|삭제|신설|개정))",
                text,
            ):
                section = text
                section_deleted = "삭제" in text
            elif text.startswith("<삭제"):
                section_deleted = True
        block["section_title"] = section
        block["deleted_section"] = section_deleted
        if block["type"] == "table":
            table_map[block["table_id"]]["section_title"] = section
            table_map[block["table_id"]]["deleted_section"] = section_deleted
    return {
        "blocks": blocks,
        "tables": tables,
        "embedded_object_count": sum(
            n.tag in {"Picture", "ShapePicture"} for n in body.iter()
        ),
    }


def preprocess_attachments(
    download_manifest: Path, output_dir: Path, review_overlays: Path | None = None
) -> dict:
    """해시 대조 후 HWP 구조 추출. 삭제·서식은 답변 근거와 별도 분류."""
    manifest = json.loads(download_manifest.read_text(encoding="utf-8"))
    run_dir = download_manifest.resolve().parent.parent
    overlays = (
        load_review_overlays(review_overlays, manifest["records"])
        if review_overlays is not None
        else {}
    )
    applied = set()
    output_dir.mkdir(parents=True, exist_ok=False)
    records = []
    for source in manifest["records"]:
        key = f"{source['parent_mst']}_{source['attachment_id']}"
        # XML 목록 정보와 내려받은 HWP의 상태 분리
        result = {
            **{
                k: v
                for k, v in source.items()
                if k not in {"collection_status", "content_present"}
            },
            "schema_version": "jungeun-annex-draft-v2",
            "xml_listing": {
                "scope": "lawService XML attachment entry only",
                "collection_status": source.get("collection_status"),
                "content_present": source.get("content_present"),
            },
            "extracted_text_present": False,
            "extracted_table_count": 0,
            "human_review_status": "pending",
            "usage_status": "index_and_model_use_unreviewed",
        }
        if source["deleted_marker"]:
            result.update(processing_status="excluded_deleted", content_role="deleted")
        elif source["download_status"] != "downloaded":
            result["processing_status"] = "download_failed"
        else:
            path = (run_dir / source["raw_path"]).resolve()
            if not path.is_relative_to(run_dir):
                raise ValueError("원본 경로 범위 확인 필요")
            if hashlib.sha256(path.read_bytes()).hexdigest() != source["raw_sha256"]:
                raise ValueError("첨부 원본 해시 불일치")
            xml_path = output_dir / f"{key}.xml"
            try:
                with xml_path.open("wb") as stream:
                    subprocess.run(
                        ["hwp5proc", "xml", str(path)],
                        stdout=stream,
                        stderr=subprocess.PIPE,
                        check=True,
                        timeout=120,
                    )
                content = extract_hwp_xml(xml_path)
                result["extracted_text_present"] = any(
                    b.get("text", "").strip() for b in content["blocks"]
                ) or any(c["text"] for t in content["tables"] for c in t["cells"])
                result["extracted_table_count"] = len(content["tables"])
                for table in content["tables"]:
                    for row in table["rows_for_search"]:
                        row["row_id"] = f"{key}_{row['row_id']}"
                        row["source_attachment_id"] = source["attachment_id"]
                        row["source_parent_mst"] = source["parent_mst"]
                role = "administrative_form" if "별지" in source["title"] else "annex"
                result.update(
                    content,
                    content_role=role,
                    processing_status="structure_extracted_pending_review",
                    extracted_xml=xml_path.name,
                    extracted_xml_sha256=hashlib.sha256(
                        xml_path.read_bytes()
                    ).hexdigest(),
                )
                overlay_key = (source["parent_mst"], source["attachment_id"])
                if overlay_key in overlays:
                    result = apply_review_overlay(result, overlays[overlay_key])
                    applied.add(overlay_key)
                (output_dir / f"{key}.json").write_text(
                    json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                result = {
                    k: v for k, v in result.items() if k not in {"blocks", "tables"}
                }
                result["output_file"] = f"{key}.json"
                result["table_count"] = len(content["tables"])
                result["cell_count"] = sum(len(t["cells"]) for t in content["tables"])
            except (
                OSError,
                subprocess.SubprocessError,
                ET.ParseError,
                ValueError,
            ) as error:
                result.update(
                    processing_status="extraction_error",
                    error_type=type(error).__name__,
                )
        records.append(result)
        (output_dir / "annex_manifest.json").write_text(
            json.dumps(
                {
                    "source_run_id": manifest["source_run_id"],
                    "records": records,
                    "tool": "pyhwp 0.1b15 hwp5proc xml",
                    "schema_version": "jungeun-annex-draft-v2",
                    "status_field_definitions": {
                        "xml_listing": "XML 목록 수집 시점 정보. HWP 다운로드·추출 상태와 별개.",
                        "download_status": "첨부 원본 파일 확보 상태",
                        "processing_status": "별도 첨부 파일의 구조 추출 상태",
                        "extracted_text_present": "HWP 구조 XML에서 읽은 텍스트 유무",
                        "extracted_table_count": "HWP 구조 XML에서 읽은 표 수",
                        "rows_for_search": "원문 셀을 보존한 검색용 행. 병합 셀과 각주 참조 포함; 실제 청킹·검색 연동은 별도.",
                        "human_review_status": "사람이 확인한 범위. 전체 데이터 이용 승인과 별개.",
                    },
                    "human_review_status": "pending",
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    if applied != set(overlays):
        raise ValueError("추출 실패로 적용하지 못한 검수 오버레이 존재")
    return {"records": records}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--review-overlays",
        type=Path,
        help="부모 MST·첨부 ID·원본 해시가 일치하는 검수 기록 재적용",
    )
    args = parser.parse_args()
    result = preprocess_attachments(
        args.manifest, args.output_dir, args.review_overlays
    )
    for r in result["records"]:
        print(
            r["parent_mst"],
            r["attachment_id"],
            r["processing_status"],
            r.get("table_count", 0),
            r.get("cell_count", 0),
        )
    if any(
        r["processing_status"] in {"download_failed", "extraction_error"}
        for r in result["records"]
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
