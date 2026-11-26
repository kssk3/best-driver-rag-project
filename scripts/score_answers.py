"""저장된 평가 입력을 검증한다. --judge-model 지정 시에만 Ragas로 채점한다."""

import argparse
import asyncio
import os
from contextlib import AsyncExitStack
from pathlib import Path

from src.evaluation.answer_metrics import score_archive


async def _run(args):
    async with AsyncExitStack() as stack:
        metric = None

        async def ascore(**sample):
            nonlocal metric
            if metric is None:
                os.environ["RAGAS_DO_NOT_TRACK"] = "true"
                from openai import AsyncOpenAI
                from ragas.llms import llm_factory
                from ragas.metrics.collections import Faithfulness

                client = await stack.enter_async_context(
                    AsyncOpenAI(max_retries=0, timeout=30)
                )
                llm = llm_factory(args.judge_model, client=client, max_retries=1)
                metric = Faithfulness(llm=llm)
            return await metric.ascore(**sample)

        return await score_archive(
            args.evaluation,
            args.cases_csv,
            args.output_dir,
            case_id=args.case_id,
            judge_model=args.judge_model or "",
            scorer=ascore if args.judge_model else None,
        )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation", type=Path, required=True)
    parser.add_argument("--cases-csv", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--case-id")
    parser.add_argument("--judge-model")
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
