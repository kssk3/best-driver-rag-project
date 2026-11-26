import csv
import json
from urllib.parse import parse_qs, urlsplit

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
                else [dict(isRootObservation=True, traceId=trace, environment="rag")]
            )
        else:
            data = [r for r in self.rows if r["subject"]["id"] == trace]
        return {"data": data, "meta": {"cursor": None}}


def test_four_traces_and_retry(sample, monkeypatch):
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
def test_preflight_checks_last_trace_before_first_post(sample, monkeypatch, problem):
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


def test_undefined_id_metrics_keep_relevancy(sample, monkeypatch):
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


def test_explicit_trace_mapping_requires_same_server_run(sample, monkeypatch):
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
