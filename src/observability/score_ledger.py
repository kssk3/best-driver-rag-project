"""여러 업로드 호스트가 같은 Langfuse 점수 ID의 최초 입력을 공유한다."""

import hashlib
import json
import os
from contextlib import contextmanager
from http.client import HTTPException
from uuid import uuid4

import psycopg

from src.observability.extra_scores import missing_scores, same_score, server_rows
from src.observability.tracing import SCORES


@contextmanager
def _locked_ledger(client, *, recovery=False):
    dsn = os.environ.get("RAG_SCORE_LEDGER_DSN")
    if not dsn:
        raise ValueError(
            "추가 점수 전송에는 팀 공용 PostgreSQL의 RAG_SCORE_LEDGER_DSN이 필요합니다."
        )
    project = client.project
    try:
        with psycopg.connect(
            dsn, autocommit=True, connect_timeout=10, client_encoding="UTF8"
        ) as db:
            # 여러 프로젝트의 최초 실행이 동시에 테이블을 만들 수 있다.
            with db.transaction():
                db.execute("SELECT pg_advisory_xact_lock(731653, 0)")
                db.execute("""CREATE TABLE IF NOT EXISTS rag_extra_score_ledger (
                    project TEXT NOT NULL, score_id TEXT NOT NULL, payload TEXT NOT NULL,
                    accepted BOOLEAN NOT NULL DEFAULT FALSE, PRIMARY KEY (project, score_id)
                )""")
                if recovery:
                    db.execute("""CREATE TABLE IF NOT EXISTS rag_extra_score_recovery (
                        project TEXT NOT NULL, score_id TEXT NOT NULL, token TEXT NOT NULL,
                        attempted_at TIMESTAMPTZ NOT NULL DEFAULT now(), status TEXT NOT NULL,
                        PRIMARY KEY (project, score_id)
                    )""")
            # 세션 잠금은 예약 커밋, HTTP 전송, 접수 상태 갱신을 모두 포함한다.
            db.execute("SELECT pg_advisory_lock(731654, hashtext(%s))", (project,))
            yield db, project
    except psycopg.Error:
        raise ValueError(
            "공용 점수 기록 DB에 접근할 수 없습니다. 연결과 테이블 권한을 확인하세요."
        ) from None


def _payload(score):
    return {k: v for k, v in score.items() if k not in ("run_id", "variant")}


def upload_scores(client, scores):
    with _locked_ledger(client) as (db, project):
        pending = missing_scores(client, scores)
        waiting = 0
        to_send = []
        for score in pending:
            payload = _payload(score)
            original = json.dumps(payload, sort_keys=True, ensure_ascii=False)
            key = (project, score["id"])
            previous = db.execute(
                "SELECT payload, accepted FROM rag_extra_score_ledger WHERE project=%s AND score_id=%s",
                key,
            ).fetchone()
            if previous and previous[0] != original:
                raise ValueError(
                    f"{score['traceId']} {score['name']}: 이전 전송의 원래 입력과 다릅니다."
                )
            if previous and previous[1]:
                waiting += 1
            else:
                to_send.append((key, original, payload))
        for key, original, payload in to_send:
            # POST 이전에 커밋한다. 응답 유실이나 프로세스 종료 후에도 다른 값은 전송할 수 없다.
            db.execute(
                """INSERT INTO rag_extra_score_ledger (project, score_id, payload)
                VALUES (%s,%s,%s) ON CONFLICT DO NOTHING""",
                (*key, original),
            )
            if client.request("POST", SCORES, [payload]) is not True:
                raise ValueError(
                    f"{payload['traceId']} {payload['name']}: 접수 미확인. --check로 먼저 조회하세요."
                )
            db.execute(
                "UPDATE rag_extra_score_ledger SET accepted=TRUE WHERE project=%s AND score_id=%s",
                key,
            )
        return len(to_send), waiting


def recover_score(client, score, confirmation):
    """접수된 원본 한 건을 대조하고, 큐 확인 번호당 한 번만 재전송한다."""
    with _locked_ledger(client, recovery=True) as (db, project):
        key = (project, score["id"])
        original = db.execute(
            "SELECT payload, accepted FROM rag_extra_score_ledger WHERE project=%s AND score_id=%s",
            key,
        ).fetchone()
        if not original or not original[1]:
            raise ValueError("현재 프로젝트 원장에 접수된 점수가 없습니다.")
        payload = json.loads(original[0])
        if original[0] != json.dumps(
            _payload(score), sort_keys=True, ensure_ascii=False
        ):
            raise ValueError("복구 입력이 최초 전송의 원래 입력과 다릅니다.")

        pending = missing_scores(client, [score], recovery=True)
        # trace 필터만으로는 다른 실행에 연결된 같은 ID를 발견할 수 없다.
        rows = server_rows(
            client, "/api/public/v3/scores", id=score["id"], fields="subject,details"
        )
        if not pending and len(rows) == 1 and same_score(rows[0], score):
            return "반영 확인. 추가 전송 0건."
        if rows or not pending:
            raise ValueError(
                "점수 ID 조회와 실행별 조회 결과가 충돌합니다. 다시 조회하세요."
            )

        previous = db.execute(
            "SELECT token, attempted_at, status FROM rag_extra_score_recovery WHERE project=%s AND score_id=%s",
            key,
        ).fetchone()
        initial = hashlib.sha256(json.dumps(key).encode()).hexdigest()
        token = previous[0] if previous else initial
        if confirmation is None:
            status = (
                f"마지막 복구 {previous[1].isoformat()} ({previous[2]})"
                if previous
                else "최초 접수 후 미등록"
            )
            return (
                f"{status}. 큐 처리 완료 확인 후 추가할 옵션: --queue-drained {token}"
            )
        if token != confirmation:
            raise ValueError(
                "현재 복구 시도와 확인 번호가 다릅니다. 큐와 접수 상태를 다시 확인하세요."
            )

        # POST 직전에 확인 번호를 교체·커밋한다. 중단되거나 응답이 유실돼도 재사용할 수 없다.
        db.execute(
            """INSERT INTO rag_extra_score_recovery (project, score_id, token, status)
            VALUES (%s,%s,%s,'접수 미확인') ON CONFLICT (project, score_id)
            DO UPDATE SET token=excluded.token, attempted_at=now(), status=excluded.status""",
            (*key, uuid4().hex),
        )
        try:
            accepted = client.request("POST", SCORES, [payload])
        except (OSError, HTTPException, ValueError):
            accepted = None
        if accepted is None:
            raise ValueError("복구 접수 미확인. --check와 큐 상태를 확인하세요.")
        db.execute(
            "UPDATE rag_extra_score_recovery SET status=%s WHERE project=%s AND score_id=%s",
            ("접수" if accepted else "거절", *key),
        )
        if not accepted:
            raise ValueError("서버가 복구 요청을 거절했습니다. 원인을 확인하세요.")
        return "복구 접수 1건. --check로 반영을 확인하세요."
