"""Langfuse 프로젝트별로 접수됐거나 확인이 필요한 span ID만 보관한다."""

import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path


@contextmanager
def journaled_post(scores: Path, project, lookup, post, trace_path, retry_missing):
    with closing(
        sqlite3.connect(scores.parent / "langfuse-spans.sqlite3", timeout=30)
    ) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS spans (
                project TEXT, trace_id TEXT, span_id TEXT, state TEXT NOT NULL,
                PRIMARY KEY (project, trace_id, span_id)
            )
        """)

        def publish(path, payload):
            if path != trace_path:
                return post(path, payload)
            for span in payload["resourceSpans"][0]["scopeSpans"][0]["spans"]:
                result = _send_span(
                    db, project, span, lookup, post, trace_path, retry_missing
                )
                if result is not True:
                    return result
            return True

        yield publish


def _send_span(db, project, span, lookup, post, trace_path, retry_missing):
    key = (project, span["traceId"], span["spanId"])
    # 조회와 예약을 직렬화한다. 프로세스가 POST 중 종료돼도 다음 실행은 먼저 조회한다.
    with db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT state FROM spans WHERE project=? AND trace_id=? AND span_id=?", key
        ).fetchone()
        if row == ("accepted",):
            return True
        if lookup is not None:
            present = lookup(span["traceId"], span["spanId"])
            if present is None:
                return None
            if present:
                db.execute(
                    "INSERT OR REPLACE INTO spans VALUES (?, ?, ?, 'accepted')", key
                )
                return True
        if row == ("pending",) and not (lookup is not None and retry_missing):
            return None
        db.execute("INSERT OR REPLACE INTO spans VALUES (?, ?, ?, 'pending')", key)

    result = post(trace_path, {"resourceSpans": [{"scopeSpans": [{"spans": [span]}]}]})
    with db:
        if result is True:
            db.execute(
                "UPDATE spans SET state='accepted' WHERE project=? AND trace_id=? AND span_id=?",
                key,
            )
        elif result is False:
            db.execute(
                "DELETE FROM spans WHERE project=? AND trace_id=? AND span_id=? AND state='pending'",
                key,
            )
    return result
