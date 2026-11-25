"""저장된 Faithfulness 점수를 명시적으로 Langfuse에 전송한다."""

import base64
import csv
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from http.client import HTTPSConnection
from pathlib import Path
from urllib.parse import urlsplit

TRACES = "/api/public/otel/v1/traces"
SCORES = "/api/public/scores"
REPORT_FIELDS = (
    "evaluation_id attempt_index run_id metric trace_id score_id scored_at_utc "
    "upload_attempted_at_utc status reason"
).split()


def langfuse_post():
    """인증 키는 HTTPS 인증 헤더에서만 사용한다."""
    url = urlsplit(os.environ.get("LANGFUSE_BASE_URL", ""))
    public = os.environ.get("LANGFUSE_PUBLIC_KEY")
    secret = os.environ.get("LANGFUSE_SECRET_KEY")
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise ValueError("LANGFUSE_BASE_URL requires an HTTPS base URL")
    if not public or not secret:
        raise ValueError("LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are required")
    token = base64.b64encode(f"{public}:{secret}".encode()).decode("ascii")

    def post(path, payload):
        headers = {
            "Authorization": "Basic " + token,
            "Content-Type": "application/json",
        }
        if path == TRACES:
            headers["x-langfuse-ingestion-version"] = "4"
        connection = HTTPSConnection(url.hostname, url.port, timeout=15)
        try:
            connection.request(
                "POST", url.path.rstrip("/") + path, json.dumps(payload), headers
            )
            response = connection.getresponse()
            if response.status not in (200, 202):
                return False
            body = json.load(response)
            if path == SCORES:
                return response.status == 202 and body == {"message": "Accepted"}
            return (
                response.status == 200
                and int(body.get("partialSuccess", {}).get("rejectedSpans", 0)) == 0
            )
        finally:
            connection.close()

    return post


def _identifier(*parts):
    encoded = json.dumps(parts, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()[:32]


def _utc(value):
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() != timedelta(0):
        raise ValueError("expected UTC")
    return parsed


def _payloads(row):
    metric = row["metric"]
    if metric != "faithfulness" or not row["run_id"] or not row["evaluation_id"]:
        raise ValueError("invalid score identity")
    value = float(row["score"])
    if not 0 <= value <= 1 or row["run_kind"] not in {"rag", "fixed_evidence", "demo"}:
        raise ValueError("invalid value or run kind")
    trace_id = _identifier("trace", row["run_id"])
    scored_at = _utc(row["scored_at_utc"])
    started = _utc(row["run_started_at_utc"]) - datetime(1970, 1, 1, tzinfo=UTC)
    nanos = str(started // timedelta(microseconds=1) * 1000)
    span = {
        "traceId": trace_id,
        "spanId": _identifier("span", row["run_id"])[:16],
        "name": "archived-run",
        "kind": 1,
        "startTimeUnixNano": nanos,
        "endTimeUnixNano": nanos,
        "attributes": [{"key": "run.kind", "value": {"stringValue": row["run_kind"]}}],
    }
    trace = {"resourceSpans": [{"scopeSpans": [{"spans": [span]}]}]}
    score = {
        "traceId": trace_id,
        "id": _identifier("score", row["evaluation_id"], row["run_id"], metric),
        "name": metric,
        "dataType": "NUMERIC",
        "value": value,
        "timestamp": scored_at.isoformat(),
    }
    return trace, score


def _publish(row, entry, post):
    if row["status"] != "scored":
        entry.update(status="skipped", reason="no_numeric_score")
        return
    try:
        trace, score = _payloads(row)
    except (ValueError, TypeError, KeyError):
        entry.update(status="failed", reason="invalid_score_row")
        return
    entry.update(trace_id=score["traceId"], score_id=score["id"])
    if post is None:
        entry.update(status="dry_run")
        return
    entry["upload_attempted_at_utc"] = datetime.now(UTC).isoformat()
    for stage, path, payload in (("trace", TRACES, trace), ("score", SCORES, [score])):
        try:
            accepted = post(path, payload)
        except Exception:
            entry.update(status="failed", reason=stage + "_unconfirmed")
            return
        if not accepted:
            entry.update(status="failed", reason=stage + "_not_accepted")
            return
    entry.update(status="accepted")


def publish_scores(scores: Path, report: Path, post=None) -> bool:
    """업로드 시도마다 새 영수증을 기록한다. post 미지정은 네트워크 없는 검증이다."""
    with scores.open(encoding="utf-8", newline="") as source:
        rows = csv.DictReader(source)
        required = {
            "evaluation_id",
            "attempt_index",
            "run_id",
            "metric",
            "score",
            "status",
            "scored_at_utc",
            "run_started_at_utc",
            "run_kind",
        }
        if not required.issubset(rows.fieldnames or []):
            raise ValueError("missing scores.csv columns")
        ok = True
        with report.open("x", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=REPORT_FIELDS)
            writer.writeheader()
            for row in rows:
                entry = {
                    key: row[key]
                    for key in (
                        "evaluation_id",
                        "attempt_index",
                        "run_id",
                        "metric",
                        "scored_at_utc",
                    )
                }
                _publish(row, entry, post)
                writer.writerow(entry)
                stream.flush()
                if entry["status"] == "failed":
                    ok = False
    return ok
