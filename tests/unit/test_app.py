"""app.py가 오류 없이 실행되고 예시 응답임을 알리는지 확인한다."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP_PATH = Path(__file__).parent.parent.parent / "app.py"


def test_app_shows_fixture_notice_after_click() -> None:
    app = AppTest.from_file(str(APP_PATH)).run()
    assert not app.exception

    app.button[0].click().run()
    assert not app.exception
    assert any("예시(합성)" in caption.value for caption in app.caption)