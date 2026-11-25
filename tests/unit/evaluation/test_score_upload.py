import csv
import io
import json
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest

from scripts.upload_scores import main
from src.observability import tracing


def write_scores(path):
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


def test_upload_cli_retry_across_midnight(tmp_path, monkeypatch, transport):
    scores = tmp_path / "scores.csv"
    sample = write_scores(scores)
    original = scores.read_bytes()
    calls = transport.return_value
    calls.getresponse.side_effect = [
        response(200, {}),
        response(202, {"message": "Accepted"}),
        response(200, {}),
        response(202, {"message": "Accepted"}),
    ]
    clock = Mock(wraps=datetime)
    monkeypatch.setattr(tracing, "datetime", clock)
    clock.now.side_effect = [
        datetime(2026, 11, day, 23, 59, 59, tzinfo=UTC) for day in (25, 26)
    ]
    payloads = []
    for day in (25, 26):
        report = tmp_path / f"report-{day}.csv"
        main(["--scores", str(scores), "--report", str(report), "--upload"])
        accepted, skipped = receipt(report)
        assert accepted["status"] == "accepted" and skipped["status"] == "skipped"
        assert accepted["upload_attempted_at_utc"].startswith(f"2026-11-{day}")
        assert accepted["scored_at_utc"] == sample["scored_at_utc"]
        trace_request, score_request = calls.request.call_args_list[-2:]
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
            "timestamp": sample["scored_at_utc"],
        }
        assert span["traceId"] == accepted["trace_id"]
        payloads.append((trace, scores_body))
    assert payloads[0] == payloads[1]
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
    transport.return_value.getresponse.side_effect = responses
    with pytest.raises(SystemExit) as result:
        main(["--scores", str(scores), "--report", str(report), "--upload"])
    assert result.value.code == 1
    assert receipt(report)[0]["reason"] == reason
    assert "private-error" not in report.read_text()
    assert (scores.read_bytes(), snapshot.read_bytes()) == before
