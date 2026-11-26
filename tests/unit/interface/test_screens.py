"""app.py의 두 화면(랜딩, 결과)과 오른쪽 검증·비교 패널이 오류 없이 전환되는지 확인한다."""

from screen_helpers import button, fixture_app, new_app


def _run():
    app = new_app().run()
    assert not app.exception
    return app


def test_landing_is_default_and_shows_dev_panel_beside_it() -> None:
    app = _run()

    assert [tab.label for tab in app.tabs] == ["검증 패널", "비교 패널"]
    assert any("먼저 질문" in item.value for item in app.info)
    assert "view" not in app.session_state
    assert not app.radio  # 응답 방식 선택은 없다


def test_footer_records_that_this_is_an_internal_demo() -> None:
    app = _run()

    html = " ".join(str(item.value) for item in app.get("html"))
    assert "내부 데모" in html


def test_empty_question_shows_warning_and_stays_on_landing() -> None:
    app = _run()

    button(app, "물어보기").click().run()

    assert not app.exception
    assert any("질문을 입력하세요" in warning.value for warning in app.warning)
    assert "view" not in app.session_state


def test_result_screen_shows_answer_and_panel_for_the_same_response() -> None:
    app = fixture_app("answered", question="가상 질문")

    assert not app.exception
    assert app.success  # 왼쪽: 답변
    assert [tab.label for tab in app.tabs] == ["검증 패널", "비교 패널"]
    assert app.dataframe  # 오른쪽: 같은 응답의 후보 순위
    assert not any("먼저 질문" in item.value for item in app.info)


def test_response_from_another_mode_is_hidden() -> None:
    app = new_app()
    app.session_state["view"] = fixture_app("answered").session_state["view"]
    app.session_state["asked_mode"] = "다른 방식"
    app.run()

    assert not app.exception
    assert not app.success
    assert any(b.label == "물어보기" for b in app.button)
