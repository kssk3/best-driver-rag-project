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
    (tmp_path / "runs.csv").write_bytes(ARCHIVE.with_name("runs.csv").read_bytes())
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


def test_dataset_identity_uses_original_run_table(tmp_path):
    from src.evaluation.csv_export import write_evaluation_csv
    from src.evaluation.runner import load_evaluation_cases

    cases = load_evaluation_cases(CASES.with_suffix(".json"))
    source = tmp_path / "archive"
    source.mkdir()
    archive = source / "evaluation.json"
    archive.write_bytes(ARCHIVE.read_bytes())
    write_evaluation_csv(source, cases, json.loads(archive.read_text()))
    other = tmp_path / "other"
    other.mkdir()
    changed = cases[0].model_copy(update={"reference_answer": "다른 채점 기준"})
    write_evaluation_csv(other, [changed, *cases[1:]], [])
    scorer = AsyncMock(return_value=SimpleNamespace(value=0.0))
    output = tmp_path / "eval"
    with pytest.raises(ValueError, match="dataset_id"):
        asyncio.run(score_archive(archive, other / "cases.csv", output, scorer=scorer))
    assert not output.exists()
    scorer.assert_not_awaited()
    assert asyncio.run(
        score_archive(archive, source / "cases.csv", output, scorer=scorer)
    )
    assert [r["score"] for r in rows(output)] == ["0.0", "0.0"]


def test_missing_run_table_fails_before_scoring(tmp_path):
    archive = tmp_path / "evaluation.json"
    archive.write_bytes(ARCHIVE.read_bytes())
    scorer = AsyncMock()
    output = tmp_path / "eval"
    with pytest.raises(FileNotFoundError, match="runs.csv"):
        asyncio.run(score_archive(archive, CASES, output, scorer=scorer))
    assert not output.exists()
    scorer.assert_not_awaited()


