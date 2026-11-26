"""저장된 평가 입력을 검증한다. --judge로 팀 판단 모델을 사용해 채점한다."""

import argparse
import asyncio
import logging
import os
from contextlib import AsyncExitStack
from pathlib import Path

from src.evaluation.answer_metrics import score_archive


async def _run(args):
    judge_model = "gpt-6-luna" if args.judge else args.judge_model
    async with AsyncExitStack() as stack:
        metric = None

        async def ascore(**sample):
            nonlocal metric
            if metric is None:
                os.environ["RAGAS_DO_NOT_TRACK"] = "true"
                from openai import AsyncOpenAI
                from ragas.llms import llm_factory

                from src.evaluation.ragas_judge import ArchivedFaithfulness, judge_stage

                # Instructor는 실패 시 API 응답 본문을 오류 수준으로도 출력한다.
                logger = logging.getLogger("instructor")
                stack.callback(logger.setLevel, logger.level)
                logger.setLevel(logging.CRITICAL + 1)
                with judge_stage("setup"):
                    client = await stack.enter_async_context(
                        AsyncOpenAI(max_retries=0, timeout=30)
                    )
                    llm = llm_factory(
                        judge_model, client=client, max_retries=0 if args.judge else 1
                    )
                    metric = ArchivedFaithfulness(llm=llm)
            return await metric.ascore(**sample)

        return await score_archive(
            args.evaluation,
            args.cases_csv,
            args.output_dir,
            case_id=args.case_id,
            judge_model=judge_model or "",
            scorer=ascore if judge_model else None,
        )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation", type=Path, required=True)
    parser.add_argument("--cases-csv", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--case-id")
    judges = parser.add_mutually_exclusive_group()
    judges.add_argument(
        "--judge", action="store_true", help="팀 고정 모델로 재시도 없이 채점"
    )
    judges.add_argument("--judge-model", help="별도 실험에 사용할 판단 모델 ID")
    args = parser.parse_args(argv)
    try:
        ok = asyncio.run(_run(args))
    except (ValueError, OSError) as error:
        parser.exit(2, f"{error}\n")
    print(args.output_dir / "scores.csv")
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
