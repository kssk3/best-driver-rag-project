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
