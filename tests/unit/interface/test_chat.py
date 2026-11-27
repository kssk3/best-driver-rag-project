"""질문·답변 화면 테스트. 합성 예시 응답만 사용한다."""

import json

import pytest
from screen_helpers import FIXTURES, button, fixture_app
from streamlit.testing.v1 import AppTest

from src.interface.chat import build_followup_request, is_safe_url


def ask(sample_name: str, question: str = "") -> AppTest:
    return fixture_app(sample_name, question=question)


def clarification_page(fixtures: str) -> None:
    # 예시 응답은 실행 모드가 아니라서 되묻기가 요청을 보내지 않고 보여 주기만 한다.
    import json  # noqa: F811  (from_function은 함수 본문만 복사한다)
    from pathlib import Path

    from src.interface.adapter import to_view_response
    from src.interface.chat import render_response

    path = Path(fixtures) / "sample_responses.json"
    raw = json.loads(path.read_text(encoding="utf-8"))["needs_clarification"]
    render_response(
        to_view_response(raw, kind="fixture"), question="가상 질문", district="서대문구"
    )


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
    app = AppTest.from_function(
        clarification_page, args=(str(FIXTURES),), default_timeout=10
    ).run()
    app.text_input[0].set_value("아파트")
    app.button[0].click().run()
    assert not app.exception
    assert json.loads(app.json[0].value) == {
        "question": "가상 질문",
        "district": "서대문구",
        "conditions": {"housing_type": "아파트"},
    }


def test_conflicting_sources_are_both_shown_for_insufficient_evidence() -> None:
    app = ask("insufficient_evidence_conflict")
    assert not app.exception
    assert not app.error
    assert any("답변이 어렵습니다" in item.value for item in app.info)
    shown = " ".join(item.value for item in app.markdown)
    assert "월·수·금" in shown
    assert "화·목·일" in shown
    chips = " ".join(item.value for item in app.get("html"))
    assert "예시 안내 웹페이지(가상)" in chips
    assert "예시 안내 PDF(가상)" in chips


def test_plain_insufficient_evidence_shows_no_source_list() -> None:
    app = ask("insufficient_evidence")
    assert not any("확인한 출처" in item.value for item in app.markdown)


def test_blank_question_clears_previous_response() -> None:
    app = ask("answered", question="가상 질문")
    assert app.success
    app.text_input[0].set_value("")
    button(app, "다시 묻기").click().run()
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


def test_followup_request_sends_district_and_dong_at_top_level_and_confirms_district() -> (
    None
):
    request = build_followup_request(
        "가상 질문", "송파구", {"district": "서대문구", "dong": "연희동", "item": "병"}
    )
    assert request == {
        "question": "가상 질문",
        "district": "서대문구",
        "dong": "연희동",
        # 되묻기에서 구를 입력했으므로 확정 표시를 전용 필드로 보낸다(조건에는 섞지 않는다).
        "district_confirmed": True,
        "conditions": {"item": "병"},
    }


def test_followup_inputs_are_cleared_for_a_new_request() -> None:
    app = ask("needs_clarification", question="가상 질문")
    app.text_input[1].set_value("아파트").run()
    assert "followup:housing_type" in app.session_state
    app.text_input[0].set_value("")
    button(app, "다시 묻기").click().run()
    assert not any(key.startswith("followup:") for key in app.session_state)


def test_error_shows_pipeline_safe_message_but_not_internal_detail() -> None:
    def page() -> None:
        from src.interface.adapter import ViewResponse
        from src.interface.chat import render_response

        render_response(
            ViewResponse(
                "r",
                "fixture",
                "error",
                "[가상] 답변 모델에 연결하지 못했습니다.",
                [],
                [],
                None,
                [],
                "[가상] 내부 오류 상세",
            )
        )

    app = AppTest.from_function(page, default_timeout=10).run()
    assert any("답변 모델에 연결하지 못했습니다" in e.value for e in app.error)
    assert not any("내부 오류 상세" in e.value for e in app.error)


