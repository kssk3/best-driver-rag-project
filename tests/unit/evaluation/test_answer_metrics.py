import asyncio
import csv
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from scripts.score_answers import main
from src.evaluation.answer_metrics import score_archive

SNAPSHOT = "2026-11-25T064832Z"
ARCHIVE = Path("results/team-a") / SNAPSHOT / "evaluation.json"
CASES = Path("eval/snapshots") / SNAPSHOT / "cases.csv"


def rows(output):
    with (output / "scores.csv").open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def test_archive_inputs_and_zero_nan(tmp_path):
    attempts = json.loads(ARCHIVE.read_text())
    score = AsyncMock(
        side_effect=[SimpleNamespace(value=0.0), SimpleNamespace(value=float("nan"))]
    )
    output = tmp_path / "eval"
    assert not asyncio.run(
        score_archive(ARCHIVE, CASES, output, scorer=score, judge_model="fake")
    )
    first, second = rows(output)
    assert [(r["status"], r["score"], r["reason"]) for r in (first, second)] == [
        ("scored", "0.0", ""),
        ("no_score", "", "non_finite_value"),
    ]
    assert first["evaluation_id"] == second["evaluation_id"]
    for call, attempt, row, count in zip(
        score.await_args_list, attempts, (first, second), (4, 5), strict=True
    ):
        record = attempt["record"]
        chunks = {
            c["chunk"]["chunk_id"]: c["chunk"]["content"] for c in record["candidates"]
        }
        contexts = [chunks[key] for key in record["model_input_chunk_ids"]]
        assert len(contexts) == count
        assert call.kwargs == dict(
            user_input=record["request"]["question"],
            response=record["response"]["answer"],
            retrieved_contexts=contexts,
        )
        assert (row["run_id"], row["dataset_id"], row["case_id"]) == (
            attempt["run_id"],
            SNAPSHOT,
            attempt["case_id"],
        )
        assert row["run_kind"] == "rag" and row["judge_model"] == "fake"
        assert json.loads(row["versions_json"]) == record["options"]["versions"]
        assert (
            float(row["duration_ms"]) >= 0
            and datetime.fromisoformat(row["scored_at_utc"]).tzinfo
        )


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("district", "송파구", "snapshot_district_mismatch"),
        ("dong", "연희동", "snapshot_dong_mismatch"),
        (
            "conditions_json",
            '{"housing_type":"단독주택","container_type":"일반용기"}',
            "snapshot_conditions_mismatch",
        ),
        ("conditions_json", "{", "invalid_snapshot_conditions"),
        (
            "conditions_json",
            '{"container_type": "일반용기", "housing_type": "공동주택"}',
            "",
        ),
    ],
)
def test_snapshot_request_checked_before_scoring(tmp_path, field, value, reason):
    with CASES.open(newline="", encoding="utf-8") as stream:
        cases = list(csv.DictReader(stream))
    cases[0][field] = value
    snapshot = tmp_path / "cases.csv"
    with snapshot.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=cases[0].keys())
        writer.writeheader()
        writer.writerows(cases)

    scorer = AsyncMock(return_value=SimpleNamespace(value=0.5))
    output = tmp_path / "evaluation"
    ok = asyncio.run(score_archive(ARCHIVE, snapshot, output, scorer=scorer))
    first, second = rows(output)
    if reason:
        assert not ok
        assert (first["status"], first["reason"], first["score"]) == (
            "input_error",
            reason,
            "",
        )
        assert [call.kwargs["user_input"] for call in scorer.await_args_list] == [
            cases[1]["question"]
        ]
    else:
        assert ok and scorer.await_count == 2
        assert (first["status"], first["score"]) == ("scored", "0.5")
    assert (second["status"], second["score"]) == ("scored", "0.5")


