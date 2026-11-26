"""P05 질문 정제 결과 저장. python -m scripts.rewrite_query로 실행."""

import argparse
import json
from codecs import BOM_UTF8
from pathlib import Path

from src.query.rewrite import append_rewrite_log, rewrite_question

QUESTION_LOG = Path("results/local/p05_rewrite_questions.jsonl")
EXAMPLE_LOG = Path("results/local/p05_rewrite_examples.jsonl")


def _save_examples(path: Path) -> bool:
    """실습 결과 3줄 생성. 동일한 예시 파일은 재사용."""

    def fail(_question: str) -> str:
        raise RuntimeError("실습용 오류")

    question = "송파구에서 우유팩은 어떻게 버려?"
    results = [
        rewrite_question(question),
        rewrite_question("송파구에서 페트병은 어떻게 버려?"),
        rewrite_question(question, normalizer=fail),
    ]
    content = "".join(
        json.dumps({**row, "source": "example"}, ensure_ascii=False) + "\n"
        for row in results
    ).encode("utf-8")

    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as file:
            file.write(content)
    except FileExistsError:
        if path.is_file() and path.read_bytes() == content:
            return False
        raise FileExistsError(f"예시를 저장할 새 파일 경로 필요: {path}") from None
    return True


def _question_log_newline(path: Path) -> str:
    """기존 로그를 검증하고 마지막 줄의 줄끝 반환. 새 파일은 LF."""
    newline = "\n"
    try:
        with path.open("rb") as file:
            for number, raw_line in enumerate(file, start=1):
                if raw_line.startswith(BOM_UTF8):
                    raise ValueError(
                        f"JSONL {number}번째 줄에 UTF-8 BOM이 있습니다. "
                        "UTF-8(BOM 없음)으로 저장하세요."
                    )
                try:
                    line = raw_line.decode("utf-8")
                except UnicodeDecodeError as error:
                    raise ValueError(f"{number}번째 줄이 UTF-8이 아닙니다.") from error
                if not line.strip():
                    raise ValueError(f"JSONL {number}번째 줄이 비어 있습니다.")
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as error:
                    raise ValueError(
                        f"{number}번째 줄이 올바른 JSON이 아닙니다."
                    ) from error
                if not isinstance(record, dict):
                    raise ValueError(f"JSONL {number}번째 줄에 객체가 필요합니다.")
                if "source" not in record:
                    raise ValueError(
                        f"{number}번째 줄에 출처 표시가 없습니다. 새 파일을 지정하세요."
                    )
                if record["source"] != "question":
                    raise ValueError(
                        f"{number}번째 줄의 출처가 question이 아닙니다. "
                        "새 파일을 지정하세요."
                    )
                if not line.endswith("\n"):
                    raise ValueError(f"{number}번째 줄 끝에 줄바꿈이 필요합니다.")
                newline = "\r\n" if raw_line.endswith(b"\r\n") else "\n"
    except FileNotFoundError:
        return "\n"
    return newline


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--question", action="append", help="변환할 질문 (반복 가능)")
    inputs.add_argument(
        "--examples", action="store_true", help="변경·유지·실습용 실패 재현"
    )
    parser.add_argument(
        "--output",
        type=Path,
        help=f"저장할 JSONL 파일 (질문: {QUESTION_LOG}, 예시: {EXAMPLE_LOG})",
    )
    args = parser.parse_args()

    if args.question and any(not question.strip() for question in args.question):
        parser.error("질문은 비어 있거나 공백만 포함할 수 없습니다.")

    output = args.output or (EXAMPLE_LOG if args.examples else QUESTION_LOG)

    try:
        if args.examples:
            saved = _save_examples(output)
            if saved:
                print(f"{output}에 예시 3건 저장")
            else:
                print(f"{output}의 기존 예시 3건 확인")
        else:
            newline = _question_log_newline(output)
            for question in args.question:
                result = rewrite_question(question)
                append_rewrite_log(
                    output, {**result, "source": "question"}, newline=newline
                )
            print(f"{output}에 {len(args.question)}건 추가")
    except (OSError, ValueError) as error:
        parser.exit(1, f"로그 저장 실패: {error}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
