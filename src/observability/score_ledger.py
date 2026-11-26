"""여러 업로드 호스트가 같은 Langfuse 점수 ID의 최초 입력을 공유한다."""

import json
import os

import psycopg

from src.observability.extra_scores import missing_scores
from src.observability.tracing import SCORES


def upload_scores(client, scores):
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
            # 세션 잠금은 예약 커밋, HTTP 전송, 접수 상태 갱신을 모두 포함한다.
            db.execute("SELECT pg_advisory_lock(731654, hashtext(%s))", (project,))
            pending = missing_scores(client, scores)
            waiting = 0
            to_send = []
            for score in pending:
                payload = {
                    k: v for k, v in score.items() if k not in ("run_id", "variant")
                }
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
    except psycopg.Error:
        raise ValueError(
            "공용 점수 기록 DB에 접근할 수 없습니다. 연결과 테이블 권한을 확인하세요."
        ) from None
