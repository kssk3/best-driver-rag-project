"""질문·답변 화면 테스트. 합성 예시 응답만 사용한다."""

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src.interface.adapter import Citation
from src.interface.chat import build_followup_request, format_citation, is_safe_url

APP_PATH = Path(__file__).parent.parent.parent.parent / "app.py"


def ask(sample_name: str, question: str = "") -> AppTest:
    app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
    app.text_input[0].set_value(question)
    app.selectbox[1].select(sample_name)
    return app.button[0].click().run()


def test_followup_request_keeps_question_and_district() -> None:
    request = build_followup_request(
        "가상 질문", "송파구", {"housing_type": " 아파트 "}
    )
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


def test_format_citation_escapes_brackets_and_shows_details() -> None:
    citation = Citation(
        "c1", "https://example.invalid/a", "[가상] 안내", "표 > 행", "v1"
    )
    assert format_citation(citation) == (
        "- [\\[가상\\] 안내](https://example.invalid/a) · 위치: 표 > 행 · 문서 버전: v1"
    )


@pytest.mark.parametrize("url", ["", None, "javascript:alert(1)"])
def test_format_citation_without_safe_link(url: str | None) -> None:
    assert format_citation(Citation("c1", url)) == "- c1 (원문 링크 없음)"


def test_conflicting_sources_are_both_shown_for_insufficient_evidence() -> None:
    app = ask("insufficient_evidence_conflict")
    assert not app.exception
    assert not app.error
    assert any("답변이 어렵습니다" in item.value for item in app.info)
    shown = " ".join(item.value for item in app.markdown)
    assert "월·수·금" in shown
    assert "화·목·일" in shown
    assert "예시 안내 웹페이지(가상)" in shown
    assert "예시 안내 PDF(가상)" in shown
    assert "PDF 3쪽 > 마지막 예시동 행" in shown
    assert "문서 버전: fx-v1" in shown
    assert "문서 버전: fx-v2" in shown


def test_plain_insufficient_evidence_shows_no_source_list() -> None:
    app = ask("insufficient_evidence")
    assert not any("확인한 출처" in item.value for item in app.markdown)


def test_followup_uses_submitted_request_not_current_inputs() -> None:
    app = ask("needs_clarification", question="가상 질문")
    app.text_input[0].set_value("바뀐 질문")
    app.selectbox[0].select("송파구")
    app.text_input[1].set_value("아파트")
    app.button[1].click().run()
    assert json.loads(app.json[0].value)["question"] == "가상 질문"
    assert json.loads(app.json[0].value)["district"] == "서대문구"


def test_blank_question_clears_previous_response() -> None:
    app = ask("answered", question="가상 질문")
    assert app.success
    app.radio[0].set_value("실행(합성 데모)").run()
    app.text_input[0].set_value("")
    app.button[0].click().run()
    assert not app.success


def test_clarification_shows_the_pipeline_message() -> None:
    def page() -> None:
        from src.interface.adapter import ViewResponse
        from src.interface.chat import render_response

        render_response(
            ViewResponse(
                "r",
                "fixture",
                "needs_clarification",
                "[가상] 동을 알려 주세요.",
                [],
                [],
                None,
                [],
                None,
            )
        )

    app = AppTest.from_function(page, default_timeout=10).run()
    assert any("동을 알려 주세요" in w.value for w in app.warning)


def test_insufficient_evidence_shows_answer_without_citations() -> None:
    def page() -> None:
        from src.interface.adapter import ViewResponse
        from src.interface.chat import render_response

        render_response(
            ViewResponse(
                "r",
                "fixture",
                "insufficient_evidence",
                "[가상] 근거가 없습니다.",
                [],
                [],
                None,
                [],
                None,
            )
        )

    app = AppTest.from_function(page, default_timeout=10).run()
    assert any("근거가 없습니다" in m.value for m in app.markdown)
