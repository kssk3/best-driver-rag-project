"""실제 CLI로 예제·사용자 로그 분리와 실패 시 원본 보존 검사."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


def run_cli(cwd: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(REPO_ROOT)
    environment["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-m", "scripts.rewrite_query", *arguments],
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
        check=False,
    )


def test_examples_are_tagged_and_rerun_does_not_duplicate(tmp_path: Path):
    output = tmp_path / "results/local/p05_rewrite_examples.jsonl"

    first = run_cli(tmp_path, "--examples")
    assert first.returncode == 0, first.stderr
    original_bytes = output.read_bytes()
    rows = [json.loads(line) for line in original_bytes.decode("utf-8").splitlines()]
    assert [row["status"] for row in rows] == ["changed", "unchanged", "failed"]
    assert all(row["source"] == "example" for row in rows)

    again = run_cli(tmp_path, "--examples")
    assert again.returncode == 0, again.stderr
    assert output.read_bytes() == original_bytes


def test_examples_refuse_different_existing_output(tmp_path: Path):
    output = tmp_path / "existing.jsonl"
    original_bytes = b'{"unrelated": true}\n'
    output.write_bytes(original_bytes)

    result = run_cli(tmp_path, "--examples", "--output", str(output))

    assert result.returncode == 1
    assert output.read_bytes() == original_bytes


def test_questions_append_separately_and_leave_historical_log(tmp_path: Path):
    historical = tmp_path / "results/local/p05_rewrite.jsonl"
    historical.parent.mkdir(parents=True)
    historical.write_bytes(b"historical-log\n")
    examples = run_cli(tmp_path, "--examples")
    assert examples.returncode == 0, examples.stderr
    example_path = tmp_path / "results/local/p05_rewrite_examples.jsonl"
    example_bytes = example_path.read_bytes()
    questions = ["서대문구 우유팩 버리는 법", " 송파구 유리는 어디로? "]

    first = run_cli(tmp_path, "--question", questions[0], "--question", questions[1])
    assert first.returncode == 0, first.stderr
    output = tmp_path / "results/local/p05_rewrite_questions.jsonl"
    first_bytes = output.read_bytes()
    again = run_cli(tmp_path, "--question", questions[0])
    assert again.returncode == 0, again.stderr
    stored_bytes = output.read_bytes()
    rows = [json.loads(line) for line in stored_bytes.decode("utf-8").splitlines()]
    assert stored_bytes.startswith(first_bytes)
    assert [row["original_question"] for row in rows] == questions + questions[:1]
    assert all(row["source"] == "question" for row in rows)
    assert "서대문구".encode("utf-8") in stored_bytes
    assert example_path.read_bytes() == example_bytes
    assert historical.read_bytes() == b"historical-log\n"


def test_questions_refuse_example_tagged_output(tmp_path: Path):
    output = tmp_path / "examples.jsonl"
    examples = run_cli(tmp_path, "--examples", "--output", str(output))
    assert examples.returncode == 0, examples.stderr
    original_bytes = output.read_bytes()

    result = run_cli(
        tmp_path, "--question", "송파구 우유팩 버리는 법", "--output", str(output)
    )

    assert result.returncode == 1
    assert output.read_bytes() == original_bytes


@pytest.mark.parametrize(
    "questions",
    [
        ["", "송파구 우유팩 버리는 법"],
        ["서대문구 우유팩 버리는 법", " \t\n "],
    ],
)
def test_blank_anywhere_in_batch_exits_before_writing(tmp_path: Path, questions):
    output = tmp_path / "not-created" / "questions.jsonl"
    arguments = [
        argument for question in questions for argument in ("--question", question)
    ]

    result = run_cli(tmp_path, *arguments, "--output", str(output))

    assert result.returncode == 2
    assert not output.exists()
    assert not output.parent.exists()


def test_directory_output_reports_save_failure(tmp_path: Path):
    output = tmp_path / "output-directory"
    output.mkdir()

    result = run_cli(
        tmp_path, "--question", "송파구 우유팩 버리는 법", "--output", str(output)
    )

    assert result.returncode == 1
    assert list(output.iterdir()) == []


@pytest.mark.parametrize(
    ("original_bytes", "message"),
    [
        (b'{"original_question": "legacy"}\n', "1번째 줄에 출처 표시가 없습니다"),
        (b'{"source": "question"}\n\n', "2번째 줄이 비어 있습니다"),
        (b'{"source": "question"}\nnot-json\n', "2번째 줄이 올바른 JSON이 아닙니다"),
        (
            b'{"source": "question"}\n{"source": "example"}\n',
            "2번째 줄의 출처가 question이 아닙니다",
        ),
        (
            b'{"source": "question"}\n{"source": "question"}',
            "2번째 줄 끝에 줄바꿈이 필요합니다",
        ),
        (b"[]\n", "1번째 줄에 객체가 필요합니다"),
        (b"\xff\n", "1번째 줄이 UTF-8이 아닙니다"),
        (
            b'\xef\xbb\xbf{"source": "question"}\n',
            "1번째 줄에 UTF-8 BOM이 있습니다",
        ),
    ],
    ids=[
        "unmarked",
        "blank-row",
        "bad-json",
        "mixed",
        "missing-lf",
        "array",
        "utf8",
        "bom",
    ],
)
def test_invalid_existing_question_log_is_unchanged(tmp_path, original_bytes, message):
    output = tmp_path / "existing-questions.jsonl"
    output.write_bytes(original_bytes)

    result = run_cli(
        tmp_path, "--question", "송파구 우유팩 버리는 법", "--output", str(output)
    )

    assert result.returncode == 1
    assert message in result.stderr
    assert output.read_bytes() == original_bytes


@pytest.mark.parametrize(
    ("original_bytes", "expected_ending"),
    [(b"", b"\n"), (b'{"source": "question"}\r\n', b"\r\n")],
)
def test_empty_or_crlf_question_log_allows_append(
    tmp_path, original_bytes, expected_ending
):
    output = tmp_path / "questions.jsonl"
    output.write_bytes(original_bytes)
    question = "서대문구 우유팩 버리는 법"

    result = run_cli(tmp_path, "--question", question, "--output", str(output))

    assert result.returncode == 0, result.stderr
    stored_bytes = output.read_bytes()
    assert stored_bytes.startswith(original_bytes)
    appended = stored_bytes[len(original_bytes) :]
    assert appended.endswith(expected_ending)
    assert b"\r" not in appended[: -len(expected_ending)]
    assert b"\n" not in appended[: -len(expected_ending)]
    rows = [json.loads(line) for line in stored_bytes.decode("utf-8").splitlines()]
    assert len(rows) == (2 if original_bytes else 1)
    assert rows[-1]["source"] == "question"
    assert rows[-1]["original_question"] == question
