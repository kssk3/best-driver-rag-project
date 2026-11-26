import csv
import json
import os
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest

from scripts import upload_extra_scores as cli
from src.observability.extra_scores import PRECISION, RECALL, RELEVANCY
from src.observability.tracing import SCORES, trace_id_for_run


def table(tmp_path, name, rows):
    with (tmp_path / name).open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0])
        w.writeheader()
        w.writerows(rows)


@pytest.fixture
def sample(tmp_path):
    runs, candidates, scores = [], [], []
    case = dict(dataset_id="dataset", case_id="case")
    table(tmp_path, "cases.csv", [{**case, "allowed_chunk_ids_json": '["c1","c7"]'}])
    for index in range(4):
        run = dict(
            **case,
            run_id=f"run-{index}",
            run_kind="rag",
            candidate_count=6,
            top_k=6,
            status="insufficient_evidence" if index == 0 else "answered",
            answer="저장 응답",
            retrieval_status="ok",
        )
        runs.append(run)
        for rank in range(1, 7):
            candidates.append(
                dict(**case, run_id=run["run_id"], rank=rank, chunk_id=f"c{rank}")
            )
        for name, value in (
            (RELEVANCY, 0 if not index else 1),
            (RECALL, 0.5),
            (PRECISION, 0.2),
        ):
            scores.append(
                dict(
                    traceId=trace_id_for_run(run["run_id"]),
                    name=name,
                    value=value,
                    timestamp="2026-11-25T23:59:59.123456Z",
                    comment="팀 저장 척도 0~1" if name == RELEVANCY else "",
                )
            )
    table(tmp_path, "runs.csv", runs)
    table(tmp_path, "candidates.csv", candidates)
    return tmp_path, scores


def invoke(sample, *args):
    p, rows = sample
    file = p / "preview.json"
    file.write_text(json.dumps(rows))
    cli.main(
        ["--archive", str(p), "--preview", str(file), "--expected-traces", "4", *args]
    )


class Server:
    def __init__(self):
        self.project = "test-" + uuid4().hex
        self.variant = None
        self.sent = []
        self.rows = []
        self.missing_root = None
        self.reject_at = None

    def request(self, method, path, payload=None):
        if method == "POST":
            assert path == SCORES
            if len(self.sent) == self.reject_at:
                return None
            score = payload[0]
            self.sent.append(score)
            self.rows.append(
                {**score, "subject": {"kind": "trace", "id": score["traceId"]}}
            )
            return True
        q = parse_qs(urlsplit(path).query)
        if "id" in q:
            assert urlsplit(path).path == "/api/public/v3/scores"
            return {
                "data": [r for r in self.rows if r.get("id") == q["id"][0]],
                "meta": {},
            }
        trace = q["traceId"][0]
        if "observations" in path:
            data = (
                []
                if trace == self.missing_root
                else [
                    dict(
                        isRootObservation=True,
                        traceId=trace,
                        environment="rag",
                        metadata={"variant": self.variant},
                    )
                ]
            )
        else:
            data = [r for r in self.rows if r["subject"]["id"] == trace]
        return {"data": data, "meta": {"cursor": None}}


def test_four_traces_and_retry(sample, monkeypatch, shared_ledger):
    server = Server()
    protected = {
        "name": "faithfulness",
        "value": 0.0,
        "id": "prior",
        "subject": {"kind": "trace", "id": sample[1][0]["traceId"]},
    }
    server.rows.append(protected.copy())
    monkeypatch.setattr(
        cli, "langfuse_post", lambda: pytest.fail("오프라인에서 서버 접근")
    )
    invoke(sample)
    monkeypatch.setattr(cli, "langfuse_post", lambda: server)
    invoke(sample, "--check")
    assert not server.sent
    server.reject_at = 4
    with pytest.raises(SystemExit):
        invoke(sample, "--upload")
    server.reject_at = None
    invoke(sample, "--upload")
    invoke(sample, "--upload")
    assert len(server.sent) == len({s["id"] for s in server.sent}) == 12
    assert server.sent[0]["value"] == 0
    assert "보류 안내" in server.sent[0]["comment"]
    assert server.sent[0]["timestamp"] == "2026-11-25T23:59:59.123456+00:00"
    assert server.rows[0] == protected


