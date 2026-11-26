"""로컬 점수의 Langfuse 전송을 검증한다. --upload를 지정해야 전송한다."""

import argparse
from pathlib import Path
from sqlite3 import Error as SQLiteError

from src.observability.tracing import langfuse_post, publish_scores


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scores", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True, help="새 업로드 결과 CSV")
    parser.add_argument(
        "--judgments", type=Path, help="진술과 판정 사유를 함께 보낼 상세 JSONL"
    )
    parser.add_argument("--upload", action="store_true")
    parser.add_argument(
        "--retry-missing-spans",
        action="store_true",
        help="서버 수집 대기가 끝났는지 확인한 뒤 조회에서 누락된 미확인 span만 재전송",
    )
    parser.add_argument(
        "--recover-missing-root",
        metavar="RUN_ID",
        help="지정한 실행만 처리한다. 이전 전송과 서버 수집 종료를 확인한 뒤 누락된 루트를 복구한다.",
    )
    args = parser.parse_args(argv)
    try:
        ok = publish_scores(
            args.scores,
            args.report,
            langfuse_post() if args.upload else None,
            retry_missing=args.retry_missing_spans,
            recover_missing_root=args.recover_missing_root,
            judgments=args.judgments,
        )
    except (ValueError, OSError, SQLiteError) as error:
        parser.exit(2, f"{error}\n")
    print(args.report)
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
