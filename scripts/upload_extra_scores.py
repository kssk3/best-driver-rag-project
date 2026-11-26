"""저장한 세 실험 지표를 검증하고 기존 Langfuse trace에 연결한다."""

import argparse
from pathlib import Path

from src.observability.extra_scores import missing_scores, prepare_scores, send_missing
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
            pending = missing_scores(client, scores)
            print(f"서버 일치 {len(scores) - len(pending)}개, 미등록 {len(pending)}개")
            if args.upload and pending:
                send_missing(client, pending)
                print("전송 접수 완료. 수집 후 --check로 다시 조회하세요.")
    except (TypeError, KeyError, ValueError, OSError) as error:
        parser.exit(2, f"{error}\n")


if __name__ == "__main__":
    main()