@pytest.mark.parametrize("missing", ["dataset_id", "case_id", "run_id"])
def test_missing_run_header_rejects_archive(tmp_path, missing):
    archive = tmp_path / "evaluation.json"
    archive.write_bytes(ARCHIVE.read_bytes())
    with ARCHIVE.with_name("runs.csv").open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        fields = [field for field in reader.fieldnames if field != missing]
        runs = list(reader)
    with archive.with_name("runs.csv").open(
        "w", newline="", encoding="utf-8"
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(runs)
    scorer = AsyncMock()
    output = tmp_path / "scored"
    with pytest.raises(ValueError, match=f"runs.csv 필수 열 누락: {missing}"):
        asyncio.run(score_archive(archive, CASES, output, scorer=scorer))
    scorer.assert_not_awaited()
    assert not output.exists()


def test_duplicate_run_id_cannot_bind_two_cases(tmp_path):
    archive = tmp_path / "evaluation.json"
    archive.write_bytes(ARCHIVE.read_bytes())
    with ARCHIVE.with_name("runs.csv").open(newline="", encoding="utf-8") as stream:
        first, second = csv.DictReader(stream)
    second["run_id"] = first["run_id"]
    with archive.with_name("runs.csv").open(
        "w", newline="", encoding="utf-8"
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=first.keys())
        writer.writeheader()
        writer.writerows([first, second])
    scorer = AsyncMock()
    output = tmp_path / "scored"
    with pytest.raises(ValueError, match="중복 run_id"):
        asyncio.run(score_archive(archive, CASES, output, scorer=scorer))
    scorer.assert_not_awaited()
    assert not output.exists()


@pytest.mark.parametrize(
    ("outcome", "first_valid"),
    [
        ("validate", ("skipped", "validate_only")),
        ("score", ("scored", "")),
        ("judge_error", ("scorer_error", "judge_failed")),
    ],
)
def test_only_first_valid_attempt_with_same_run_id_is_processed(
    tmp_path, outcome, first_valid
):
    first, _ = json.loads(ARCHIVE.read_text())
    no_record = dict(first, record=None, status="error")
    invalid = dict(
        first, record=dict(first["record"], model_input_chunk_ids=["absent"])
    )
    skipped_response = dict(first["record"]["response"], status="error")
    skipped = dict(
        first, record=dict(first["record"], response=skipped_response), status="error"
    )
    archive = tmp_path / "evaluation.json"
    archive.write_text(json.dumps([no_record, invalid, skipped, first, first]))
    archive.with_name("runs.csv").write_bytes(
        ARCHIVE.with_name("runs.csv").read_bytes()
    )
    scorer = (
        None
        if outcome == "validate"
        else AsyncMock(return_value=SimpleNamespace(value=1))
    )
    if outcome == "judge_error":
        scorer.side_effect = RuntimeError("offline judge error")
    output = tmp_path / "scored"
    assert not asyncio.run(score_archive(archive, CASES, output, scorer=scorer))
    result = rows(output)
    assert [(r["status"], r["reason"]) for r in result] == [
        ("skipped", "no_run_record"),
        ("input_error", "unresolved_chunk_id"),
        ("skipped", "response_error"),
        first_valid,
        ("input_error", "duplicate_run_id"),
    ]
    assert result[-1]["score"] == ""
    if scorer is not None:
        scorer.assert_awaited_once()


def test_long_exported_csv_fields_are_preserved_and_parser_limit_restored(tmp_path):
    from src.evaluation.csv_export import write_evaluation_csv
    from src.evaluation.runner import load_evaluation_cases

    original_limit = csv.field_size_limit()
    long_text = '큰 필드에 들어가는 "따옴표", 쉼표와 줄바꿈\n' * 8000
    assert len(long_text) > 131072
    cases = load_evaluation_cases(CASES.with_suffix(".json"))
    cases[0] = cases[0].model_copy(update={"reference_answer": long_text})
    attempts = json.loads(ARCHIVE.read_text())
    attempts[0]["record"]["response"]["answer"] = long_text
    archive = tmp_path / "evaluation.json"
    archive.write_text(json.dumps(attempts), encoding="utf-8")
    write_evaluation_csv(tmp_path, cases, attempts)

    async def judge(**sample):
        assert csv.field_size_limit() == original_limit
        return SimpleNamespace(value=1)

    scorer = AsyncMock(side_effect=judge)
    output = tmp_path / "scored"
    assert asyncio.run(
        score_archive(archive, tmp_path / "cases.csv", output, scorer=scorer)
    )
    assert [r["score"] for r in rows(output)] == ["1.0", "1.0"]
    assert scorer.await_args_list[0].kwargs["response"] == long_text
    with pytest.raises(ValueError, match="dataset_id"):
        asyncio.run(score_archive(archive, CASES, tmp_path / "invalid", scorer=scorer))
    assert csv.field_size_limit() == original_limit
    assert scorer.await_count == 2


def test_exported_blank_run_ids_preserve_each_missing_attempt(tmp_path):
    from src.evaluation.csv_export import write_evaluation_csv
    from src.evaluation.runner import load_evaluation_cases

    cases = load_evaluation_cases(CASES.with_suffix(".json"))
    first, second = json.loads(ARCHIVE.read_text())
    attempts = [
        dict(a, record=None, run_id=None, response=None, status="error")
        for a in (first, second)
    ] + [second]
    archive = tmp_path / "evaluation.json"
    archive.write_text(json.dumps(attempts), encoding="utf-8")
    write_evaluation_csv(tmp_path, cases, attempts)
    with archive.with_name("runs.csv").open(newline="", encoding="utf-8") as stream:
        assert [r["run_id"] for r in csv.DictReader(stream)] == [
            "",
            "",
            second["run_id"],
        ]
    output = tmp_path / "scored"
    scorer = AsyncMock(return_value=SimpleNamespace(value=1))
    assert not asyncio.run(
        score_archive(archive, tmp_path / "cases.csv", output, scorer=scorer)
    )
    assert [
        (r["attempt_index"], r["case_id"], r["reason"], r["score"])
        for r in rows(output)
    ] == [
        ("1", first["case_id"], "no_run_record", ""),
        ("2", second["case_id"], "no_run_record", ""),
        ("3", second["case_id"], "", "1.0"),
    ]
    scorer.assert_awaited_once()


@pytest.mark.parametrize("reason", ["ambiguous_chunk_id", "empty_context"])
def test_invalid_selected_context_prevents_judge_call(tmp_path, reason):
    first, second = json.loads(ARCHIVE.read_text())
    record = first["record"]
    selected_id = record["model_input_chunk_ids"][0]
    candidate = next(
        c for c in record["candidates"] if c["chunk"]["chunk_id"] == selected_id
    )
    if reason == "ambiguous_chunk_id":
        revised = dict(
            candidate["chunk"], content="같은 식별자에 연결된 서로 다른 본문"
        )
        record["candidates"].append(dict(candidate, chunk=revised))
    else:
        candidate["chunk"]["content"] = "   "
    archive = tmp_path / "evaluation.json"
    archive.write_text(json.dumps([first, second]), encoding="utf-8")
    archive.with_name("runs.csv").write_bytes(
        ARCHIVE.with_name("runs.csv").read_bytes()
    )
    scorer = AsyncMock(return_value=SimpleNamespace(value=0.25))
    output = tmp_path / "scored"
    assert not asyncio.run(score_archive(archive, CASES, output, scorer=scorer))
    assert [(r["status"], r["score"], r["reason"]) for r in rows(output)] == [
        ("input_error", "", reason),
        ("scored", "0.25", ""),
    ]
    scorer.assert_awaited_once()
    assert (
        scorer.await_args.kwargs["user_input"]
        == second["record"]["request"]["question"]
    )


@pytest.mark.parametrize(
    ("value", "reason"),
    [(False, "invalid_value"), (-0.01, "out_of_range"), (1.01, "out_of_range")],
)
def test_invalid_judge_value_has_reason_and_no_score(tmp_path, value, reason):
    output = tmp_path / "scored"
    scorer = AsyncMock(
        side_effect=[SimpleNamespace(value=value), SimpleNamespace(value=1.0)]
    )
    assert not asyncio.run(score_archive(ARCHIVE, CASES, output, scorer=scorer))
    assert [(r["status"], r["score"], r["reason"]) for r in rows(output)] == [
        ("no_score", "", reason),
        ("scored", "1.0", ""),
    ]
    assert scorer.await_count == 2


def test_malformed_attempts_and_run_case_mismatch_do_not_drop_valid_rows(tmp_path):
    attempts = json.loads(ARCHIVE.read_text())
    attempts[0]["case_id"] = attempts[1]["case_id"]
    archive = tmp_path / "evaluation.json"
    archive.write_text(json.dumps([None, {"case_id": []}, *attempts]))
    (tmp_path / "runs.csv").write_bytes(ARCHIVE.with_name("runs.csv").read_bytes())
    scorer = AsyncMock(return_value=SimpleNamespace(value=1.0))
    output = tmp_path / "out"
    assert not asyncio.run(score_archive(archive, CASES, output, scorer=scorer))
    result = rows(output)
    assert [row["attempt_index"] for row in result] == ["1", "2", "3", "4"]
    assert [(row["status"], row["reason"]) for row in result] == [
        ("input_error", "invalid_attempt"),
        ("input_error", "invalid_case_id"),
        ("input_error", "run_case_mismatch"),
        ("scored", ""),
    ]
    assert result[1]["case_id"] == "" and result[3]["score"] == "1.0"
    scorer.assert_awaited_once()


@pytest.mark.parametrize(
    "run_stamp", ["explicit", "", "2026-11-25T06:48:32", "2026-11-25T06:48:32+09:00"]
)
def test_naive_run_start_needs_explicit_utc_in_matched_run(tmp_path, run_stamp):
    attempts = json.loads(ARCHIVE.read_text())
    # Legacy timestamps may use local wall time; never assign them a timezone by guess.
    attempts[0]["record"]["started_at"] = "2026-11-25T15:48:32.431436"
    archive = tmp_path / "evaluation.json"
    archive.write_text(json.dumps(attempts))
    with ARCHIVE.with_name("runs.csv").open(encoding="utf-8", newline="") as stream:
        runs = list(csv.DictReader(stream))
    original_stamp = runs[0]["started_at_utc"]
    if run_stamp != "explicit":
        runs[0]["started_at_utc"] = run_stamp
    with (tmp_path / "runs.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=runs[0].keys())
        writer.writeheader()
        writer.writerows(reversed(runs))
    scorer = AsyncMock(return_value=SimpleNamespace(value=0.5))
    output = tmp_path / "out"
    ok = asyncio.run(score_archive(archive, CASES, output, scorer=scorer))
    first, second = rows(output)
    if run_stamp == "explicit":
        assert ok and scorer.await_count == 2
        assert first["status"] == "scored"
        assert datetime.fromisoformat(
            first["run_started_at_utc"]
        ) == datetime.fromisoformat(original_stamp)
    else:
        assert not ok and scorer.await_count == 1
        assert (first["status"], first["reason"], first["score"]) == (
            "input_error",
            "missing_run_start_utc",
            "",
        )
    assert second["status"] == "scored"


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
    import httpx
    from ragas.llms.base import InstructorLLM

    from scripts.upload_scores import main as preview_scores

    async def unexpected_request(self, request):
        pytest.fail("채점 테스트에서 HTTP 요청을 시도했습니다")

    monkeypatch.setattr(
        httpx.AsyncHTTPTransport, "handle_async_request", unexpected_request
    )

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
    (scored,) = rows(out)
    assert scored["score"] == "0.0"
    report = tmp_path / "preview.csv"
    preview_scores(["--scores", str(out / "scores.csv"), "--report", str(report)])
    with report.open(newline="", encoding="utf-8") as stream:
        (receipt,) = csv.DictReader(stream)
    assert receipt["status"] == "dry_run"
    assert receipt["run_id"] == scored["run_id"]
    assert receipt["scored_at_utc"] == scored["scored_at_utc"]
    assert receipt["trace_id"] and receipt["score_id"]
