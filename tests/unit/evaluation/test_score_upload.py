import csv
import io
import json
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest

from scripts.upload_scores import main
from src.observability import tracing


def write_scores(path, **overrides):
    row = dict(
        evaluation_id="evaluation1",
        attempt_index="1",
        run_id="run1",
        metric="faithfulness",
        score="0.0",
        status="scored",
        scored_at_utc="2026-11-25T23:59:59+00:00",
        run_started_at_utc="2026-11-24T12:00:00+00:00",
        run_kind="fixed_evidence",
        question="private-question",
        answer="private-answer",
        context="private-context",
        versions_json="private-key",
        reason="private-error",
    )
    row.update(overrides)
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
        writer.writerow(dict(row, attempt_index="2", status="no_score", score=""))
    return row


def receipt(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


@pytest.fixture
def transport(monkeypatch):
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://langfuse.invalid")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "dummy-public")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "private-credential")
    connection = Mock()
    monkeypatch.setattr(tracing, "HTTPSConnection", connection)
    return connection


def response(status, body):
    result = io.BytesIO(json.dumps(body).encode())
    result.status = status
    return result


def serve(connection, posts, lookups=None):
    posts = iter(posts)
    lookups = iter(lookups) if lookups is not None else None

    def getresponse():
        if connection.request.call_args.args[0] == "GET":
            return (
                next(lookups)
                if lookups is not None
                else response(200, {"data": [], "meta": {}})
            )
        result = next(posts)
        if isinstance(result, Exception):
            raise result
        return result

    connection.getresponse.side_effect = getresponse


def posts(connection):
    return [c for c in connection.request.call_args_list if c.args[0] == "POST"]


def test_upload_cli_retry_across_midnight(tmp_path, monkeypatch, transport):
    scores = tmp_path / "scores.csv"
    sample = write_scores(scores)
    original = scores.read_bytes()
    calls = transport.return_value
    serve(
        calls,
        [
            response(200, {}),
            response(504, {}),
            response(202, {"message": "Accepted"}),
        ],
    )
    clock = Mock(wraps=datetime)
    monkeypatch.setattr(tracing, "datetime", clock)
    clock.now.side_effect = [
        datetime(2026, 11, day, 23, 59, 59, tzinfo=UTC) for day in (25, 26)
    ]
    payloads = []
    for day in (25, 26):
        report = tmp_path / f"report-{day}.csv"
        args = ["--scores", str(scores), "--report", str(report), "--upload"]
        if day == 25:
            with pytest.raises(SystemExit) as error:
                main(args)
            assert error.value.code == 1
        else:
            main(args)
        accepted, skipped = receipt(report)
        assert accepted["trace_status"] == "accepted" and skipped["status"] == "skipped"
        assert accepted["score_status"] == ("unconfirmed" if day == 25 else "accepted")
        assert accepted["upload_attempted_at_utc"].startswith(f"2026-11-{day}")
        assert accepted["scored_at_utc"] == sample["scored_at_utc"]
        trace_request, score_request = posts(calls)[0], posts(calls)[-1]
        assert trace_request.args[:2] == ("POST", tracing.TRACES)
        assert score_request.args[:2] == ("POST", tracing.SCORES)
        assert trace_request.args[3]["x-langfuse-ingestion-version"] == "4"
        assert score_request.args[3]["Authorization"].startswith("Basic ")
        trace, scores_body = trace_request.args[2], score_request.args[2]
        assert all(
            secret not in trace + scores_body
            for secret in ("private-", "dummy-public", "run1")
        )
        (span,) = json.loads(trace)["resourceSpans"][0]["scopeSpans"][0]["spans"]
        (score,) = json.loads(scores_body)
        assert score == {
            "id": accepted["score_id"],
            "traceId": span["traceId"],
            "name": "faithfulness",
            "value": 0.0,
            "dataType": "NUMERIC",
            "environment": "fixed_evidence",
            "timestamp": sample["scored_at_utc"],
        }
        assert {
            "key": "langfuse.environment",
            "value": {"stringValue": "fixed_evidence"},
        } in span["attributes"]
        assert span["traceId"] == accepted["trace_id"]
        payloads.append((trace, scores_body))
    assert payloads[0] == payloads[1]
    assert [c.args[1] for c in posts(calls)] == [
        tracing.TRACES,
        tracing.SCORES,
        tracing.SCORES,
    ]
    assert transport.call_count == 4
    assert scores.read_bytes() == original
    _, other = tracing._payloads(dict(sample, evaluation_id="evaluation2"))
    assert other["id"] != score["id"] and other["traceId"] == score["traceId"]
    _, other = tracing._payloads(dict(sample, run_id="run2"))
    assert other["id"] != score["id"] and other["traceId"] != score["traceId"]


def test_default_off_and_no_overwrite(tmp_path, monkeypatch):
    monkeypatch.delenv("LANGFUSE_BASE_URL", raising=False)
    scores = tmp_path / "scores.csv"
    write_scores(scores)
    report = tmp_path / "report.csv"
    args = ["--scores", str(scores), "--report", str(report)]
    main(args)
    assert [r["status"] for r in receipt(report)] == ["dry_run", "skipped"]
    with pytest.raises(SystemExit):
        main(args)
    before = scores.read_bytes()
    with pytest.raises(SystemExit):
        main(["--scores", str(scores), "--report", str(scores)])
    assert scores.read_bytes() == before


@pytest.mark.parametrize(
    ("responses", "reason"),
    [
        ([TimeoutError("private-error")], "trace_unconfirmed"),
        ([response(401, {})], "trace_not_accepted"),
        ([response(200, {"unexpected": True})], "trace_unconfirmed"),
        ([response(200, {}), response(504, {})], "score_unconfirmed"),
        ([response(200, {}), response(408, {})], "score_unconfirmed"),
        ([response(200, {}), response(202, {})], "score_unconfirmed"),
        ([response(200, {}), response(207, {})], "score_unconfirmed"),
        (
            [response(200, {"partialSuccess": {"rejectedSpans": "1"}})],
            "trace_not_accepted",
        ),
        (
            [
                response(200, {}),
                response(207, {"rejected": 1, "errors": ["private-error"]}),
            ],
            "score_not_accepted",
        ),
    ],
)
def test_failure_preserves_files(tmp_path, transport, responses, reason):
    scores = tmp_path / "scores.csv"
    write_scores(scores)
    snapshot = tmp_path / "evaluation.json"
    snapshot.write_text('[{"status":"answered"}]')
    before = scores.read_bytes(), snapshot.read_bytes()
    report = tmp_path / "failed.csv"
    serve(transport.return_value, responses)
    with pytest.raises(SystemExit) as result:
        main(["--scores", str(scores), "--report", str(report), "--upload"])
    assert result.value.code == 1
    assert receipt(report)[0]["reason"] == reason
    assert "private-error" not in report.read_text()
    assert (scores.read_bytes(), snapshot.read_bytes()) == before


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"status": "scorred"}, "unknown_score_status"),
        ({"status": "skipped"}, "score_status_conflict"),
        ({"status": "scored", "score": ""}, "score_status_conflict"),
        ({"run_started_at_utc": ""}, "missing_run_started_at_utc"),
        ({"score": "not-numeric"}, "invalid_score_row"),
        ({"score": "NaN"}, "invalid_score_row"),
        ({"score": "-0.01"}, "invalid_score_row"),
        ({"score": "1.01"}, "invalid_score_row"),
        ({"metric": "unsupported"}, "invalid_score_row"),
        ({"run_kind": "unknown"}, "invalid_score_row"),
        ({"scored_at_utc": "2026-11-25T23:59:59"}, "invalid_score_row"),
        ({"run_started_at_utc": "2026-11-25T12:00:00+09:00"}, "invalid_score_row"),
    ],
)
def test_invalid_score_rows_capture_reason_and_skip_transmission(
    tmp_path, transport, overrides, reason
):
    scores = tmp_path / "scores.csv"
    write_scores(scores, **overrides)
    report = tmp_path / "report.csv"
    with pytest.raises(SystemExit) as error:
        main(["--scores", str(scores), "--report", str(report), "--upload"])
    assert error.value.code == 1
    first, next_row = receipt(report)
    assert (first["status"], first["reason"]) == ("failed", reason)
    assert first["upload_attempted_at_utc"] == ""
    assert next_row["status"] == "skipped"
    transport.assert_not_called()


