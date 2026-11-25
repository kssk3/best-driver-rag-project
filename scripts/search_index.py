"""실제 색인에서 질문과 가까운 근거를 확인한다. 답변 LLM/팀 A/B/C 검색 구현은 아니다."""

import argparse
import json
import math
from pathlib import Path

from src.infrastructure.embeddings import (
    BoundedEmbeddings,
    configure_key_file,
    create_openai_embeddings,
)
from src.infrastructure.stores import load_index, validate_vector


def rank_entries(index, query_vector, district: str, top_k: int):
    vector = validate_vector(query_vector)
    if len(vector) != index.metadata.dimension:
        raise ValueError("질문과 색인 벡터 차원이 다릅니다.")
    if not district.strip() or top_k < 1:
        raise ValueError("지역과 양의 top_k가 필요합니다.")
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0:
        raise ValueError("질문 벡터의 크기가 0입니다.")
    results = []
    for entry in index.entries:
        chunk = entry.chunk
        if chunk.scope_type == "unknown" or (
            chunk.scope_type == "district" and district not in chunk.districts
        ):
            continue
        other = math.sqrt(sum(v * v for v in entry.vector))
        if other == 0:
            continue
        score = sum(a * b for a, b in zip(vector, entry.vector, strict=True)) / (
            norm * other
        )
        results.append({"score": score, "chunk": chunk.model_dump(mode="json")})
    results.sort(key=lambda r: (-r["score"], r["chunk"]["chunk_id"]))
    return results[:top_k]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--index",
        type=Path,
        action="append",
        required=True,
        help="여러 번 지정하면 같은 질문 벡터로 비교",
    )
    parser.add_argument("--district", required=True)
    parser.add_argument("--question", help="생략하면 터미널에서 반복 입력")
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--api-key-file", type=Path)
    parser.add_argument(
        "--output", type=Path, help="질문 1건의 전체 근거 JSON을 새 파일에 저장"
    )
    args = parser.parse_args()
    if args.question is not None and not args.question.strip():
        parser.error("질문은 비어 있을 수 없습니다.")
    if not args.district.strip():
        parser.error("지역은 비어 있을 수 없습니다.")
    if args.output and not args.question:
        parser.error("--output은 --question과 함께 사용하세요.")
    if args.top_k < 1:
        parser.error("--top-k는 양수여야 합니다.")
    if args.output and args.output.exists():
        parser.error("기존 검색 기록을 덮어쓸 수 없습니다.")
    indexes = [(path, load_index(path)) for path in args.index]
    identities = {index.metadata.embedding_identity for _, index in indexes}
    if len(identities) != 1:
        parser.error("같은 모델/설정으로 만든 색인만 함께 비교할 수 있습니다.")
    identity = json.loads(next(iter(identities)))
    if (
        identity.get("provider") != "openai"
        or identity.get("model") != "text-embedding-3-small"
    ):
        parser.error("현재 이 확인 도구는 text-embedding-3-small 색인을 지원합니다.")
    configure_key_file(args.api_key_file)
    embedder = BoundedEmbeddings(
        create_openai_embeddings(identity["model"], identity.get("dimensions"))
    )
    if embedder.identity != next(iter(identities)):
        parser.error("색인의 임베딩 설정과 현재 환경이 다릅니다.")
    print(
        "실제 자료의 근거 검색 확인입니다. 답변 생성과 검색 품질 평가는 수행하지 않습니다."
    )
    print("종료: /종료")
    try:
        while True:
            question = args.question or input(f"[{args.district}] 질문: ").strip()
            if question in {"/종료", "/exit"}:
                break
            if not question.strip():
                continue
            try:
                vector = embedder.embed_query(question)
            except Exception as error:
                parser.exit(1, f"질문 임베딩 실패: {type(error).__name__}\n")
            record = {"question": question, "district": args.district, "results": []}
            for path, index in indexes:
                results = rank_entries(index, vector, args.district, args.top_k)
                record["results"].append(
                    {
                        "index_path": str(path),
                        "index_id": index.metadata.index_id,
                        "matches": results,
                    }
                )
                print(f"\n색인: {path}")
                for rank, result in enumerate(results, 1):
                    chunk = result["chunk"]
                    print(
                        f"{rank}. {chunk['title']} | {chunk['source_location']} | 유사도 {result['score']:.4f}"
                    )
                    print(chunk["content"][:1200])
                    print("출처:", chunk["source_url"])
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                with args.output.open("x", encoding="utf-8") as stream:
                    json.dump(record, stream, ensure_ascii=False, indent=2)
            if args.question:
                break
    except (EOFError, KeyboardInterrupt):
        pass


if __name__ == "__main__":
    main()
