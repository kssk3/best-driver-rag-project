"""저장된 Faithfulness 점수를 명시적으로 Langfuse에 전송한다."""

import base64
import csv
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from http.client import HTTPResponse, HTTPSConnection
from pathlib import Path
from urllib.parse import urlsplit

TRACES = "/api/public/otel/v1/traces"
SCORES = "/api/public/scores"
REPORT_FIELDS = (
    "evaluation_id attempt_index run_id metric trace_id score_id scored_at_utc "
    "upload_attempted_at_utc status reason"
).split()


def _accepted(path: str, response: HTTPResponse) -> bool | None:
    """True는 접수, False는 명시적 거절, None은 확인되지 않은 결과다."""
    status = response.status
    if 400 <= status < 500 and status != 408:
        return False
    if path == TRACES and status == 200:
        body = json.load(response)
        if body == {}:
            return True
        partial = body.get("partialSuccess")
        if isinstance(partial, dict):
            count = partial.get("rejectedSpans", 0)
            if (
                type(count) in (str, int)
                and str(count).isascii()
                and str(count).isdigit()
            ):
                return int(count) == 0
    if path == SCORES and status in (202, 207):
        body = json.load(response)
        if status == 202 and body.get("message") == "Accepted":
            return True
        # 이 클라이언트는 점수를 한 건씩 제출한다.
        if status == 207 and body.get("rejected") == 1 and body.get("accepted", 0) == 0:
            return False
    return None


def langfuse_post():
    """인증 키는 HTTPS 인증 헤더에서만 사용한다."""
    try:
        url = urlsplit(os.environ.get("LANGFUSE_BASE_URL", ""))
        hostname, port = url.hostname, url.port
    except ValueError as error:
        raise ValueError(
            "LANGFUSE_BASE_URL requires a valid hostname and port"
        ) from error
    public = os.environ.get("LANGFUSE_PUBLIC_KEY")
    secret = os.environ.get("LANGFUSE_SECRET_KEY")
    if (
        url.scheme != "https"
        or not hostname
        or url.username is not None
        or url.password is not None
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
        connection = HTTPSConnection(hostname, port, timeout=15)
        try:
            connection.request(
                "POST", url.path.rstrip("/") + path, json.dumps(payload), headers
            )
            return _accepted(path, connection.getresponse())
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
        "attributes": [
            {"key": "run.kind", "value": {"stringValue": row["run_kind"]}},
            {"key": "langfuse.environment", "value": {"stringValue": row["run_kind"]}},
        ],
    }
    trace = {"resourceSpans": [{"scopeSpans": [{"spans": [span]}]}]}
    score = {
        "traceId": trace_id,
        "id": _identifier("score", row["evaluation_id"], row["run_id"], metric),
        "name": metric,
        "dataType": "NUMERIC",
        "environment": row["run_kind"],
        "value": value,
        "timestamp": scored_at.isoformat(),
    }
    return trace, score


def _publish(row, entry, post):
    status = row["status"]
    if status not in {"scored", "skipped", "no_score", "input_error", "scorer_error"}:
        entry.update(status="failed", reason="unknown_score_status")
        return
    if (status == "scored") != bool(row["score"]):
        entry.update(status="failed", reason="score_status_conflict")
        return
    if status != "scored":
        entry.update(status="skipped", reason="no_numeric_score")
        return
    if not row["run_started_at_utc"]:
        entry.update(status="failed", reason="missing_run_started_at_utc")
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
            accepted = None
        if accepted is None:
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
