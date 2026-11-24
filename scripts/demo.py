"""색인부터 평가 기록까지 합성 자료로 실행한다. 외부 API는 호출하지 않는다."""

import argparse
import json
from pathlib import Path
from uuid import uuid4

from src.config import load_settings
from src.demo import create_demo_pipeline
from src.evaluation.runner import evaluate_cases, load_evaluation_cases
from src.infrastructure.embeddings import DemoHashEmbeddings
from src.infrastructure.stores import save_index
from src.ingestion.chunking import chunk_documents
from src.ingestion.indexing import build_index
from src.ingestion.loaders import load_source_documents, load_source_manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output_dir or root / "results/local" / f"handoff-demo-{uuid4().hex}"
    output = output.resolve()
    # 다른 실행의 원본 기록을 덮어쓰지 않도록 새로운 실행 폴더를 요구한다.
    output.mkdir(parents=True, exist_ok=False)
    settings = load_settings(root / "configs/demo.json", project_root=root)
    settings.index_path = output / "index.json"
    settings.runs_path = output / "runs"
    manifest = load_source_manifest(root / "tests/fixtures/source_manifest.json")
    # 고정된 작은 합성 문서만 색인한다. 평가 정답은 별도 파일로 읽는다.
    documents = load_source_documents(root / "tests/fixtures/handoff_documents.json")
    chunks = chunk_documents(documents, max_characters=settings.max_document_characters)
    snapshot = build_index(chunks, DemoHashEmbeddings(dimensions=settings.demo_dimensions))
    save_index(snapshot, settings.index_path)
    cases = load_evaluation_cases(root / "tests/fixtures/handoff_eval.json")
    results = evaluate_cases(cases, {"synthetic-demo": create_demo_pipeline(settings)})
    summary = {
        "is_synthetic": True, "run_kind": "demo",
        "notice": "외부 모델 호출과 실제 검색 품질 평가를 수행하지 않은 합성 연결 검사",
        "manifest_documents": len(manifest),
        "manifest_attachments": sum(len(row.attachments) for row in manifest),
        "indexed_synthetic_documents": len(documents), "chunks": len(chunks),
        "index_id": snapshot.metadata.index_id,
        "results": results,
    }
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"합성 데모 완료: 목록 {len(manifest)}건, 청크 {len(chunks)}개")
    for result in results:
        print(f"{result['case_id']}: {result['status']}")
    print(f"결과: {output / 'summary.json'}")
    if any(result["status"] == "error" for result in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
