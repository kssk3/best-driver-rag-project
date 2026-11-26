"""Langfuse 프로젝트별로 접수됐거나 확인이 필요한 span ID만 보관한다."""

import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path


def recorded_project_aliases(scores: Path, project: str) -> set[str]:
    path = scores.with_name("langfuse-spans.sqlite3")
    if not path.is_file():
        return set()
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        if not db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='project_aliases'"
        ).fetchone():
            return set()
        return {
            row[0]
            for row in db.execute(
                "SELECT fingerprint FROM project_aliases WHERE project=?", (project,)
            )
        }


@contextmanager
def journaled_post(
    scores: Path,
    project,
    lookup,
    post,
    trace_path,
    retry_missing,
    *,
    legacy_project=None,
):
    with closing(
        sqlite3.connect(scores.parent / "langfuse-spans.sqlite3", timeout=30)
    ) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS spans (
                project TEXT, trace_id TEXT, span_id TEXT, state TEXT NOT NULL,
                PRIMARY KEY (project, trace_id, span_id)
            )
        """)

        if legacy_project:
            # 같은 인증 키로 프로젝트를 확인한 기존 접수 기록도 그대로 이어 쓴다.
            with db:
                db.execute(
                    "CREATE TABLE IF NOT EXISTS project_aliases (fingerprint TEXT PRIMARY KEY, project TEXT NOT NULL)"
                )
                db.execute(
                    "INSERT OR IGNORE INTO project_aliases VALUES (?, ?)",
                    (legacy_project, project),
                )
                if db.execute(
                    "SELECT project FROM project_aliases WHERE fingerprint=?",
                    (legacy_project,),
                ).fetchone() != (project,):
                    raise ValueError("기존 키의 프로젝트 연결이 서버 응답과 다릅니다.")
                db.execute(
                    """INSERT INTO spans SELECT ?, trace_id, span_id, state FROM spans WHERE project=?
                              ON CONFLICT(project, trace_id, span_id) DO UPDATE SET state='accepted'
                              WHERE excluded.state='accepted'""",
                    (project, legacy_project),
                )
                db.execute("DELETE FROM spans WHERE project=?", (legacy_project,))

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
            # 논리 루트 조회에서 발견했다면 attach_to_root가 이미 payload에서 제거했다.
            if lookup is not None and not span.get("parentSpanId"):
                return None
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
