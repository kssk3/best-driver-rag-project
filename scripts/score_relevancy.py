"""저장된 답변의 answer_relevancy를 Ragas로 채점해 <실행 폴더>/relevancy.csv에 쓴다 (유료 호출).
이미 있는 파일은 덮어쓰지 않고 호출 전에 중단한다(--output으로 새 경로를 지정).

사용: uv run --locked --env-file .env python -m scripts.score_relevancy results/<실행 폴더>
되묻기(needs_clarification)와 정보 부족 안내(insufficient_evidence)도 채점하되 status 열로 구분한다. 평균에 넣을지는 보고서에서 정한다.
한 행의 호출이 실패하면 score를 비우고 error에 오류 종류만 남긴다(답변 원문은 남기지 않는다).
"""

import argparse
import asyncio
import csv
import math
import os
from datetime import UTC, datetime
from pathlib import Path

JUDGE_MODEL = "gpt-6-luna"
EMBEDDING_MODEL = "text-embedding-3-small"
# 보류 안내(needs_clarification, insufficient_evidence)도 채점하고 status 열로 구분한다.
SCORED_STATUSES = ("answered", "needs_clarification", "insufficient_evidence")
FIELDS = [
    "run_id",
    "case_id",
    "configuration",
    "variant",
    "rewrite_enabled",
    "status",
    "score",
    "error",
    "timestamp",
]


def checked_score(value: float) -> tuple[str, str]:
    """(점수 문자열, 오류). 업로드 검증은 0~1만 받으므로 범위 밖 값은 성공으로 내보내지 않는다."""
    if math.isfinite(value) and 0 <= value <= 1:
        return f"{value:.4f}", ""
    return "", "score_out_of_range"


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
        score, error, stamp = "", "", ""
        if row["status"] in SCORED_STATUSES and row["answer"]:
            try:
                result = await metric.ascore(
                    user_input=row["original_question"], response=row["answer"]
                )
                score, error = checked_score(float(result.value))
                if score:
                    stamp = datetime.now(UTC).isoformat(timespec="milliseconds")
            except Exception as exc:  # 한 행의 실패가 전체를 멈추지 않게 한다.
                error = type(exc).__name__
        else:
            error = "no_answer"
        out.append(
            {
                "run_id": row["run_id"],
                "case_id": row["case_id"],
                "configuration": row["configuration"],
                "variant": row.get("variant") or row["configuration"],
                "rewrite_enabled": row["rewrite_enabled"],
                "status": row["status"],
                "score": score,
                "error": error,
                "timestamp": stamp,  # 점수를 얻은 UTC 시각. 업로드 시 원래 채점 시각으로 쓴다.
            }
        )
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument(
        "--output", type=Path, help="기본값은 <실행 폴더>/relevancy.csv"
    )
    args = parser.parse_args(argv)
    path = args.output or args.archive / "relevancy.csv"
    if path.exists():  # 유료 호출 전에 막아 기존 점수를 지킨다.
        raise SystemExit(f"{path}가 이미 있습니다. --output으로 새 경로를 지정하세요.")
    with (args.archive / "runs.csv").open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    # 기록 없이 실패한 행은 run_id가 비어 있으므로(채점 대상 아님) 중복 검사에서 뺀다.
    if any(
        not r["run_id"].strip() and r["status"] in SCORED_STATUSES and r["answer"]
        for r in rows
    ):  # 실행 ID가 없으면 점수를 원본 실행에 연결할 수 없으므로 유료 호출 전에 막는다.
        raise SystemExit("채점할 답변 행에 run_id가 없습니다.")
    ids = [r["run_id"].strip() for r in rows if r["run_id"].strip()]
    if len(set(ids)) != len(ids):
        raise SystemExit("runs.csv의 run_id가 중복됩니다.")
    # 유료 호출이 끝난 뒤 쓰기에 실패하지 않도록 출력 파일을 먼저 만든다.
    with path.open("x", encoding="utf-8", newline="") as file:
        try:
            scored = asyncio.run(_score(rows))
        except BaseException:
            file.close()
            path.unlink()
            raise
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(scored)
    failed = sum(1 for r in scored if r["error"])
    print(f"{len(scored)}행 중 점수 없음 {failed}행 -> {path}")


if __name__ == "__main__":
    main()
