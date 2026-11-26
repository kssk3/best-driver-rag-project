"""검증 패널 화면 테스트. 합성 예시 응답만 사용한다."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP_PATH = Path(__file__).parent.parent.parent.parent / "app.py"


def dev_app() -> AppTest:
    """예전 사용자 화면의 위젯은 개발자 모드 미리보기 탭으로 옮겨졌다."""
    app = AppTest.from_file(str(APP_PATH), default_timeout=10)
    app.session_state["dev"] = True
    return app


def ask(sample_name: str, district: str = "서대문구") -> AppTest:
    app = dev_app().run()
    app.selectbox[0].select(district)
    app.selectbox[1].select(sample_name)
    return app.button[1].click().run()


def test_panel_asks_for_question_first() -> None:
    app = dev_app().run()
    assert not app.exception
    assert any("먼저 질문" in item.value for item in app.info)


def test_clean_answer_shows_no_alert_and_candidate_table() -> None:
    app = ask("answered")
    assert not app.exception
    assert any("경고 없음" in item.value for item in app.success)
    table = app.dataframe[0].value
    assert list(table["chunk_id"]) == ["fx-chunk-001", "fx-chunk-002", "fx-chunk-003"]
    assert list(table["모델"]) == ["예", "예", "아니오"]
    assert list(table["인용"]) == ["예", "아니오", "아니오"]


def test_district_used_when_asking_is_checked() -> None:
    app = ask("answered", district="송파구")
    assert any("[W1]" in item.value for item in app.warning)


def test_error_is_shown_as_error_in_panel() -> None:
    app = ask("error")
    assert any(
        "[W7]" in item.value and "검색 호출 실패" in item.value for item in app.error
    )


def test_unknown_model_input_is_not_shown_as_empty() -> None:
    app = ask("insufficient_evidence")
    assert any("알 수 없습니다" in item.value for item in app.info)
    assert list(app.dataframe[0].value["모델"]) == ["알 수 없음"]


def test_common_scope_candidate_is_labelled_common_not_unknown() -> None:
    def page() -> None:
        from src.interface.adapter import Candidate, ViewResponse
        from src.interface.inspection import render_inspection

        view = ViewResponse(
            "r",
            "demo",
            "answered",
            "[가상]",
            [],
            [
                Candidate("c1", None, 0.8, "[가상]", rank=1, scope_type="common"),
                Candidate("c2", None, 0.7, "[가상]", rank=2, scope_type="unknown"),
            ],
            ["c1", "c2"],
            [],
            None,
        )
        render_inspection(view, "서대문구")

    app = AppTest.from_function(page, default_timeout=10).run()
    assert list(app.dataframe[0].value["지역"]) == ["공통", "알 수 없음"]


def test_switching_mode_hides_stale_response_from_inspection_panel() -> None:
    app = ask("answered")
    assert not any("먼저 질문" in item.value for item in app.info)
    app.radio[0].set_value("합성 데모").run()
    assert any("먼저 질문" in item.value for item in app.info)