@pytest.mark.parametrize("kind", ["fixed_evidence", "rag", "demo"])
def test_score_and_span_share_run_kind_environment(tmp_path, kind):
    sample = write_scores(tmp_path / "scores.csv", run_kind=kind)
    trace, score = tracing._payloads(sample)
    (span,) = trace["resourceSpans"][0]["scopeSpans"][0]["spans"]
    attrs = {attr["key"]: attr["value"]["stringValue"] for attr in span["attributes"]}
    assert score["environment"] == attrs["langfuse.environment"] == kind


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("LANGFUSE_BASE_URL", None),
        ("LANGFUSE_BASE_URL", "http://langfuse.invalid"),
        ("LANGFUSE_BASE_URL", "https://langfuse.invalid:invalid-port"),
        ("LANGFUSE_BASE_URL", "https://@langfuse.invalid"),
        ("LANGFUSE_BASE_URL", "https://dummy:dummy@langfuse.invalid"),
        ("LANGFUSE_BASE_URL", "https://langfuse.invalid?param=private-query"),
        ("LANGFUSE_BASE_URL", "https://langfuse.invalid#fragment"),
        ("LANGFUSE_PUBLIC_KEY", None),
        ("LANGFUSE_SECRET_KEY", None),
    ],
)
def test_invalid_connection_settings_exit_before_creating_report(
    tmp_path, transport, monkeypatch, capsys, name, value
):
    scores = tmp_path / "scores.csv"
    write_scores(scores)
    original = scores.read_bytes()
    report = tmp_path / "report.csv"
    if value is None:
        monkeypatch.delenv(name)
    else:
        monkeypatch.setenv(name, value)
    with pytest.raises(SystemExit) as error:
        main(["--scores", str(scores), "--report", str(report), "--upload"])
    assert error.value.code == 2
    message = capsys.readouterr().err
    assert name in message
    assert "private-credential" not in message and "private-query" not in message
    assert scores.read_bytes() == original
    assert not report.exists()
    transport.assert_not_called()