@pytest.mark.parametrize(
    "problem",
    [
        "duplicate",
        "missing",
        "wrong_precision",
        "nan",
        "bool",
        "wrong_trace",
        "forbidden_metric",
        "wrong_source",
        "empty_gold",
    ],
)
def test_invalid_batch_never_writes(sample, monkeypatch, problem):
    p, rows = sample
    if problem == "duplicate":
        rows.append(rows[0])
    elif problem == "missing":
        rows.pop()
    elif problem == "wrong_source":
        f = p / "candidates.csv"
        f.write_text(f.read_text().replace("dataset,case", "other,case", 1))
    elif problem == "empty_gold":
        table(
            p,
            "cases.csv",
            [dict(dataset_id="dataset", case_id="case", allowed_chunk_ids_json="[]")],
        )
    else:
        field, value = {
            "wrong_precision": ("value", 0.9),
            "nan": ("value", float("nan")),
            "bool": ("value", True),
            "wrong_trace": ("traceId", "a" * 32),
            "forbidden_metric": ("name", "faithfulness"),
        }[problem]
        rows[2][field] = value
    monkeypatch.setattr(
        cli, "langfuse_post", lambda: pytest.fail("잘못된 파일의 전송 시도")
    )
    with pytest.raises(SystemExit):
        invoke(sample, "--upload")


@pytest.mark.parametrize("problem", ["missing_root", "conflicting_score"])
def test_preflight_checks_last_trace_before_first_post(
    sample, monkeypatch, problem, shared_ledger
):
    server = Server()
    last = sample[1][-1]
    if problem == "missing_root":
        server.missing_root = last["traceId"]
    else:
        server.rows.append(
            {
                **last,
                "value": 0.9,
                "dataType": "NUMERIC",
                "subject": {"kind": "trace", "id": last["traceId"]},
            }
        )
    monkeypatch.setattr(cli, "langfuse_post", lambda: server)
    with pytest.raises(SystemExit):
        invoke(sample, "--upload")
    assert not server.sent


def test_undefined_id_metrics_keep_relevancy(sample, monkeypatch, shared_ledger):
    path, rows = sample
    table(
        path,
        "cases.csv",
        [dict(dataset_id="dataset", case_id="case", allowed_chunk_ids_json="[]")],
    )
    rows[:] = [row for row in rows if row["name"] == RELEVANCY]
    server = Server()
    monkeypatch.setattr(cli, "langfuse_post", lambda: server)
    invoke(sample, "--upload")
    assert len(server.sent) == 4
    assert all(row["name"] == RELEVANCY and "run_id" not in row for row in server.sent)


def test_explicit_trace_mapping_requires_same_server_run(
    sample, monkeypatch, shared_ledger
):
    path, scores = sample
    with (path / "runs.csv").open() as f:
        runs = list(csv.DictReader(f))
    for run in runs:
        run["trace_id"] = ""
    runs[-1]["trace_id"] = "c" * 32
    table(path, "runs.csv", runs)
    for score in scores[-3:]:
        score["traceId"] = "c" * 32
    server = Server()
    monkeypatch.setattr(cli, "langfuse_post", lambda: server)
    with pytest.raises(SystemExit):
        invoke(sample, "--upload")
    assert not server.sent


@pytest.fixture
def shared_ledger(monkeypatch):
    test_dsn = os.environ.get("TEST_SCORE_LEDGER_DSN")
    if not test_dsn:
        pytest.skip("임시 PostgreSQL의 TEST_SCORE_LEDGER_DSN이 필요합니다.")
    monkeypatch.setenv("RAG_SCORE_LEDGER_DSN", test_dsn)


def test_delayed_visibility_does_not_replace_accepted_input(
    sample, monkeypatch, shared_ledger
):
    server = Server()
    monkeypatch.setattr(cli, "langfuse_post", lambda: server)
    invoke(sample, "--upload")
    server.rows.clear()  # 접수 뒤에도 v3 읽기에는 아직 반영되지 않았다.
    invoke(sample, "--upload")
    assert len(server.sent) == 12
    sample[1][0]["value"] = 0.8
    with pytest.raises(SystemExit):
        invoke(sample, "--upload")
    assert len(server.sent) == 12


def test_extra_variant_conflict_precedes_all_posts(sample, monkeypatch, shared_ledger):
    path, _ = sample
    with (path / "runs.csv").open() as f:
        runs = list(csv.DictReader(f))
    for run in runs:
        run["variant"] = "B"
    table(path, "runs.csv", runs)
    server = Server()
    server.variant = "A"
    monkeypatch.setattr(cli, "langfuse_post", lambda: server)
    with pytest.raises(SystemExit):
        invoke(sample, "--upload")
    assert not server.sent


