"""저장된 Faithfulness 점수를 명시적으로 Langfuse에 전송한다."""

import base64
import csv
import hashlib
import json
import os
import re
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from http.client import HTTPResponse, HTTPSConnection
from pathlib import Path
from urllib.parse import SplitResult, urlencode, urlsplit

from src.evaluation.judgment_details import JudgmentDetails
from src.observability.upload_state import journaled_post

TRACES = "/api/public/otel/v1/traces"
SCORES = "/api/public/scores"
REPORT_FIELDS = (
    "evaluation_id attempt_index run_id metric trace_id score_id scored_at_utc "
    "upload_attempted_at_utc trace_status score_status status reason"
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
        # 자체 호스팅 4.86은 큐에 정상 접수한 경우 작업 영수증을 반환한다.
        job = body.get("data")
        if (
            body.get("name") == "otel-ingestion-job"
            and isinstance(job, dict)
            and job.get("name") == "otel-ingestion-job"
            and isinstance(job.get("id"), str)
            and job["id"]
        ):
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


def langfuse_settings() -> tuple[SplitResult, str, str]:
    try:
        url = urlsplit(os.environ.get("LANGFUSE_BASE_URL", ""))
        # url.port에 접근해야 숫자가 아닌 포트도 이 시점에 거절된다.
        hostname, _port = url.hostname, url.port
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
    return url, public, secret


class LangfuseUpload:
    def __init__(self):
        url, public, secret = langfuse_settings()
        assert url.hostname is not None  # langfuse_settings에서 검증한 호스트
        self.hostname = url.hostname
        self.url = url
        self.project = project_fingerprint(url, public)
        token = base64.b64encode(f"{public}:{secret}".encode()).decode("ascii")
        self.headers = {
            "Authorization": "Basic " + token,
            "Content-Type": "application/json",
        }

    def request(self, method, path, payload=None):
        headers = self.headers.copy()
        if path == TRACES:
            headers["x-langfuse-ingestion-version"] = "4"
        connection = HTTPSConnection(self.hostname, self.url.port, timeout=15)
        try:
            connection.request(
                method,
                self.url.path.rstrip("/") + path,
                json.dumps(payload) if payload is not None else None,
                headers,
            )
            response = connection.getresponse()
            if method == "POST":
                return _accepted(path, response)
            if response.status == 200:
                return json.load(response)
            return None
        finally:
            connection.close()

    def __call__(self, path, payload):
        return self.request("POST", path, payload)

    def attach_to_root(self, payload, recorded_project):
        spans = payload["resourceSpans"][0]["scopeSpans"][0]["spans"]
        trace_id = spans[0]["traceId"]
        query = urlencode(
            {
                "traceId": trace_id,
                "isRootObservation": "true",
                "fields": "core,basic",
                "limit": 2,
            }
        )
        body = self.request("GET", "/api/public/v2/observations?" + query)
        if (
            not isinstance(body, dict)
            or not isinstance(body.get("meta"), dict)
            or body["meta"].get("cursor")
        ):
            raise ValueError("incomplete root lookup")
        rows = body.get("data")
        if rows == [] and recorded_project != self.project:
            return  # 이 프로젝트에서 추적한 기록이 없으면 보관본 루트를 쓴다.
        if (
            not isinstance(rows, list)
            or len(rows) != 1
            or not isinstance(rows[0], dict)
        ):
            raise ValueError("expected one root")
        root = rows[0]
        root_id = root.get("id")
        if (
            root.get("traceId") != trace_id
            or root.get("isRootObservation") is not True
            or not isinstance(root_id, str)
            or not re.fullmatch(r"[0-9a-f]{16}", root_id)
            or root_id == "0" * 16
        ):
            raise ValueError("invalid root")
        spans.pop(0)
        for child in spans:
            child["parentSpanId"] = root_id

    def find_span(self, trace_id, span_id):
        filters = [
            {"column": column, "operator": "=", "type": "string", "value": value}
            for column, value in (("traceId", trace_id), ("id", span_id))
        ]
        query = urlencode({"fields": "core", "limit": 1, "filter": json.dumps(filters)})
        body = self.request("GET", "/api/public/v2/observations?" + query)
        if not isinstance(body, dict) or not isinstance(body.get("meta"), dict):
            return None
        rows = body.get("data")
        if rows == [] and not body["meta"].get("cursor"):
            return False
        if isinstance(rows, list) and any(
            isinstance(r, dict)
            and r.get("id") == span_id
            and r.get("traceId") == trace_id
            for r in rows
        ):
            return True
        return None


def langfuse_post() -> LangfuseUpload:
    return LangfuseUpload()


def _identifier(*parts):
    encoded = json.dumps(parts, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()[:32]


def project_fingerprint(url: SplitResult, public: str) -> str:
    return _identifier(url.geturl().rstrip("/"), public)


def trace_id_for_run(run_id: str) -> str:
    return _identifier("trace", run_id)


def _utc(value):
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() != timedelta(0):
        raise ValueError("expected UTC")
    return parsed


def _trace_payload(row, details: JudgmentDetails | None = None):
    if (
        row["run_kind"] not in {"rag", "fixed_evidence", "demo"}
        or row["metric"] != "faithfulness"
    ):
        raise ValueError("invalid trace row")
    trace_id = trace_id_for_run(row["run_id"])
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
    spans = [span]
    if details is not None:
        at = _utc(row["scored_at_utc"]) - datetime(1970, 1, 1, tzinfo=UTC)
        at_nanos = str(at // timedelta(microseconds=1) * 1000)
        detail_id = _identifier(
            "judgment", row["evaluation_id"], row["run_id"], row["metric"]
        )[:16]
        output = {
            **details.model_dump(),
            "score": float(row["score"]) if row["score"] else None,
            "status": row["status"],
            "reason": row.get("reason") or None,
        }
        spans.append(
            {
                **span,
                "spanId": detail_id,
                "parentSpanId": span["spanId"],
                "startTimeUnixNano": at_nanos,
                "endTimeUnixNano": at_nanos,
                "name": "faithfulness",
                "attributes": [
                    *span["attributes"],
                    {
                        "key": "langfuse.observation.output",
                        "value": {
                            "stringValue": json.dumps(output, ensure_ascii=False)
                        },
                    },
                ],
            }
        )
    return {"resourceSpans": [{"scopeSpans": [{"spans": spans}]}]}


def _payloads(row, details=None):
    metric = row["metric"]
    if metric != "faithfulness" or not row["run_id"] or not row["evaluation_id"]:
        raise ValueError("invalid score identity")
    value = float(row["score"])
    if not 0 <= value <= 1:
        raise ValueError("invalid value or run kind")
    trace_id = trace_id_for_run(row["run_id"])
    scored_at = _utc(row["scored_at_utc"])
    trace = _trace_payload(row, details)
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


def _publish(row, entry, post, seen_score_ids, details, attach_to_root):
    status = row["status"]
    if status not in {"scored", "skipped", "no_score", "input_error", "scorer_error"}:
        entry.update(status="failed", reason="unknown_score_status")
        return
    if (status == "scored") != bool(row["score"]):
        entry.update(status="failed", reason="score_status_conflict")
        return
    if status != "scored" and details is None:
        entry.update(status="skipped", reason="no_numeric_score")
        return
    if not row["run_started_at_utc"]:
        entry.update(status="failed", reason="missing_run_started_at_utc")
        return
    try:
        trace_id = trace_id_for_run(row["run_id"])
        identity = _identifier(
            "score", row["evaluation_id"], row["run_id"], row["metric"]
        )
        if status == "scored":
            trace, score = _payloads(row, details)
            requests = [("trace", TRACES, trace), ("score", SCORES, [score])]
            entry["score_id"] = score["id"]
        else:
            requests = [("trace", TRACES, _trace_payload(row, details))]
        entry["trace_id"] = trace_id
    except (ValueError, TypeError, KeyError):
        entry.update(status="failed", reason="invalid_score_row")
        return
    if identity in seen_score_ids:
        entry.update(status="failed", reason="duplicate_score_identity")
        return
    seen_score_ids.add(identity)
    if post is None:
        entry.update(status="dry_run")
        return
    entry["upload_attempted_at_utc"] = datetime.now(UTC).isoformat()
    entry.update(
        trace_status="pending",
        score_status="pending" if status == "scored" else "skipped",
    )
    for stage, path, payload in requests:
        try:
            if stage == "trace" and attach_to_root is not None:
                attach_to_root(payload, row.get("langfuse_project"))
            accepted = post(path, payload)
        except Exception:
            accepted = None
        entry[stage + "_status"] = {
            True: "accepted",
            False: "not_accepted",
            None: "unconfirmed",
        }[accepted]
        if accepted is None:
            entry.update(status="failed", reason=stage + "_unconfirmed")
            return
        if not accepted:
            entry.update(status="failed", reason=stage + "_not_accepted")
            return
    entry.update(status="accepted")


def _read_details(path: Path, rows: list[dict]):
    expected = {
        (r["evaluation_id"], r["attempt_index"], r["run_id"], r["metric"])
        for r in rows
        if r["status"] in {"scored", "no_score", "scorer_error"}
    }
    details = {}
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            item = JudgmentDetails.model_validate_json(line)
            key = (
                item.evaluation_id,
                str(item.attempt_index),
                item.run_id,
                item.metric,
            )
            if key not in expected or key in details or not item.model_input_chunk_ids:
                raise ValueError("점수와 상세 파일의 채점 시도가 다릅니다.")
            details[key] = item
    if details.keys() != expected:
        raise ValueError("점수에 대응하는 채점 상세가 누락됐습니다.")
    return details


def publish_scores(
    scores: Path,
    report: Path,
    post=None,
    *,
    judgments: Path | None = None,
    retry_missing=False,
) -> bool:
    """업로드 시도마다 새 영수증을 기록한다. post 미지정은 네트워크 없는 검증이다."""
    project = post.project if isinstance(post, LangfuseUpload) else "injected"
    lookup = post.find_span if isinstance(post, LangfuseUpload) else None
    attach_to_root = post.attach_to_root if isinstance(post, LangfuseUpload) else None
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
        if judgments:
            records = list(rows)
            details = _read_details(judgments, records)
        else:
            details = {}
        seen_score_ids: set[str] = set()
        ok = True
        with (
            report.open("x", encoding="utf-8", newline="") as stream,
            journaled_post(scores, project, lookup, post, TRACES, retry_missing)
            if post is not None
            else nullcontext() as send,
        ):
            writer = csv.DictWriter(stream, fieldnames=REPORT_FIELDS)
            writer.writeheader()
            for row in records if judgments else rows:
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
                key = (
                    row["evaluation_id"],
                    row["attempt_index"],
                    row["run_id"],
                    row["metric"],
                )
                _publish(
                    row, entry, send, seen_score_ids, details.get(key), attach_to_root
                )
                writer.writerow(entry)
                stream.flush()
                if entry["status"] == "failed":
                    ok = False
    return ok