@pytest.mark.parametrize(
    "missing",
    [
        "evaluation_id",
        "attempt_index",
        "run_id",
        "metric",
        "score",
        "status",
        "scored_at_utc",
        "run_started_at_utc",
        "run_kind",
    ],
)
def test_missing_score_header_exits_before_upload(tmp_path, transport, capsys, missing):
    scores = tmp_path / "scores.csv"
    row = write_scores(scores)
    del row[missing]
    with scores.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    report = tmp_path / "report.csv"
    with pytest.raises(SystemExit) as error:
        main(["--scores", str(scores), "--report", str(report), "--upload"])
    assert error.value.code == 2
    assert "missing scores.csv columns" in capsys.readouterr().err
    assert not report.exists()
    transport.assert_not_called()


@pytest.mark.parametrize("first_status", ["dry_run", "accepted", "score_unconfirmed"])
def test_only_first_valid_row_for_score_id_is_published(
    tmp_path, transport, first_status
):
    scores = tmp_path / "scores.csv"
    # Invalid and scoreless rows with the same identity must not reserve it.
    row = write_scores(scores, score="NaN")
    with scores.open("a", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(row))
        writer.writerow(dict(row, attempt_index=3, score="0.2"))
        writer.writerow(dict(row, attempt_index=4, score="0.8"))
        writer.writerow(dict(row, attempt_index=5, score="1.0", evaluation_id="other"))
    original = scores.read_bytes()
    report = tmp_path / "report.csv"
    args = ["--scores", str(scores), "--report", str(report)]
    connection = transport.return_value
    if first_status != "dry_run":
        args.append("--upload")
        serve(
            connection,
            [
                response(200, {}),
                response(504, {})
                if first_status == "score_unconfirmed"
                else response(202, {"message": "Accepted"}),
                response(202, {"message": "Accepted"}),
            ],
        )

    with pytest.raises(SystemExit) as error:
        main(args)
    assert error.value.code == 1
    invalid, skipped, first, duplicate, independent = receipt(report)
    assert invalid["reason"] == "invalid_score_row"
    assert skipped["reason"] == "no_numeric_score"
    if first_status == "score_unconfirmed":
        assert (first["status"], first["reason"]) == ("failed", "score_unconfirmed")
    else:
        assert first["status"] == first_status
    assert (duplicate["status"], duplicate["reason"]) == (
        "failed",
        "duplicate_score_identity",
    )
    assert duplicate["upload_attempted_at_utc"] == ""
    assert duplicate["score_id"] == first["score_id"] != independent["score_id"]
    if first_status == "dry_run":
        assert independent["status"] == "dry_run"
        transport.assert_not_called()
    else:
        assert independent["status"] == "accepted"
        requests = posts(connection)
        assert [call.args[1] for call in requests] == [
            tracing.TRACES,
            tracing.SCORES,
            tracing.SCORES,
        ]
        assert [json.loads(call.args[2])[0]["value"] for call in requests[1:]] == [
            0.2,
            1.0,
        ]
    assert scores.read_bytes() == original


