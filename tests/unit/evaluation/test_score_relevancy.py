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
