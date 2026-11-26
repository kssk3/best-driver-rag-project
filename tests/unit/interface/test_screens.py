"""app.py의 두 화면(랜딩, 결과)과 아래 검증·비교 대시보드가 오류 없이 전환되는지 확인한다."""

from screen_helpers import button, fixture_app, new_app, press_submit, rank_table


def _run():
    app = new_app().run()
    assert not app.exception
    return app


def test_landing_is_default_and_shows_dashboard_below_it() -> None:
    app = _run()

    assert [tab.label for tab in app.tabs] == ["검증 패널", "비교 패널"]
    assert any("먼저 질문" in item.value for item in app.info)
    assert "view" not in app.session_state
    assert not app.radio  # 응답 방식 선택은 없다
    assert not app.error  # 설정이 있으면 안내 오류가 없다


def test_footer_records_that_this_is_an_internal_demo() -> None:
    app = _run()

    html = " ".join(str(item.value) for item in app.get("html"))
    assert "내부 데모" in html
    assert "합성 데모" not in html


def test_without_settings_the_page_explains_how_to_run(monkeypatch) -> None:
    monkeypatch.delenv("RAG_CHAT_SETTINGS")
    app = _run()

    [error] = app.error
    assert "RAG_CHAT_SETTINGS" in error.value
    assert "scripts.run_chat" in error.value
    assert "OPENAI_API_KEY" in error.value


def test_without_settings_a_question_is_not_answered(monkeypatch) -> None:
    monkeypatch.delenv("RAG_CHAT_SETTINGS")
    app = _run()

    app.text_input[0].set_value("페트병은 어떻게 버려요?")
    button(app, "물어보기").click().run()

    assert not app.exception
    assert "view" not in app.session_state  # 합성 응답으로 빠지지 않는다


def test_empty_question_shows_warning_and_stays_on_landing() -> None:
    app = _run()

    press_submit(app)

    assert not app.exception
    assert any("질문을 입력하세요" in warning.value for warning in app.warning)
    assert "view" not in app.session_state


def test_district_chip_starts_unselected_and_asks_to_choose() -> None:
    app = _run()
    assert app.pills[0].value is None

    app.text_input[0].set_value("가상 질문")
    button(app, "물어보기").click().run()

    assert any("지역을 선택하세요" in warning.value for warning in app.warning)
    assert "pending" not in app.session_state


def test_result_screen_shows_answer_and_dashboard_for_the_same_response() -> None:
    app = fixture_app("answered", question="가상 질문")

    assert not app.exception
    assert app.success  # 위: 답변
    assert [tab.label for tab in app.tabs] == ["검증 패널", "비교 패널"]
    assert rank_table(app)  # 아래 대시보드: 같은 응답의 후보 순위
    assert not any("먼저 질문" in item.value for item in app.info)


def test_landing_picks_the_district_with_chips_and_the_chat_screen_with_a_dropdown() -> (
    None
):
    landing = _run()
    assert landing.pills and not landing.selectbox  # 랜딩: 칩

    chat = fixture_app("answered", question="가상 질문", district="송파구")
    assert not chat.pills or all(p.label != "지역" for p in chat.pills)
    [select] = [s for s in chat.selectbox if s.label == "지역"]  # 대화 화면: 드롭다운
    assert select.value == "송파구"


def test_header_brand_links_back_to_the_landing() -> None:
    html = " ".join(str(item.value) for item in _run().get("html"))

    assert 'class="brand" href="./"' in html


def test_dashboard_title_has_no_internal_demo_chip() -> None:
    html = " ".join(str(item.value) for item in _run().get("html"))

    assert "검증·비교 대시보드" in html
    assert "<span>내부 데모</span>" not in html
