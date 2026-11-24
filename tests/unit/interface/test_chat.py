"""질문·답변 화면 테스트. 합성 예시 응답만 사용한다."""

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src.interface.chat import build_followup_request, is_safe_url

APP_PATH = Path(__file__).parent.parent.parent.parent / "app.py"


def ask(sample_name: str, question: str = "") -> AppTest:
    app = AppTest.from_file(str(APP_PATH)).run()
    app.text_input[0].set_value(question)
    app.selectbox[1].select(sample_name)
    return app.button[0].click().run()


def test_followup_request_keeps_question_and_district() -> None:
    request = build_followup_request("가상 질문", "송파구", {"housing_type": " 아파트 "})
    assert request == {
        "question": "가상 질문",
        "district": "송파구",
        "conditions": {"housing_type": "아파트"},
    }


def test_followup_request_drops_blank_conditions() -> None:
    request = build_followup_request("가상 질문", "송파구", {"housing_type": "  "})
    assert request["conditions"] == {}


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://example.invalid/a", True),
        ("http://example.invalid/a", True),
        ("javascript:alert(1)", False),
        ("", False),
        (None, False),
    ],
)
def test_is_safe_url(url: str | None, expected: bool) -> None:
    assert is_safe_url(url) is expected


@pytest.mark.parametrize(
    "sample_name, element, expected_text",
    [
        ("answered", "success", "가상"),
        ("needs_clarification", "warning", "추가 정보가 필요"),
        ("insufficient_evidence", "info", "답변이 어렵습니다"),
        ("error", "error", "처리 중 오류"),
    ],
)
def test_each_status_has_its_own_message(
    sample_name: str, element: str, expected_text: str
) -> None:
    app = ask(sample_name)
    assert not app.exception
    assert any(expected_text in item.value for item in getattr(app, element))


def test_error_is_not_shown_as_normal_refusal() -> None:
    app = ask("error")
    assert not any("답변이 어렵습니다" in item.value for item in app.info)


def test_followup_form_keeps_original_question_and_district() -> None:
    app = ask("needs_clarification", question="가상 질문")
    app.text_input[1].set_value("아파트")
    app.button[1].click().run()
    assert not app.exception
    assert json.loads(app.json[0].value) == {
        "question": "가상 질문",
        "district": "서대문구",
        "conditions": {"housing_type": "아파트"},
    }