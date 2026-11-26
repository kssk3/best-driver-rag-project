"""검증 패널 화면 테스트. 합성 예시 응답을 세션에 넣어 그린다."""

import json
from pathlib import Path

from streamlit.testing.v1 import AppTest

from src.interface.adapter import to_view_response

APP_PATH = Path(__file__).parent.parent.parent.parent / "app.py"


SAMPLES = json.loads(
    (APP_PATH.parent / "tests/fixtures/interface/sample_responses.json").read_text(
        encoding="utf-8"
    )
)


def ask(sample_name: str, district: str = "서대문구") -> AppTest:
    app = AppTest.from_file(str(APP_PATH), default_timeout=10)
    app.session_state["view"] = to_view_response(SAMPLES[sample_name], kind="fixture")
    app.session_state["asked_district"] = district
    app.session_state["asked_mode"] = "합성 데모"
    return app.run()


def test_panel_asks_for_question_first() -> None:
    app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
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