def test_error_after_record_failure_does_not_show_the_successful_answer() -> None:
    def page() -> None:
        from src.interface.adapter import StageError, ViewResponse
        from src.interface.chat import render_response

        render_response(
            ViewResponse(
                "r",
                "demo",
                "error",
                "[가상] 성공한 답변",
                [],
                [],
                None,
                [],
                "기록 실패",
                stage_errors=[StageError("record", "x.record_failed", "기록 실패")],
            )
        )

    app = AppTest.from_function(page, default_timeout=10).run()
    assert not any("성공한 답변" in e.value for e in app.error)
    assert any("처리 중 오류" in e.value for e in app.error)


def test_error_keeps_primary_message_when_record_also_failed() -> None:
    def page() -> None:
        from src.interface.adapter import StageError, ViewResponse
        from src.interface.chat import render_response

        render_response(
            ViewResponse(
                "r",
                "demo",
                "error",
                "[가상] 답변 모델에 연결하지 못했습니다.",
                [],
                [],
                None,
                [],
                "x",
                error_code="x.generate_failed",
                stage_errors=[
                    StageError("generate", "x.generate_failed", None),
                    StageError("record", "x.record_failed", None),
                ],
            )
        )

    app = AppTest.from_function(page, default_timeout=10).run()
    assert any("답변 모델에 연결하지 못했습니다" in e.value for e in app.error)


def test_recoverable_stage_failure_plus_record_failure_hides_successful_answer() -> (
    None
):
    def page() -> None:
        from src.interface.adapter import StageError, ViewResponse
        from src.interface.chat import render_response

        render_response(
            ViewResponse(
                "r",
                "demo",
                "error",
                "[가상] 성공한 답변",
                [],
                [],
                None,
                [],
                "x",
                error_code="x.record_failed",
                stage_errors=[
                    StageError("place_lookup", "x.place_failed", None),
                    StageError("record", "x.record_failed", None),
                ],
            )
        )

    app = AppTest.from_function(page, default_timeout=10).run()
    assert not any("성공한 답변" in e.value for e in app.error)
    assert any("처리 중 오류" in e.value for e in app.error)


def test_primary_failure_keeps_message_even_when_error_codes_collide() -> None:
    # 일반 예외끼리는 같은 코드(common.unexpected_error)를 받을 수 있다.
    def page() -> None:
        from src.interface.adapter import StageError, ViewResponse
        from src.interface.chat import render_response

        code = "common.unexpected_error"
        render_response(
            ViewResponse(
                "r",
                "demo",
                "error",
                "[가상] 답변 모델에 연결하지 못했습니다.",
                [],
                [],
                None,
                [],
                "x",
                error_code=code,
                stage_errors=[
                    StageError("generate", code, None),
                    StageError("record", code, None),
                ],
            )
        )

    app = AppTest.from_function(page, default_timeout=10).run()
    assert any("답변 모델에 연결하지 못했습니다" in e.value for e in app.error)


def test_standard_refusal_line_is_not_repeated_under_the_fixed_notice() -> None:
    def page() -> None:
        from src.interface.adapter import ViewResponse
        from src.interface.chat import render_response

        render_response(
            ViewResponse(
                "r",
                "fixture",
                "insufficient_evidence",
                "현재 확인한 자료로는 답변하기 어렵습니다.\n서울시 안내는 월요일입니다.",
                [],
                [],
                None,
                [],
                None,
            )
        )

    app = AppTest.from_function(page, default_timeout=10).run()
    shown = " ".join(m.value for m in app.markdown)
    assert (
        "답변하기 어렵습니다" not in shown
    )  # 고정 안내와 같은 뜻이라 되풀이하지 않는다.
    assert "월요일" in shown  # 정보가 더해지는 줄은 그대로 보인다.
    assert len(app.info) == 1
