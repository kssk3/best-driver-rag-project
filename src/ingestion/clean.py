"""자치법규 본문 추출 초안. 팀 공통 규격 연동 전 로컬 검토용.

본문 공백은 앞뒤만 제거하고 항·호·예외·개정 문구는 보존한다.
부칙·제개정이유는 별도 구획으로 보존. 별표 본문은 annexes에서 처리.
"""

import argparse
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

# 조문 전체 삭제와 항·호 일부 삭제 구분
_DELETED_ARTICLE = re.compile(
    r"제\s*\d+\s*조(?:의\s*\d+)?\s*(?:\([^)]*\)\s*)?"
    r"(?:삭제\s*(?:<[^<>]*>)?|<\s*삭제[^<>]*>)"
)


def preview_article(xml_path: Path) -> None:
    root = ET.parse(xml_path).getroot()
    for article in root.findall("./조문/조"):
        if article.findtext("조문여부") != "Y":
            continue
        print("조문번호:", article.findtext("조문번호"))
        print("제목:", article.findtext("조제목"))
        print("내용:", article.findtext("조내용"))
        break


def extract_document(xml_path: Path, record: dict) -> dict:
    """해시·문서명·MST·시행일 대조 후 본문 단위 반환. 불일치 시 중단."""
    if record.get("collection_status") != "body_saved":
        raise ValueError("본문 저장 완료 기록 필요")
    raw = xml_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != record["raw_sha256"]:
        raise ValueError("원본 해시 불일치")
    root = ET.fromstring(raw)
    if root.tag != "LawService":
        raise ValueError("본문 XML 루트 불일치")
    for tag, field in (
        ("자치법규명", "title"),
        ("자치법규일련번호", "mst"),
        ("시행일자", "effective_date"),
    ):
        if root.findtext(f"./자치법규기본정보/{tag}") != record[field]:
            raise ValueError(f"본문과 실행 기록의 {field} 불일치")

    units = []
    seen = set()
    for position, article in enumerate(root.findall("./조문/조"), start=1):
        number = article.findtext("조문번호", "")
        kind = article.findtext("조문여부", "")
        content = article.find("조내용")
        if not number or kind not in {"Y", "N"} or content is None:
            raise ValueError("조문 구조 확인 필요")
        # 내부 줄바꿈·공백과 개정·삭제 문구 보존
        raw_text = "".join(content.itertext())
        text = raw_text.strip()
        if not text:
            raise ValueError(f"빈 조내용: {number}")
        suffix = number if kind == "Y" else f"heading-{position}"
        unit_id = f"{record['document_id']}_{record['mst']}_{suffix}"
        if unit_id in seen:
            raise ValueError(f"중복 조문 ID: {number}")
        seen.add(unit_id)
        title = article.findtext("조제목", "")
        units.append(
            {
                "unit_id": unit_id,
                "unit_type": "article" if kind == "Y" else "heading",
                "article_number": number,
                "title": title,
                "raw_text": raw_text,
                "text": text,
                "deleted_article": kind == "Y"
                and (title.strip() == "삭제" or bool(_DELETED_ARTICLE.fullmatch(text))),
                "source_location": f"조문/조[{position}] (조문번호 {number})",
            }
        )
    if not units:
        raise ValueError("추출된 본문 없음")
    supplementary = []
    for position, provision in enumerate(root.findall("./부칙"), start=1):
        raw_text = "".join(provision.find("부칙내용").itertext())
        supplementary.append(
            {
                "unit_id": f"{record['document_id']}_{record['mst']}_supplement-{position}",
                "source_location": f"부칙[{position}]/부칙내용",
                "promulgation_date": provision.findtext("부칙공포일자", ""),
                "promulgation_number": provision.findtext("부칙공포번호", ""),
                "raw_text": raw_text,
                "text": raw_text.strip(),
                "applicability_status": "historical_and_current_mixed_review_required",
                "note": "과거 부칙의 시행일·경과조치 포함. 현행 일반 배출 기준으로 일괄 적용 금지.",
            }
        )
    reasons = [
        {
            "source_location": f"제개정이유[{i}]",
            "raw_xml": ET.tostring(node, encoding="unicode"),
        }
        for i, node in enumerate(root.findall("./제개정이유"), start=1)
    ]
    return {
        "schema_version": "jungeun-body-draft-v2",
        "document_id": record["document_id"],
        "title": record["title"],
        "district": record["district"],
        "mst": record["mst"],
        "effective_date": record["effective_date"],
        "source_url": record["source_url"],
        "raw_path": record["raw_path"],
        "raw_sha256": record["raw_sha256"],
        "review": record["review"],
        "usage_status": record["usage_status"],
        "processing_status": "body_and_supplements_extracted_pending_manual_review",
        "transformations": ["XML 구조 추출", "조내용 앞뒤 공백 제거"],
        "unprocessed_sections": ["별표 (annexes 별도 결과 확인)"],
        "supplementary_provisions": supplementary,
        "amendment_reasons": reasons,
        "attachments_scope": "lawService XML link inventory only; see separate annex processing manifest",
        "attachments": record["attachments"],
        "units": units,
    }


def preprocess_run(manifest_path: Path, output_dir: Path) -> dict:
    """수집 실행 한 건을 새 폴더에 저장. 원본·기존 결과 덮어쓰기 금지."""
    manifest_path = manifest_path.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    documents = []
    skipped = []
    seen = set()
    for record in manifest["records"]:
        if record.get("collection_status") != "body_saved":
            skipped.append(record["document_id"])
            continue
        document_id = record["document_id"]
        if (
            not document_id
            or document_id in seen
            or any(
                c not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for c in document_id
            )
        ):
            raise ValueError("안전한 고유 document_id 필요")
        seen.add(document_id)
        xml_path = (manifest_path.parent / record["raw_path"]).resolve()
        if not xml_path.is_relative_to(manifest_path.parent):
            raise ValueError("원본 경로가 실행 폴더를 벗어남")
        documents.append(extract_document(xml_path, record))
    if not documents:
        raise ValueError("처리할 본문 없음")
    summary = {
        "source_run_id": manifest["run_id"],
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "processing_status": "body_and_supplements_extracted_pending_manual_review",
        "skipped_documents": skipped,
        "documents": [
            {
                "document_id": d["document_id"],
                "output_file": f"{d['document_id']}.json",
                "unit_count": len(d["units"]),
                "article_count": sum(u["unit_type"] == "article" for u in d["units"]),
                "raw_sha256": d["raw_sha256"],
            }
            for d in documents
        ],
        "unprocessed_sections": ["별표 (annexes 별도 결과 확인)"],
    }
    # 전체 입력 대조 후 새 폴더에 저장
    output_dir.mkdir(parents=True, exist_ok=False)
    for document in documents:
        path = output_dir / f"{document['document_id']}.json"
        path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    (output_dir / "processing_manifest.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    summary = preprocess_run(args.manifest, args.output_dir)
    for document in summary["documents"]:
        print(
            f"{document['document_id']}: {document['article_count']} 조문 / "
            f"장 제목 포함 {document['unit_count']} 단위"
        )
    print(f"저장 위치: {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
