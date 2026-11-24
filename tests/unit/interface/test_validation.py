"""자동 경고(W1~W9) 단위 테스트. 화면 없이 응답만 만들어 검사한다."""

from src.interface.adapter import Candidate, Citation, ViewResponse
from src.validation import check_response


def make_view(**changes) -> ViewResponse:
    base = dict(
        request_id="fx-req",
        kind="fixture",
        status="answered",
        answer="[가상] 답변",
        required_fields=[],
        candidates=[
            Candidate("c1", "서대문구", 0.8, "[가상] 본문 1"),
            Candidate("c2", "송파구", 0.6, "[가상] 본문 2"),
        ],
        model_inputs=["c1"],
        citations=[Citation("c1", None)],
        error=None,
    )
    base.update(changes)
    return ViewResponse(**base)


def codes(view: ViewResponse, district: str | None = None) -> list[str]:
    return [alert.code for alert in check_response(view, district)]


def test_clean_response_has_no_alerts() -> None:
    assert codes(make_view(), "서대문구") == []


def test_w1_other_district_used_in_model_input() -> None:
    assert codes(make_view(), "송파구") == ["W1"]


def test_w1_ignores_candidates_not_used_by_model() -> None:
    # c2(송파구)는 후보일 뿐 모델 입력이 아니다
    assert "W1" not in codes(make_view(), "서대문구")


def test_w1_checks_all_candidates_when_model_input_is_unknown() -> None:
    assert codes(make_view(model_inputs=None), "서대문구") == ["W1"]


def test_w1_skipped_without_selected_district() -> None:
    assert codes(make_view(), None) == []


def test_w1_skips_unknown_district() -> None:
    view = make_view(candidates=[Candidate("c1", None, 0.8, "")])
    assert codes(view, "송파구") == []


def test_w2_citation_not_in_candidates_or_inputs() -> None:
    assert codes(make_view(citations=[Citation("zz", None)])) == ["W2"]


def test_w3_answered_without_citations() -> None:
    assert codes(make_view(citations=[])) == ["W3"]


def test_w3_not_checked_for_refusal() -> None:
    assert codes(make_view(status="insufficient_evidence", citations=[])) == []


def test_w4_answered_without_candidates() -> None:
    view = make_view(candidates=[], model_inputs=None, citations=[])
    assert codes(view) == ["W3", "W4"]


def test_w6_clarification_without_fields() -> None:
    view = make_view(status="needs_clarification", answer=None, citations=[])
    assert codes(view) == ["W6"]


def test_w6_clarification_with_fields_is_fine() -> None:
    view = make_view(
        status="needs_clarification", answer=None, citations=[], required_fields=["item"]
    )
    assert codes(view) == []


def test_w7_error_is_reported_with_error_level() -> None:
    view = make_view(status="error", answer=None, citations=[], error="[가상] 검색 실패")
    alerts = check_response(view)
    assert [a.code for a in alerts] == ["W7"]
    assert alerts[0].level == "error"
    assert "[가상] 검색 실패" in alerts[0].message


def test_w7_error_without_text_says_so() -> None:
    view = make_view(status="error", answer=None, citations=[], error=None)
    assert "오류 내용 없음" in check_response(view)[0].message


def test_w8_model_input_more_than_visible_candidates() -> None:
    view = make_view(
        candidates=[Candidate("c1", None, 0.8, "")],
        model_inputs=["c1", "c2"],
        citations=[],
        status="insufficient_evidence",
    )
    assert codes(view) == ["W8"]


def test_w8_not_checked_when_model_input_is_unknown() -> None:
    assert "W8" not in codes(make_view(model_inputs=None, candidates=[]))


def test_w9_error_text_with_non_error_status() -> None:
    view = make_view(status="insufficient_evidence", citations=[], error="[가상] 내부 오류")
    alerts = check_response(view)
    assert [a.code for a in alerts] == ["W9"]
    assert alerts[0].level == "error"