def test_explicit_judgments_share_parent_and_keep_score_identity(tmp_path):
    score_path = tmp_path / "scores.csv"
    write_scores(score_path)
    with score_path.open(newline="") as f:
        records = list(csv.DictReader(f))
    details = tmp_path / "details.jsonl"

    def detail(row):
        return dict(
            evaluation_id=row["evaluation_id"],
            run_id=row["run_id"],
            metric="faithfulness",
            attempt_index=int(row["attempt_index"]),
            model_input_chunk_ids=["chunk2", "chunk1"],
            statements=["a"],
            verdicts=[{"statement": "a", "reason": "missing", "verdict": 0}],
        )

    # 별도 실행의 무점수 시도도 진단 내용을 전송한다.
    records[1]["run_id"] = "other"
    with score_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=records[0])
        w.writeheader()
        w.writerows(records)
    details.write_text("".join(json.dumps(detail(r)) + "\n" for r in records))
    calls = []

    def post(path, payload):
        calls.append((path, payload))
        return True

    for i in range(2):
        assert tracing.publish_scores(
            score_path, tmp_path / f"r{i}.csv", post, judgments=details
        )
    assert [p for p, _ in calls] == [
        tracing.TRACES,
        tracing.TRACES,
        tracing.SCORES,
        tracing.TRACES,
        tracing.TRACES,
        tracing.SCORES,
    ]
    original, score = tracing._payloads(records[0])
    assert calls[2][1] == calls[-1][1] == [score]
    parent, child = (
        payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        for _, payload in calls[:2]
    )
    assert parent == original["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    assert (
        child["traceId"] == score["traceId"]
        and child["parentSpanId"] == parent["spanId"]
    )
    output = json.loads(child["attributes"][-1]["value"]["stringValue"])
    assert output["score"] == 0 and output["verdicts"][0]["reason"] == "missing"
    details.write_text(json.dumps(detail(records[1])))
    with pytest.raises(ValueError, match="누락"):
        tracing.publish_scores(
            score_path, tmp_path / "missing.csv", post, judgments=details
        )
    assert len(calls) == 6


@pytest.mark.parametrize(
    "recovery", ["found", "wait", "explicit", "lookup_error", "wrong_id"]
)
def test_uncertain_span_is_reconciled_before_retry(tmp_path, transport, recovery):
    from urllib.parse import parse_qs, urlsplit

    scores = tmp_path / "scores.csv"
    row = write_scores(scores)
    trace, _ = tracing._payloads(row)
    span = trace["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    matches = {"id": span["spanId"], "traceId": span["traceId"]}
    conn = transport.return_value
    report = tmp_path / "first.csv"
    args = ["--scores", str(scores), "--upload", "--report"]
    serve(conn, [TimeoutError()])
    with pytest.raises(SystemExit):
        main([*args, str(report)])
    assert receipt(report)[0]["reason"] == "trace_unconfirmed"
    conn.request.reset_mock()
    found = [matches] if recovery == "found" else []
    if recovery == "wrong_id":
        found = [dict(matches, traceId="other")]
    serve(
        conn,
        [response(200, {}), response(202, {"message": "Accepted"})]
        if recovery == "explicit"
        else [response(202, {"message": "Accepted"})],
        [
            response(
                503 if recovery == "lookup_error" else 200, {"data": found, "meta": {}}
            )
        ],
    )
    second = tmp_path / "second.csv"
    if recovery in {"wait", "lookup_error", "wrong_id"}:
        with pytest.raises(SystemExit):
            main([*args, str(second)])
        assert posts(conn) == []
        assert receipt(second)[0]["reason"] == "trace_unconfirmed"
    else:
        main(
            [
                *args,
                str(second),
                *(["--retry-missing-spans"] if recovery == "explicit" else []),
            ]
        )
        expected = (
            [tracing.SCORES]
            if recovery == "found"
            else [tracing.TRACES, tracing.SCORES]
        )
        assert [c.args[1] for c in posts(conn)] == expected
        assert receipt(second)[0]["status"] == "accepted"
    method, path, body, _ = conn.request.call_args_list[0].args
    assert method == "GET" and body is None
    query = parse_qs(urlsplit(path).query)
    assert query["fields"] == ["core"]
    assert {f["column"]: f["value"] for f in json.loads(query["filter"][0])} == matches


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (
            {
                "name": "otel-ingestion-job",
                "data": {"name": "otel-ingestion-job", "id": "mock-job"},
            },
            True,
        ),
        (
            {
                "name": "otel-ingestion-job",
                "data": {"name": "otel-ingestion-job", "id": ""},
            },
            None,
        ),
        ({"partialSuccess": {"rejectedSpans": "unknown"}}, None),
        ({"partialSuccess": {"rejectedSpans": "0"}}, True),
    ],
)
def test_otlp_receipt_requires_confirmed_result(body, expected):
    assert tracing._accepted(tracing.TRACES, response(200, body)) is expected
