"""W5(조건 불일치)와 순위 이동 계산 테스트. 합성 값만 사용한다."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from src.interface.adapter import Candidate, Citation, ViewResponse
from src.validation import check_response, rank_shifts, stage_names, unchecked_rules

APP_PATH = Path(__file__).parent.parent.parent.parent / "app.py"


def dev_app() -> AppTest:
    """예전 사용자 화면의 위젯은 개발자 모드 미리보기 탭으로 옮겨졌다."""
    app = AppTest.from_file(str(APP_PATH), default_timeout=10)
    app.session_state["dev"] = True
    return app


def make_view(**changes) -> ViewResponse:
    base = dict(
        request_id="fx-req",
        kind="demo",
        status="answered",
        answer="[가상] 답변",
        required_fields=[],
        candidates=[
            Candidate(
                "c1", "서대문구", 0.8, "[가상] 본문 1", rank=1, conditions=["일반주택"]
            ),
            Candidate(
                "c2", "서대문구", 0.6, "[가상] 본문 2", rank=2, conditions=["공동주택"]
            ),
        ],
        model_inputs=["c1", "c2"],
        citations=[Citation("c1", None)],
        error=None,
        request_conditions={"housing_type": "일반주택"},
    )
    base.update(changes)
    return ViewResponse(**base)


def w5(view: ViewResponse) -> list[str]:
    return [a.message for a in check_response(view, "서대문구") if a.code == "W5"]


def test_w5_reports_chunks_whose_conditions_do_not_contain_the_input() -> None:
    messages = w5(make_view())
    assert len(messages) == 1
    assert "housing_type=일반주택" in messages[0]
    assert "c2" in messages[0]
    assert "c1" not in messages[0]


def test_w5_is_silent_when_every_chunk_matches() -> None:
    view = make_view(
        candidates=[
            Candidate(
                "c1",
                "서대문구",
                0.8,
                "[가상]",
                rank=1,
                conditions=["일반주택 (공동주택 제외)"],
            )
        ],
        model_inputs=["c1"],
    )
    assert w5(view) == []


def test_w5_ignores_chunks_not_given_to_the_model() -> None:
    # c2는 후보일 뿐 모델 입력이 아니다
    assert w5(make_view(model_inputs=["c1"])) == []


def test_w5_checks_all_candidates_when_model_input_is_unknown() -> None:
    assert len(w5(make_view(model_inputs=None))) == 1


def test_w5_needs_input_conditions() -> None:
    assert w5(make_view(request_conditions={})) == []
    assert w5(make_view(request_conditions={"housing_type": "  "})) == []


def test_w5_cannot_judge_chunks_without_conditions() -> None:
    view = make_view(
        candidates=[Candidate("c1", "서대문구", 0.8, "[가상]", rank=1)],
        model_inputs=["c1"],
    )
    assert w5(view) == []
    assert len(unchecked_rules(view)) == 1
    assert "W5" in unchecked_rules(view)[0]


def test_unchecked_rules_are_empty_when_conditions_were_compared() -> None:
    assert unchecked_rules(make_view()) == []
    assert unchecked_rules(make_view(request_conditions={})) == []


def staged(chunk_id: str, rank: int, **scores: float) -> Candidate:
    return Candidate(
        chunk_id, "서대문구", None, "[가상]", rank=rank, stage_scores=scores
    )


def test_stage_names_keep_first_seen_order() -> None:
    candidates = [
        staged("a", 1, vector=0.5, rerank=0.9),
        staged("b", 2, vector=0.7, bm25=1.0),
    ]
    assert stage_names(candidates) == ["vector", "rerank", "bm25"]
    assert stage_names([]) == []


def test_rank_shift_is_positive_when_a_chunk_moved_up() -> None:
    # vector만으로는 b가 1등, 최종은 a가 1등
    candidates = [
        staged("a", 1, vector=0.4),
        staged("b", 2, vector=0.9),
        staged("c", 3, vector=0.1),
    ]
    assert rank_shifts(candidates, "vector") == {"a": 1, "b": -1, "c": 0}


def test_rank_shift_is_zero_when_order_is_unchanged() -> None:
    candidates = [staged("a", 1, vector=0.9), staged("b", 2, vector=0.5)]
    assert rank_shifts(candidates, "vector") == {"a": 0, "b": 0}


def test_rank_shift_skips_candidates_without_that_stage() -> None:
    candidates = [
        staged("a", 1, vector=0.4),
        staged("b", 2),
        staged("c", 3, vector=0.9),
    ]
    assert rank_shifts(candidates, "vector") == {"a": 1, "c": -1}


def open_panel(view: ViewResponse) -> AppTest:
    app = dev_app()
    app.session_state["view"] = view
    app.session_state["asked_district"] = "서대문구"
    app.session_state["asked_mode"] = "예시 응답"  # 앱의 기본 응답 방식
    return app.run()


def test_panel_shows_w5_and_rank_shift_column() -> None:
    view = make_view(
        candidates=[
            Candidate(
                "c1",
                "서대문구",
                0.8,
                "[가상]",
                rank=1,
                conditions=["일반주택"],
                stage_scores={"vector": 0.4, "rerank": 0.9},
            ),
            Candidate(
                "c2",
                "서대문구",
                0.6,
                "[가상]",
                rank=2,
                conditions=["공동주택"],
                stage_scores={"vector": 0.9, "rerank": 0.5},
            ),
        ],
    )
    app = open_panel(view)
    assert not app.exception
    assert any("[W5]" in w.value for w in app.warning)
    table = app.dataframe[0].value
    assert list(table["순위 이동"]) == ["+1", "-1"]


def test_panel_says_rank_shift_cannot_be_computed_with_one_stage() -> None:
    app = open_panel(make_view())
    assert not app.exception
    assert any("순위 이동을 계산할 수 없습니다" in c.value for c in app.caption)
    assert list(app.dataframe[0].value["순위 이동"]) == ["-", "-"]


def test_panel_reports_rules_it_could_not_check() -> None:
    view = make_view(
        candidates=[Candidate("c1", "서대문구", 0.8, "[가상]", rank=1)],
        model_inputs=["c1"],
    )
    app = open_panel(view)
    assert not app.exception
    assert any("검사하지 못한 규칙" in i.value and "W5" in i.value for i in app.info)


def test_w5_requires_every_condition_to_match() -> None:
    view = make_view(
        candidates=[
            Candidate("c1", "서대문구", 0.8, "[가상]", rank=1, conditions=["일반주택"])
        ],
        model_inputs=["c1"],
        request_conditions={"housing_type": "공동주택", "item": "일반주택"},
    )
    assert len(w5(view)) == 1
    ok = make_view(
        candidates=[
            Candidate(
                "c1", "서대문구", 0.8, "[가상]", rank=1, conditions=["일반주택", "병"]
            )
        ],
        model_inputs=["c1"],
        request_conditions={"housing_type": "일반주택", "item": "병"},
    )
    assert w5(ok) == []


def test_unchecked_when_any_used_candidate_lacks_conditions() -> None:
    view = make_view(
        candidates=[
            Candidate("c1", "서대문구", 0.8, "[가상]", rank=1, conditions=["일반주택"]),
            Candidate("c2", "서대문구", 0.6, "[가상]", rank=2),
        ],
        model_inputs=["c1", "c2"],
    )
    assert "W5" in unchecked_rules(view)[0]


def test_panel_does_not_say_no_alert_when_a_rule_was_unchecked() -> None:
    def page() -> None:
        from src.interface.adapter import Candidate, Citation, ViewResponse
        from src.interface.inspection import render_inspection

        view = ViewResponse(
            "r",
            "demo",
            "answered",
            "[가상]",
            [],
            [Candidate("c1", "서대문구", 0.8, "[가상]", rank=1)],
            ["c1"],
            [Citation("c1", None)],
            None,
            request_conditions={"item": "병"},
        )
        render_inspection(view, "서대문구")

    app = AppTest.from_function(page, default_timeout=10).run()
    assert not app.success
    assert any("검사하지 못한 규칙" in i.value for i in app.info)


def test_panel_computes_rank_shift_with_a_single_stage_score() -> None:
    view = make_view(
        candidates=[
            Candidate(
                "c1", "서대문구", 0.8, "[가상]", rank=1, stage_scores={"vector": 0.4}
            ),
            Candidate(
                "c2", "서대문구", 0.6, "[가상]", rank=2, stage_scores={"vector": 0.9}
            ),
        ],
    )
    app = open_panel(view)
    assert not app.exception
    assert list(app.dataframe[0].value["순위 이동"]) == ["+1", "-1"]
    # 단계가 하나라 고르는 칸이 없다
    assert not any(b.label == "순위 이동 비교" for b in app.selectbox)
