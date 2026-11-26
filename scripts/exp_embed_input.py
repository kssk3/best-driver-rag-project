"""임베딩 입력 실험: 표 행의 공백 정리·표 맥락 평문이 검색 순위를 올리는지 새 개발용 문항으로 잰다.

사용: uv run --locked --env-file .env python -m scripts.exp_embed_input --output-dir results/local/embed-input-exp
청크 ID·본문은 그대로이고 검색 입력만 바꾼다. 답변은 만들지 않고(검색만) 정답 청크의 순위를 본다.
세 가지 조건을 같은 문항에 돌린다.
- base: 기존 색인 + 기존 BM25·재정렬 입력
- vec : 표 행 벡터만 평문으로 다시 임베딩(A와 B·C의 벡터 쪽에만 영향)
- full: vec + BM25·재정렬 입력의 글자 사이 공백 정리
최종셋(eval/test.json)은 쓰지 않는다. 문항은 eval/exp의 14개와 개발셋의 답변 가능 8개다.
모델 호출: 표 행 임베딩 약 432건, 질문 임베딩, C의 재정렬.
"""

import argparse
import csv
import json
from pathlib import Path

import src.retrieval.rerankers as rerankers_module
import src.retrieval.search as search_module
from src.contracts import PipelineRequest
from src.evaluation.answer_experiments.answer_evaluation_runtimes import (
    _embedding_settings,
    create_openai_embeddings,
    load_index,
    make_vector_retriever,
    resolve_request,
)
from src.evaluation.runner import load_evaluation_cases
from src.infrastructure.stores import IndexEntry, save_index
from src.ingestion.embedding_text import row_embedding_text, search_text
from src.retrieval.rerankers import make_openai_reranker

DEFAULT_INDEX = "data/processed/ordinance-v2-openai-small/index-json.json"
GROUPS = {"exp": "eval/exp/songpa-table-dev.json", "dev": "eval/dev.json"}
ORIGINAL_CHUNK_TEXT = search_module.chunk_text


def set_normalized_search_text(enabled: bool) -> None:
    """BM25(`search.chunk_text`)와 재정렬(`rerankers.chunk_text`)의 입력을 바꾼다. 명지님 파일은 고치지 않는다."""

    def wrapped(chunk):  # type: ignore[no-untyped-def]
        return search_text(ORIGINAL_CHUNK_TEXT(chunk), chunk.content)

    function = wrapped if enabled else ORIGINAL_CHUNK_TEXT
    search_module.chunk_text = function
    rerankers_module.chunk_text = function


def build_variant_index(base, embedder):  # type: ignore[no-untyped-def]
    texts = {
        i: row_embedding_text(entry.chunk.content)
        for i, entry in enumerate(base.entries)
        if entry.chunk.content_format == "json"
    }
    order = [i for i, t in texts.items() if t is not None]
    vectors = embedder.embed_documents([texts[i] for i in order])
    entries = list(base.entries)
    for i, vector in zip(order, vectors, strict=True):
        entries[i] = IndexEntry(chunk=entries[i].chunk, vector=list(vector))
    metadata = base.metadata.model_copy(
        update={"index_id": base.metadata.index_id + "-embed-input-exp"}
    )
    return base.model_copy(update={"metadata": metadata, "entries": entries}), len(
        order
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--index", default=DEFAULT_INDEX)
    parser.add_argument("--reranker-model", default="gpt-6-luna")
    args = parser.parse_args(argv)
    if args.output_dir.exists():
        parser.error("기존 결과를 덮어쓸 수 없습니다. 새 --output-dir를 지정하세요.")

    base = load_index(args.index)
    model, dims = _embedding_settings(base.metadata.embedding_identity)
    embedder = create_openai_embeddings(model, dims)
    variant, changed = build_variant_index(base, embedder)
    args.output_dir.mkdir(parents=True)
    save_index(variant, args.output_dir / "index-variant.json")
    print(f"표 행 {changed}개를 평문으로 다시 임베딩했다.", flush=True)

    reranker = make_openai_reranker(args.reranker_model)
    arms = {
        "base": (base, False),
        "vec": (variant, False),
        "full": (variant, True),
    }
    cases = []
    for group, path in GROUPS.items():
        for case in load_evaluation_cases(Path(path)):
            if case.expected_status == "answered":
                cases.append((group, case))

    rows = []
    for arm, (index, normalize) in arms.items():
        set_normalized_search_text(normalize)
        retrieve = make_vector_retriever(index, embedder, reranker=reranker)
        for group, case in cases:
            resolved = resolve_request(
                PipelineRequest(question=case.question, district=case.district)
            )
            for variant_name in "ABC":
                found = retrieve(resolved, variant=variant_name, top_k=10)
                ranks = [
                    c.rank for c in found if c.chunk.chunk_id in case.allowed_chunk_ids
                ]
                rows.append(
                    {
                        "arm": arm,
                        "group": group,
                        "case_id": case.case_id,
                        "variant": variant_name,
                        "first_rank": min(ranks) if ranks else "",
                    }
                )
        print(f"{arm} 완료", flush=True)
    set_normalized_search_text(False)

    with (args.output_dir / "hits.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (args.output_dir / "meta.json").write_text(
        json.dumps({"index": args.index, "rows_changed": changed, "groups": GROUPS}),
        encoding="utf-8",
    )
    for group in GROUPS:
        for arm in arms:
            line = []
            for v in "ABC":
                mine = [
                    r
                    for r in rows
                    if (r["group"], r["arm"], r["variant"]) == (group, arm, v)
                ]
                h1 = sum(r["first_rank"] == 1 for r in mine)
                h5 = sum(r["first_rank"] != "" and r["first_rank"] <= 5 for r in mine)
                line.append(f"{v}: Hit@1 {h1} Hit@5 {h5}/{len(mine)}")
            print(f"{group:3} {arm:5}", " | ".join(line))


if __name__ == "__main__":
    main()
