"""로컬 점수의 Langfuse 전송을 검증한다. --upload를 지정해야 전송한다."""

import argparse
from pathlib import Path

from src.observability.tracing import langfuse_post, publish_scores


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scores", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True, help="새 업로드 결과 CSV")
    parser.add_argument(
        "--judgments", type=Path, help="진술과 판정 사유를 함께 보낼 상세 JSONL"
    )
    parser.add_argument("--upload", action="store_true")
    args = parser.parse_args(argv)
    try:
        ok = publish_scores(
            args.scores,
            args.report,
            langfuse_post() if args.upload else None,
            judgments=args.judgments,
        )
    except (ValueError, OSError) as error:
        parser.exit(2, f"{error}\n")
    print(args.report)
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
