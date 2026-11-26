"""명시한 공용 문서 JSON을 색인한다. python -m scripts.index --help 참조."""

import argparse
from pathlib import Path

from src.infrastructure.embeddings import DemoHashEmbeddings, create_openai_embeddings
from src.infrastructure.stores import save_index
from src.ingestion.chunking import chunk_documents
from src.ingestion.indexing import build_index
from src.ingestion.loaders import load_source_documents


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--documents", type=Path, required=True, help="SourceDocument 목록 JSON"
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="교체할 로컬 색인 JSON"
    )
    parser.add_argument(
        "--content-format", choices=("html", "json"), help="색인에 포함할 전처리 형식"
    )
    provider = parser.add_mutually_exclusive_group(required=True)
    provider.add_argument(
        "--demo", action="store_true", help="네트워크 없는 흐름 검증용 해시 벡터"
    )
    provider.add_argument(
        "--openai-model", help="실제로 API를 호출할 임베딩 모델을 명시"
    )
    parser.add_argument("--dimensions", type=int, help="선택 모델의 출력 차원")
    parser.add_argument("--max-characters", type=int, default=20000)
    args = parser.parse_args()
    if args.documents.resolve() == args.output.resolve():
        parser.error("입력 문서와 출력 색인 경로는 달라야 합니다.")
    # 공용 로더에서 검사한다. sources.json, 평가 정답표, 임의 폴더는 자동 수집하지 않는다.
    documents = load_source_documents(args.documents)
    if args.content_format:
        documents = [
            doc for doc in documents if doc.content_format == args.content_format
        ]
        if not documents:
            parser.error(f"{args.content_format} 형식의 문서가 없습니다.")
    chunks = chunk_documents(documents, max_characters=args.max_characters)
    embedder = (
        DemoHashEmbeddings(args.dimensions if args.dimensions is not None else 64)
        if args.demo
        else create_openai_embeddings(args.openai_model, args.dimensions)
    )
    index = build_index(chunks, embedder)
    save_index(index, args.output)
    print(f"{len(index.entries)}개 청크 저장: {args.output}")
    if args.demo:
        print("데모 해시 벡터입니다. 의미 검색 품질 평가에 사용할 수 없습니다.")
        if len({doc.content_format for doc in documents}) > 1:
            print(
                "HTML/JSON이 혼합되어 있습니다. 동등 비교에는 --content-format으로 형식별 색인을 만드세요."
            )


if __name__ == "__main__":
    main()
