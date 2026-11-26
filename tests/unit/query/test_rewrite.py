"""질문의 지역·의도 보존과 변환 실패·JSONL 기록 회귀 검사."""

import json
from pathlib import Path

import pytest

from src.query import rewrite


def test_multiple_aliases_add_one_canonical_term_and_preserve_intent():
    question = "  서대문구와 송파구에서 우유팩과 두유팩은 어디에 버려?  \n"

    result = rewrite.rewrite_question(question)

    assert result == {
        "original_question": question,
        "rewritten_question": (
            "서대문구와 송파구에서 우유팩과 두유팩은 어디에 버려? (종이팩)"
        ),
        "status": "changed",
    }


@pytest.mark.parametrize(
    "question",
    [
        "  송파구 종이팩인 우유팩은 어디에 버려?  \n",
        "  서대문구 깨진 유리는 어디에 버려?  \n",
        "\t \n",
    ],
)
def test_existing_canonical_or_unmatched_input_is_preserved_exactly(question):
    assert rewrite.rewrite_question(question) == {
        "original_question": question,
        "rewritten_question": question,
        "status": "unchanged",
    }


def test_failed_rewrite_returns_original_without_error_message(monkeypatch):
    question = " 송파구 우유팩을 버릴 곳이 어디야? "

    def fail(_question):
        raise RuntimeError("sensitive-detail-not-for-log")

    monkeypatch.setattr(rewrite, "normalize_question", fail)

    assert rewrite.rewrite_question(question) == {
        "original_question": question,
        "rewritten_question": question,
        "status": "failed",
        "error_type": "RuntimeError",
    }


def test_log_creates_parent_and_appends_utf8_records(tmp_path: Path, monkeypatch):
    log_path = tmp_path / "nested" / "logs" / "rewrite.jsonl"
    changed = rewrite.rewrite_question("서대문구 우유팩 버리는 법")
    rewrite.append_rewrite_log(log_path, changed)
    first_bytes = log_path.read_bytes()

    def fail(_question):
        raise ValueError("sensitive-detail-not-for-log")

    monkeypatch.setattr(rewrite, "normalize_question", fail)
    failed = rewrite.rewrite_question(" 송파구 두유팩 버리는 법 ")
    rewrite.append_rewrite_log(log_path, failed)
    stored_bytes = log_path.read_bytes()

    assert stored_bytes.startswith(first_bytes)
    assert "서대문구".encode("utf-8") in stored_bytes
    assert "송파구".encode("utf-8") in stored_bytes
    assert b"sensitive-detail-not-for-log" not in stored_bytes
    assert [json.loads(line) for line in stored_bytes.decode("utf-8").splitlines()] == [
        changed,
        failed,
    ]
