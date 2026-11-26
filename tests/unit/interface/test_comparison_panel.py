"""화면의 비교 패널 탭이 scores.csv 점수를 보여 주는지 확인한다. 외부 호출은 하지 않는다."""

import csv
from pathlib import Path

from streamlit.testing.v1 import AppTest

from src.evaluation.answer_metrics import FIELDS

APP_PATH = Path(__file__).parent.parent.parent.parent / "app.py"


def write_scores(path: Path, rows: list[tuple[str, str, str]]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, restval="")
        writer.writeheader()
        for variant, score, eligible in rows:
            writer.writerow(
                {"variant": variant, "score": score, "comparison_eligible": eligible}
            )
    return path


def open_app() -> AppTest:
    return AppTest.from_file(str(APP_PATH), default_timeout=10).run()


def test_without_a_scores_path_the_panel_explains_how_to_set_it(monkeypatch) -> None:
    monkeypatch.delenv("RAG_SCORES_CSV", raising=False)
    app = open_app()

    assert not app.exception
    assert any("RAG_SCORES_CSV" in info.value for info in app.info)
    assert not app.metric


def test_the_panel_shows_count_and_mean_per_variant(monkeypatch, tmp_path) -> None:
    path = write_scores(
        tmp_path / "scores.csv",
        [("A", "1.0", "true"), ("A", "0.5", "true"), ("B", "0.0", "true"),
         ("C", "0.9", "false")],
    )  # fmt: skip
    monkeypatch.setenv("RAG_SCORES_CSV", str(path))
    app = open_app()

    assert not app.exception
    assert [(m.label, m.value) for m in app.metric] == [
        ("방식 A", "2건 · 평균 0.750"),
        ("방식 B", "1건 · 평균 0.000"),  # 0점 한 건은 점수 없음과 다르다.
        ("방식 C", "0건 · 평균 —"),
    ]
    assert any("답변 근거 충실도" in s.value for s in app.subheader)
    assert any("Hit@k" in c.value for c in app.caption)  # 다른 지표와 섞지 않는다.


def test_an_unreadable_file_shows_a_safe_error(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("RAG_SCORES_CSV", str(tmp_path / "no-such" / "scores.csv"))
    app = open_app()

    assert not app.exception
    assert any("점수 파일을 읽지 못했습니다" in e.value for e in app.error)
    assert not any("no-such" in e.value for e in app.error)  # 경로 원문은 숨긴다.
