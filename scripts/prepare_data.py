"""제공된 XML/전처리 JSON을 형식별 공용 문서, 청크와 선택적 실제 색인으로 연결한다."""

import argparse
from collections import Counter
import json
from pathlib import Path
from uuid import uuid4

from src.infrastructure.embeddings import (
    BoundedEmbeddings, configure_key_file, create_openai_embeddings,
)
from src.infrastructure.stores import save_index
from src.ingestion.bundle_archive import extract_bundle
from src.ingestion.indexing import build_index


def _write(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _prepare_data(args, output: Path, report: dict) -> None:
    from src.ingestion.preprocessed_bundle import load_preprocessed_bundle
    from src.ingestion.preprocessed_chunking import chunk_preprocessed_documents

    project = Path(__file__).resolve().parents[1]
    bundle = (extract_bundle(args.bundle, output / "input") if args.bundle.is_file()
              else args.bundle.resolve())
    identities = json.loads(args.identities.read_text(encoding="utf-8")) if args.identities else None
    report["stage"] = "load_documents"
    prepared = load_preprocessed_bundle(bundle, project_root=project, version=args.version, identities=identities)
    eligible = {s["document_id"] for s in prepared.report["sources"] if s["index_eligible"]}
    selected = [d for d in prepared.documents if d.document_id in eligible]
    report.update(prepared.report)
    report.update({"version": args.version, "input_route": {"html": "XML -> HTML", "json": "preprocessed JSON -> JSON"},
                   "output_dir": str(output), "formats": {}})
    _write(output / "documents.json", [d.model_dump(mode="json") for d in prepared.documents])
    _write(output / "identities.json", {s["source_key"]: s["document_id"] for s in report["sources"]})
    by_format = {}
    report["stage"] = "chunking"
    for fmt in ("html", "json"):
        docs = [d for d in selected if d.content_format == fmt]
        chunks = chunk_preprocessed_documents(docs, max_characters=args.max_characters)
        by_format[fmt] = chunks
        _write(output / f"chunks-{fmt}.json", [c.model_dump(mode="json") for c in chunks])
        report["formats"][fmt] = {"documents": len(docs), "chunks": len(chunks),
                                   "by_document": dict(Counter(c.source_document_id for c in chunks))}
    _write(output / "report.json", report)
    if args.openai_model:
        report["stage"] = "embedding_preflight"
        configure_key_file(args.api_key_file)
        embedder = BoundedEmbeddings(create_openai_embeddings(args.openai_model))
        # 양쪽 전체 입력을 API 호출 전에 확인한다. 중간 잘림/임의 평균으로 통과시키지 않는다.
        for fmt, chunks in by_format.items():
            counts = embedder.counts([c.content for c in chunks])
            report["formats"][fmt].update(input_tokens=sum(counts), max_chunk_tokens=max(counts))
        report["index_status"] = "running"
        report["stage"] = "embedding"
        _write(output / "report.json", report)
        # 바깥 prepare가 모든 단계의 실패를 한 번 기록한다.
        # 여기서 예외를 감싸면 실제 제공자 오류 종류가 RuntimeError로 가려진다.
        for fmt, chunks in by_format.items():
            index = build_index(chunks, embedder)
            save_index(index, output / f"index-{fmt}.json")
            report["formats"][fmt].update(index_id=index.metadata.index_id,
                                           dimension=index.metadata.dimension)
            _write(output / "report.json", report)
        report["index_status"] = "completed"


def prepare(args) -> dict:
    project = Path(__file__).resolve().parents[1]
    output = (args.output_dir or project / "data/processed" / f"p04-{uuid4().hex}").resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "running", "stage": "read_input", "output_dir": str(output),
              "index_status": "pending" if args.openai_model else "not_requested"}
    _write(output / "report.json", report)
    try:
        _prepare_data(args, output, report)
    except Exception as error:
        report.update(status="failed", error_type=type(error).__name__)
        if args.openai_model:
            report["index_status"] = "failed"
        try:
            _write(output / "report.json", report)
        except OSError:
            pass
        # 인증 설정까지 포함하므로 원본 예외 본문은 기록/출력하지 않는다.
        raise RuntimeError(f"{report['stage']} 단계 실패: {type(error).__name__}. report.json을 확인하세요.") from None
    report.update(status="completed", stage="completed")
    _write(output / "report.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True, help="v2 인계 ZIP 또는 전처리 폴더")
    parser.add_argument("--version", required=True, help="원문 버전, 예: v1. ZIP의 v2와는 별개")
    parser.add_argument("--identities", type=Path, help="source_key와 유지할 document_id 매핑")
    parser.add_argument("--output-dir", type=Path, help="새 결과 폴더. 기존 결과 덮어쓰기 금지")
    parser.add_argument("--max-characters", type=int, default=12000)
    parser.add_argument("--openai-model", choices=("text-embedding-3-small",), help="생략하면 외부 호출 없이 문서/청크만 준비")
    parser.add_argument("--api-key-file", type=Path, help="명시한 기존 로컬 키를 이 프로세스에서만 읽기")
    args = parser.parse_args()
    if args.api_key_file and not args.openai_model:
        parser.error("--api-key-file은 --openai-model과 함께 사용하세요.")
    try:
        report = prepare(args)
    except (ValueError, OSError, RuntimeError) as error:
        parser.exit(1, f"준비 실패: {error}\n")
    print(json.dumps({key: report[key] for key in ("output_dir", "index_status", "formats")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
