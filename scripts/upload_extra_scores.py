"""저장한 세 실험 지표를 검증하고 기존 Langfuse trace에 연결한다."""

import argparse
from pathlib import Path

from src.observability.extra_scores import missing_scores, prepare_scores
from src.observability.score_ledger import upload_scores
from src.observability.tracing import langfuse_post


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", required=True, type=Path)
    parser.add_argument(
        "--archive", required=True, type=Path, help="cases/runs/candidates.csv 폴더"
    )
    parser.add_argument("--expected-traces", required=True, type=int)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="실서버 읽기 대조")
    mode.add_argument(
        "--upload", action="store_true", help="기존 실행에 누락 점수만 전송"
    )
    args = parser.parse_args(argv)
    try:
        scores = prepare_scores(args.preview, args.archive, args.expected_traces)
        print(f"로컬 검증: 실행 {args.expected_traces}건, 숫자 점수 {len(scores)}개")
        if args.check or args.upload:
            client = langfuse_post()
            if args.upload:
                sent, waiting = upload_scores(client, scores)
                print(
                    f"신규 접수 {sent}개, 이전 접수 후 조회 대기 {waiting}개. --check로 확인하세요."
                )
            else:
                pending = missing_scores(client, scores)
                print(
                    f"서버 일치 {len(scores) - len(pending)}개, 미등록 {len(pending)}개"
                )
    except (TypeError, KeyError, ValueError, OSError) as error:
        parser.exit(2, f"{error}\n")


if __name__ == "__main__":
    main()
