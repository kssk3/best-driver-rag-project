import csv

import pytest

from scripts import score_relevancy

COLUMNS = [
    "run_id",
    "case_id",
    "configuration",
    "rewrite_enabled",
    "status",
    "answer",
    "original_question",
]


def write_runs(folder, rows, columns=COLUMNS):
    """rows는 {열: 값} 목록. 없는 열은 빈 문자열로 채운다."""
    with (folder / "runs.csv").open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(columns)
        for row in rows:
            writer.writerow([row.get(c, "") for c in columns])


def answered(run_id="r1"):
    return {
        "run_id": run_id,
        "case_id": "c1",
        "configuration": "A",
        "status": "answered",
        "answer": "답",
    }


class Spy:
    def __init__(self, result=None, error=None):
        self.calls, self.result, self.error = [], result, error

    async def __call__(self, rows):
        self.calls.append(rows)
        if self.error:
            raise self.error
        return self.result(rows) if self.result else []


def echo(rows):
    return [{"run_id": r["run_id"], "error": ""} for r in rows]


def test_existing_relevancy_csv_is_never_overwritten_and_run_id_is_kept(
    tmp_path, monkeypatch
) -> None:
    write_runs(tmp_path, [answered()])
    (tmp_path / "relevancy.csv").write_text("원본", encoding="utf-8")
    spy = Spy(echo)
    monkeypatch.setattr(score_relevancy, "_score", spy)
    with pytest.raises(SystemExit):
        score_relevancy.main([str(tmp_path)])
    assert spy.calls == []
    assert (tmp_path / "relevancy.csv").read_text(encoding="utf-8") == "원본"
    out = tmp_path / "new.csv"
    score_relevancy.main([str(tmp_path), "--output", str(out)])
    assert "r1" in out.read_text(encoding="utf-8")


def test_output_is_reserved_before_paid_scoring_and_cleaned_up_on_failure(
    tmp_path, monkeypatch
) -> None:
    write_runs(tmp_path, [answered()])
    spy = Spy(error=RuntimeError("호출 실패"))
    monkeypatch.setattr(score_relevancy, "_score", spy)
    with pytest.raises(FileNotFoundError):  # 없는 폴더는 호출 전에 실패한다
        score_relevancy.main([str(tmp_path), "--output", str(tmp_path / "x" / "o.csv")])
    assert spy.calls == []
    out = tmp_path / "o.csv"
    with pytest.raises(RuntimeError):
        score_relevancy.main([str(tmp_path), "--output", str(out)])
    assert not out.exists()  # 실패한 실행이 빈 파일을 남기지 않는다


def test_score_row_has_a_utc_timestamp_only_when_scored() -> None:
    assert "timestamp" in score_relevancy.FIELDS


def test_clarification_responses_are_scored_not_marked_absent() -> None:
    assert "needs_clarification" in score_relevancy.SCORED_STATUSES


def test_scores_outside_zero_to_one_are_errors_not_successes() -> None:
    assert score_relevancy.checked_score(0.5) == ("0.5000", "")
    for bad in (-0.03, 1.2, float("nan")):
        assert score_relevancy.checked_score(bad) == ("", "score_out_of_range")
    assert "variant" in score_relevancy.FIELDS


def test_duplicate_run_ids_stop_before_paid_scoring(tmp_path, monkeypatch) -> None:
    write_runs(tmp_path, [answered("r1"), answered("r1")])
    spy = Spy(echo)
    monkeypatch.setattr(score_relevancy, "_score", spy)
    with pytest.raises(SystemExit):
        score_relevancy.main([str(tmp_path), "--output", str(tmp_path / "o.csv")])
    assert spy.calls == [] and not (tmp_path / "o.csv").exists()


def test_blank_run_ids_of_recordless_failures_are_allowed(
    tmp_path, monkeypatch
) -> None:
    failure = {"case_id": "c1", "configuration": "A", "status": "error"}
    write_runs(tmp_path, [failure, failure, answered()])
    monkeypatch.setattr(score_relevancy, "_score", Spy(echo))
    score_relevancy.main([str(tmp_path), "--output", str(tmp_path / "o.csv")])
    assert (tmp_path / "o.csv").exists()


def test_scoreable_row_without_a_run_id_stops_before_paid_scoring(
    tmp_path, monkeypatch
) -> None:
    write_runs(tmp_path, [answered("")])
    spy = Spy(echo)
    monkeypatch.setattr(score_relevancy, "_score", spy)
    with pytest.raises(SystemExit):
        score_relevancy.main([str(tmp_path), "--output", str(tmp_path / "o.csv")])
    assert spy.calls == []


def test_partial_output_is_removed_when_csv_writing_fails(
    tmp_path, monkeypatch
) -> None:
    write_runs(tmp_path, [answered()])
    # 열 이름이 FIELDS와 달라 쓰기에 실패한다
    monkeypatch.setattr(
        score_relevancy,
        "_score",
        Spy(lambda rows: [{"run_id": "r1", "bad_column": "x"}]),
    )
    out = tmp_path / "o.csv"
    with pytest.raises(ValueError):
        score_relevancy.main([str(tmp_path), "--output", str(out)])
    assert not out.exists()


def test_missing_required_columns_stop_before_paid_scoring(
    tmp_path, monkeypatch
) -> None:
    write_runs(
        tmp_path, [answered()], columns=["run_id", "case_id", "status", "answer"]
    )
    spy = Spy(echo)
    monkeypatch.setattr(score_relevancy, "_score", spy)
    with pytest.raises(SystemExit) as stop:
        score_relevancy.main([str(tmp_path), "--output", str(tmp_path / "o.csv")])
    assert "original_question" in str(stop.value)
    assert spy.calls == [] and not (tmp_path / "o.csv").exists()


def test_legacy_archive_with_variant_but_no_configuration_is_accepted(
    tmp_path, monkeypatch
) -> None:
    columns = [c for c in COLUMNS if c != "configuration"] + ["variant"]
    row = {**answered(), "variant": "A"}
    write_runs(tmp_path, [row], columns=columns)
    monkeypatch.setattr(score_relevancy, "_score", Spy(echo))
    score_relevancy.main([str(tmp_path), "--output", str(tmp_path / "o.csv")])
    assert score_relevancy.label({"variant": "A"}) == "A"
    assert score_relevancy.missing_columns([{c: "" for c in columns}]) == []
