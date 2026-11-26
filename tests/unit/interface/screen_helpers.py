"""app.py 화면을 시험하는 공용 도우미. 외부 호출은 하지 않는다."""

import json
from pathlib import Path

from streamlit.testing.v1 import AppTest

from src.interface.adapter import to_view_response

ROOT = Path(__file__).parent.parent.parent.parent
APP_PATH = ROOT / "app.py"
FIXTURES = ROOT / "tests" / "fixtures" / "interface"


def _load(name: str) -> dict:
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return {key: value for key, value in data.items() if not key.startswith("_")}


SAMPLES = _load("sample_responses.json")


def new_app() -> AppTest:
    return AppTest.from_file(str(APP_PATH), default_timeout=10)


def button(app: AppTest, label: str):
    return next(item for item in app.button if item.label == label)


def fixture_app(
    sample_name: str,
    question: str = "",
    district: str = "서대문구",
) -> AppTest:
    """예시 응답을 이미 받은 상태의 화면을 띄운다(질문 입력 없이 결과 화면부터)."""
    app = new_app()
    app.session_state["view"] = to_view_response(SAMPLES[sample_name], kind="fixture")
    app.session_state["asked_question"] = question
    app.session_state["asked_district"] = district
    return app.run()


def press_submit(app: AppTest) -> AppTest:
    """검색창의 제출 버튼을 누른다. 결과 화면에서는 '다시 묻기', 랜딩에서는 '물어보기'."""
    labels = [item.label for item in app.button]
    return (
        button(app, "다시 묻기" if "다시 묻기" in labels else "물어보기").click().run()
    )