def test_concurrent_writers_use_one_reservation(sample, monkeypatch, shared_ledger):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from src.observability.extra_scores import prepare_scores
    from src.observability.score_ledger import upload_scores

    path, rows = sample
    preview = path / "batch.json"
    preview.write_text(json.dumps(rows))
    scores = prepare_scores(preview, path, 4)
    server = Server()
    entered, release = Event(), Event()
    request = server.request

    def delayed(method, path, payload=None):
        if method == "POST":
            entered.set()
            assert release.wait(5)
            server.sent.append(payload[0])
            return True  # 접수 후 읽기에서는 계속 보이지 않는다.
        return request(method, path, payload)

    monkeypatch.setattr(server, "request", delayed)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(upload_scores, server, scores)
        assert entered.wait(5)
        second = pool.submit(
            upload_scores, server, [*scores[:-1], dict(scores[-1], value=0.8)]
        )
        release.set()
        assert first.result(timeout=10) == (12, 0)
        with pytest.raises(ValueError, match="원래 입력"):
            second.result(timeout=10)
    assert len(server.sent) == 12


def test_unconfirmed_post_keeps_original_payload(sample, monkeypatch, shared_ledger):
    server = Server()
    server.reject_at = 1
    monkeypatch.setattr(cli, "langfuse_post", lambda: server)
    with pytest.raises(SystemExit):
        invoke(sample, "--upload")
    # 첫 POST는 접수됐고, 두 번째 POST의 응답은 유실됐다.
    server.reject_at = None
    sample[1][1]["comment"] = "바뀐 설명"
    with pytest.raises(SystemExit):
        invoke(sample, "--upload")
    assert len(server.sent) == 1


def test_missing_shared_ledger_never_posts(sample, monkeypatch):
    monkeypatch.delenv("RAG_SCORE_LEDGER_DSN", raising=False)
    server = Server()
    monkeypatch.setattr(cli, "langfuse_post", lambda: server)
    with pytest.raises(SystemExit):
        invoke(sample, "--upload")
    assert not server.sent


@pytest.fixture
def missing_accepted(sample, shared_ledger, monkeypatch):
    server = Server()
    monkeypatch.setattr(cli, "langfuse_post", lambda: server)
    invoke(sample, "--upload")
    original = server.sent[0].copy()
    server.rows.pop(0)
    return server, original


def confirmation(sample, original, capsys):
    invoke(sample, "--recover-score-id", original["id"])
    return capsys.readouterr().out.split("--queue-drained ")[-1].strip()


def test_recover_accepted_via_cli(sample, missing_accepted, capsys):
    server, original = missing_accepted
    invoke(sample, "--check")
    output = capsys.readouterr().out
    assert "서버 일치 11개, 미등록 1개" in output
    assert all(original[k] in output for k in ("id", "traceId", "name"))
    invoke(sample, "--upload")
    assert len(server.sent) == 12
    token = confirmation(sample, original, capsys)
    args = ("--recover-score-id", original["id"], "--queue-drained", token)
    invoke(sample, *args)
    assert "복구 접수" in capsys.readouterr().out
    assert len(server.sent) == 13 and server.sent[-1] == original
    assert original["value"] == 0.0
    assert original["timestamp"] == "2026-11-25T23:59:59.123456+00:00"
    invoke(sample, *args)
    assert "반영 확인" in capsys.readouterr().out
    invoke(sample, "--check")
    assert "서버 일치 12개, 미등록 0개" in capsys.readouterr().out
    assert len(server.sent) == 13


@pytest.mark.parametrize(
    "problem",
    [
        "unknown_id",
        "other_project",
        "missing_root",
        "other_variant",
        "changed_input",
        "same_name_other_id",
        "same_id_other_trace",
        "id_read_failed",
        "inconsistent_read",
        "id_conflicting_value",
        "wrong_server_run",
        "unreadable_subject",
        "incomplete_pages",
        "unaccepted",
    ],
)
def test_recovery_preflight_never_posts(
    sample, missing_accepted, capsys, monkeypatch, problem
):
    server, original = missing_accepted
    token = confirmation(sample, original, capsys)
    score_id = original["id"]
    row = {**original, "subject": {"kind": "trace", "id": original["traceId"]}}
    if problem == "unknown_id":
        score_id = "unknown"
    elif problem == "other_project":
        server.project += "-other"
    elif problem == "missing_root":
        server.missing_root = original["traceId"]
    elif problem == "other_variant":
        server.variant = "C"
    elif problem == "changed_input":
        sample[1][0]["comment"] += " 수정"
    elif problem == "same_name_other_id":
        server.rows.append({**row, "id": "other"})
    elif problem == "same_id_other_trace":
        server.rows.append({**row, "subject": {"kind": "trace", "id": "other"}})
    elif problem == "unreadable_subject":
        server.rows.append({**row, "subject": {"id": original["traceId"]}})
    elif problem == "unaccepted":
        import psycopg

        with psycopg.connect(os.environ["TEST_SCORE_LEDGER_DSN"]) as db:
            db.execute(
                "UPDATE rag_extra_score_ledger SET accepted=FALSE WHERE project=%s AND score_id=%s",
                (server.project, score_id),
            )
    else:
        request = server.request
        if problem == "id_conflicting_value":
            server.rows.append(row)

        def inconsistent(method, path, payload=None):
            if problem == "wrong_server_run" and "observations" in path:
                page = request(method, path, payload)
                page["data"][0]["metadata"]["run_id"] = "other"
                return page
            if "id" in parse_qs(urlsplit(path).query):
                if problem == "incomplete_pages":
                    return {"data": [], "meta": {"cursor": "same-page"}}
                if problem == "id_read_failed":
                    return None
                return {"data": [{**row, "value": 0.7}], "meta": {}}
            return request(method, path, payload)

        monkeypatch.setattr(server, "request", inconsistent)
    with pytest.raises(SystemExit):
        invoke(sample, "--recover-score-id", score_id, "--queue-drained", token)
    assert len(server.sent) == 12


