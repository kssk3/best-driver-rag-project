"""app.py의 세 화면(랜딩, 결과, 개발자 모드)이 오류 없이 전환되는지 확인한다."""

import json
from pathlib import Path

from streamlit.testing.v1 import AppTest

from src.interface.adapter import to_view_response

ROOT = Path(__file__).parent.parent.parent.parent
APP_PATH = ROOT / "app.py"
SAMPLE_PATH = ROOT / "tests" / "fixtures" / "interface" / "sample_responses.json"
DEMO_MODE = "실행(합성 데모)"  # 일반 화면이 쓰는 응답 방식


def _run() -> AppTest:
    app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
    assert not app.exception
    return app


def _button(app: AppTest, label: str):
    return next(button for button in app.button if button.label == label)


def test_landing_is_default_and_hides_dev_tabs() -> None:
    app = _run()

    assert not app.tabs
    assert _button(app, "개발자 모드")
    assert "view" not in app.session_state


def test_empty_question_shows_warning_and_stays_on_landing() -> None:
    app = _run()

    _button(app, "물어보기").click().run()

    assert not app.exception
    assert any("질문을 입력하세요" in warning.value for warning in app.warning)
    assert "view" not in app.session_state


def test_result_screen_shows_answer_without_dev_widgets() -> None:
    raw = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))["answered"]
    app = AppTest.from_file(str(APP_PATH), default_timeout=10)
    app.session_state["view"] = to_view_response(raw, kind="demo")
    app.session_state["asked_mode"] = DEMO_MODE
    app.run()

    assert not app.exception
    assert app.success
    assert not app.tabs
    assert not app.radio


def test_dev_button_opens_dev_mode_with_three_tabs() -> None:
    app = _run()

    _button(app, "개발자 모드").click().run()

    assert not app.exception
    assert [tab.label for tab in app.tabs] == [
        "사용자 화면 미리보기",
        "검증 패널",
        "비교 패널",
    ]


def test_dev_query_param_opens_dev_mode() -> None:
    app = AppTest.from_file(str(APP_PATH), default_timeout=10)
    app.query_params["dev"] = "1"
    app.run()

    assert not app.exception
    assert len(app.tabs) == 3


def test_dev_fixture_response_shows_fixture_notice() -> None:
    app = _run()
    _button(app, "개발자 모드").click().run()

    _button(app, "질문하기").click().run()

    assert not app.exception
    assert any("예시(합성)" in caption.value for caption in app.caption)
