"""저장된 답변의 answer_relevancy를 Ragas로 채점해 <실행 폴더>/relevancy.csv에 쓴다 (유료 호출).

사용: uv run --locked --env-file .env python -m scripts.score_relevancy results/<실행 폴더>
정보 부족 안내(insufficient_evidence)도 채점하되 status 열로 구분한다. 평균에 넣을지는 보고서에서 정한다.
한 행의 호출이 실패하면 score를 비우고 error에 오류 종류만 남긴다(답변 원문은 남기지 않는다).
"""

import argparse
import asyncio
import csv
import os
from pathlib import Path

JUDGE_MODEL = "gpt-6-luna"
EMBEDDING_MODEL = "text-embedding-3-small"


async def _score(rows: list[dict]) -> list[dict]:
    os.environ["RAGAS_DO_NOT_TRACK"] = "true"
    from openai import AsyncOpenAI
    from ragas.embeddings.base import embedding_factory
    from ragas.llms import llm_factory
    from ragas.metrics.collections import AnswerRelevancy

    client = AsyncOpenAI(max_retries=1, timeout=60)
    metric = AnswerRelevancy(
        llm=llm_factory(JUDGE_MODEL, client=client, max_retries=1),
        embeddings=embedding_factory("openai", model=EMBEDDING_MODEL, client=client),
    )
    out = []
    for row in rows:
        score, error = "", ""
        if row["status"] in ("answered", "insufficient_evidence") and row["answer"]:
            try:
                result = await metric.ascore(
                    user_input=row["original_question"], response=row["answer"]
                )
                score = f"{float(result.value):.4f}"
            except Exception as exc:  # 한 행의 실패가 전체를 멈추지 않게 한다.
                error = type(exc).__name__
        else:
            error = "no_answer"
        out.append(
            {
                "case_id": row["case_id"],
                "configuration": row["configuration"],
                "rewrite_enabled": row["rewrite_enabled"],
                "status": row["status"],
                "score": score,
                "error": error,
            }
        )
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args(argv)
    with (args.archive / "runs.csv").open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    scored = asyncio.run(_score(rows))
    path = args.archive / "relevancy.csv"
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(scored[0]))
        writer.writeheader()
        writer.writerows(scored)
    failed = sum(1 for r in scored if r["error"])
    print(f"{len(scored)}행 중 점수 없음 {failed}행 -> {path}")


if __name__ == "__main__":
    main()