def test_uncertain_recovery_requires_new_queue_confirmation(
    sample, missing_accepted, capsys, monkeypatch
):
    server, original = missing_accepted
    token = confirmation(sample, original, capsys)
    args = ("--recover-score-id", original["id"], "--queue-drained")
    request = server.request

    def lost(method, path, payload=None):
        if method == "POST":
            server.sent.append(payload[0])
            raise TimeoutError
        return request(method, path, payload)

    monkeypatch.setattr(server, "request", lost)
    with pytest.raises(SystemExit) as error:
        invoke(sample, *args, token)
    assert error.value.code == 2 and "접수 미확인" in capsys.readouterr().err
    with pytest.raises(SystemExit) as error:
        invoke(sample, *args, token)
    assert error.value.code == 2 and "확인 번호" in capsys.readouterr().err
    invoke(sample, "--upload")
    assert len(server.sent) == 13
    fresh = confirmation(sample, original, capsys)
    assert fresh != token
    monkeypatch.setattr(server, "request", request)
    invoke(sample, *args, fresh)
    assert server.sent[12:] == [original, original]


def test_concurrent_recoveries_consume_confirmation_once(
    sample, missing_accepted, capsys, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    server, original = missing_accepted
    token = confirmation(sample, original, capsys)
    args = [
        "--archive",
        str(sample[0]),
        "--preview",
        str(sample[0] / "preview.json"),
        "--expected-traces",
        "4",
        "--recover-score-id",
        original["id"],
        "--queue-drained",
        token,
    ]
    entered, release = Event(), Event()
    request = server.request

    def delayed(method, path, payload=None):
        if method == "POST":
            entered.set()
            assert release.wait(5)
            server.sent.append(payload[0])
            return True
        return request(method, path, payload)

    monkeypatch.setattr(server, "request", delayed)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(cli.main, args)
        assert entered.wait(5)
        second = pool.submit(cli.main, args)
        release.set()
        first.result(timeout=10)
        with pytest.raises(SystemExit) as error:
            second.result(timeout=10)
        assert error.value.code == 2 and "확인 번호" in capsys.readouterr().err
    assert server.sent[12:] == [original]


def test_queue_confirmation_requires_recovery(sample, monkeypatch):
    monkeypatch.setattr(
        cli, "langfuse_post", lambda: pytest.fail("잘못된 옵션으로 서버 접근")
    )
    with pytest.raises(SystemExit):
        invoke(sample, "--upload", "--queue-drained", "unused")


def test_definitive_rejection_is_visible_in_recovery_status(
    sample, missing_accepted, capsys, monkeypatch
):
    server, score = missing_accepted
    token = confirmation(sample, score, capsys)
    request = server.request

    def reject(method, path, payload=None):
        return False if method == "POST" else request(method, path, payload)

    monkeypatch.setattr(server, "request", reject)
    with pytest.raises(SystemExit):
        invoke(sample, "--recover-score-id", score["id"], "--queue-drained", token)
    assert "거절" in capsys.readouterr().err
    invoke(sample, "--recover-score-id", score["id"])
    assert "(거절)" in capsys.readouterr().out


def test_empty_csv_variant_and_absent_server_variant(sample, missing_accepted, capsys):
    path = sample[0] / "runs.csv"
    with path.open() as file:
        runs = list(csv.DictReader(file))
    table(sample[0], path.name, [dict(run, variant="") for run in runs])
    server, score = missing_accepted
    assert confirmation(sample, score, capsys)
    assert len(server.sent) == 12
