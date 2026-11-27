import csv

import pytest

from scripts import score_relevancy


def test_existing_relevancy_csv_is_never_overwritten_and_run_id_is_kept(
    tmp_path, monkeypatch
) -> None:
    with (tmp_path / "runs.csv").open("w", encoding="utf-8", newline="") as file:
        csv.writer(file).writerows([["run_id"], ["r1"]])
    (tmp_path / "relevancy.csv").write_text("원본", encoding="utf-8")
    called = []

    async def fake(rows):
        called.append(rows)
        return [{"run_id": r["run_id"], "error": ""} for r in rows]

    monkeypatch.setattr(score_relevancy, "_score", fake)
    with pytest.raises(SystemExit):
        score_relevancy.main([str(tmp_path)])
    assert (
        called == []
        and (tmp_path / "relevancy.csv").read_text(encoding="utf-8") == "원본"
    )
    out = tmp_path / "new.csv"
    score_relevancy.main([str(tmp_path), "--output", str(out)])
    assert "r1" in out.read_text(encoding="utf-8")


def test_output_is_reserved_before_paid_scoring_and_cleaned_up_on_failure(
    tmp_path, monkeypatch
) -> None:
    with (tmp_path / "runs.csv").open("w", encoding="utf-8", newline="") as file:
        csv.writer(file).writerows([["run_id"], ["r1"]])
    called = []

    async def boom(rows):
        called.append(rows)
        raise RuntimeError("호출 실패")

    monkeypatch.setattr(score_relevancy, "_score", boom)
    with pytest.raises(FileNotFoundError):  # 없는 폴더는 호출 전에 실패한다
        score_relevancy.main([str(tmp_path), "--output", str(tmp_path / "x" / "o.csv")])
    assert called == []
    out = tmp_path / "o.csv"
    with pytest.raises(RuntimeError):
        score_relevancy.main([str(tmp_path), "--output", str(out)])
    assert not out.exists()  # 실패한 실행이 빈 파일을 남기지 않는다


def test_score_row_has_a_utc_timestamp_only_when_scored() -> None:
    assert "timestamp" in score_relevancy.FIELDS


def test_clarification_responses_are_scored_not_marked_absent() -> None:
    assert "needs_clarification" in score_relevancy.SCORED_STATUSES