def test_archive_failures_are_independent(tmp_path):
    attempts = json.loads(ARCHIVE.read_text())
    record = attempts[0]["record"]
    ids = record["model_input_chunk_ids"]
    record["model_input_chunk_ids"] = [ids[2], ids[0], ids[2]]
    bad_id, absent_ids, skipped = [
        json.loads(json.dumps(attempts[0])) for _ in range(3)
    ]
    bad_id["record"]["model_input_chunk_ids"].append("not-in-candidates")
    del absent_ids["record"]["model_input_chunk_ids"]
    skipped["status"] = skipped["record"]["response"]["status"] = "error"
    no_record = dict(
        attempts[0], record=None, run_id=None, response=None, status="error"
    )
    path = tmp_path / "evaluation.json"
    path.write_text(json.dumps([bad_id, absent_ids, no_record, skipped, *attempts]))
    score = AsyncMock(side_effect=[RuntimeError("private"), SimpleNamespace()])
    output = tmp_path / "eval"
    assert not asyncio.run(score_archive(path, CASES, output, scorer=score))
    result = rows(output)
    assert [(r["status"], r["reason"]) for r in result] == [
        ("input_error", "unresolved_chunk_id"),
        ("input_error", "missing_model_input_chunk_ids"),
        ("skipped", "no_run_record"),
        ("skipped", "response_error"),
        ("scorer_error", "judge_failed"),
        ("no_score", "missing_value"),
    ]
    assert result[2]["run_id"] == "" and result[2]["attempt_index"] == "3"
    assert all(r["score"] == "" for r in result)
    original = [c["chunk"]["content"] for c in record["candidates"]]
    assert score.await_args_list[0].kwargs["retrieved_contexts"] == [
        original[2],
        original[0],
        original[2],
    ]


@pytest.mark.parametrize(
    "missing",
    ["question", "case_id", "dataset_id", "district", "dong", "conditions_json"],
)
def test_missing_case_header_fails_before_creating_output(tmp_path, capsys, missing):
    with CASES.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = [field for field in reader.fieldnames if field != missing]
        cases = list(reader)
    snapshot = tmp_path / "cases.csv"
    with snapshot.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(cases)

    output = tmp_path / "scored"
    with pytest.raises(SystemExit) as error:
        main(
            [
                "--evaluation",
                str(ARCHIVE),
                "--cases-csv",
                str(snapshot),
                "--output-dir",
                str(output),
            ]
        )
    assert error.value.code == 2
    assert f"cases.csv 필수 열 누락: {missing}" in capsys.readouterr().err
    assert not output.exists()


def test_validate_cli_creates_new_table(tmp_path):
    out = tmp_path / "check"
    args = [
        "--evaluation",
        str(ARCHIVE),
        "--cases-csv",
        str(CASES),
        "--output-dir",
        str(out),
    ]
    main(args)
    assert [r["reason"] for r in rows(out)] == ["validate_only"] * 2
    with pytest.raises(SystemExit):
        main(args)
    assert len(rows(out)) == 2


def test_judge_cli_with_installed_ragas(tmp_path, monkeypatch):
    monkeypatch.setenv("RAGAS_DO_NOT_TRACK", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test")
    from ragas.llms.base import InstructorLLM

    calls = []

    async def generate(self, prompt, response_model):
        calls.append(response_model.__name__)
        if len(calls) == 1:
            return response_model(statements=["test"])
        return response_model(
            statements=[dict(statement="test", reason="offline", verdict=0)]
        )

    monkeypatch.setattr(InstructorLLM, "agenerate", generate)
    out = tmp_path / "scored"
    main(
        [
            "--evaluation",
            str(ARCHIVE),
            "--cases-csv",
            str(CASES),
            "--output-dir",
            str(out),
            "--case-id",
            "p04-colors-trick",
            "--judge-model",
            "gpt-4o-mini",
        ]
    )
    assert calls == ["StatementGeneratorOutput", "NLIStatementOutput"]
    assert rows(out)[0]["score"] == "0.0"
