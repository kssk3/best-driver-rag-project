import csv
import json
from pathlib import Path

import httpx2
import pytest

from scripts.score_answers import main

ARCHIVE = Path("results/team-a/2026-11-25T064832Z/evaluation.json")
CASES = Path("eval/snapshots/2026-11-25T064832Z/cases.csv")
CASE_ID = "p04-colors-trick"
PRIVATE = "private-fixture-marker"


def mock_completion(content):
    return httpx2.Response(
        200,
        json={
            "id": "mock",
            "object": "chat.completion",
            "model": "gpt-6-luna",
            "created": 1,
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": json.dumps(content)},
                }
            ],
        },
    )


@pytest.mark.parametrize(
    ("scenario", "status", "score", "reason", "expected_calls"),
    [
        ("setup_missing_key", "scorer_error", "", "judge_setup_error", 0),
        ("mixed", "scored", "0.5", "", 2),
        ("empty", "no_score", "", "non_finite_value", 1),
        ("supported", "scored", "1.0", "", 2),
        ("unsupported", "scored", "0.0", "", 2),
        ("statements_http", "scorer_error", "", "judge_statements_http_429", 1),
        ("verdicts_schema", "scorer_error", "", "judge_verdicts_invalid_response", 2),
        ("statements_redirect", "scorer_error", "", "judge_statements_http_307", 1),
        ("verdicts_redirect", "scorer_error", "", "judge_verdicts_http_308", 2),
        ("statements_timeout", "scorer_error", "", "judge_statements_timeout", 1),
        ("statements_connect", "scorer_error", "", "judge_statements_connection", 1),
    ],
)
def test_judge_http_responses(
    scenario,
    status,
    score,
    reason,
    expected_calls,
    tmp_path,
    monkeypatch,
    caplog,
    capsys,
):
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://offline.invalid/v1")
    monkeypatch.setenv("NO_PROXY", "*")
    if scenario == "setup_missing_key":
        monkeypatch.delenv("OPENAI_API_KEY")
        monkeypatch.delenv("OPENAI_ADMIN_KEY", raising=False)
    calls = []

    async def handle(self, request):
        assert request.url.host == "offline.invalid"
        calls.append(request.url.path)
        if request.url.path == "/redirected":
            return httpx2.Response(429, json={"error": {"message": PRIVATE}})
        assert json.loads(request.content)["model"] == "gpt-6-luna"
        if scenario == "statements_redirect":
            return httpx2.Response(307, headers={"Location": "/redirected"})
        if scenario == "verdicts_redirect" and len(calls) == 2:
            return httpx2.Response(308, headers={"Location": "/redirected"})
        if scenario == "statements_timeout":
            raise httpx2.ReadTimeout(PRIVATE, request=request)
        if scenario == "statements_http":
            return httpx2.Response(429, json={"error": {"message": PRIVATE}})
        if scenario == "statements_connect":
            raise httpx2.ConnectError(PRIVATE, request=request)
        if len(calls) == 1:
            claims = {"mixed": ["one claim", "another claim"], "empty": []}.get(
                scenario, ["one claim"]
            )
            return mock_completion({"statements": claims})
        if scenario == "mixed":
            return mock_completion(
                {
                    "statements": [
                        {
                            "statement": "one claim",
                            "verdict": 1,
                            "reason": "fixed evidence",
                        },
                        {
                            "statement": "reworded claim",
                            "verdict": 0,
                            "reason": "missing evidence",
                        },
                    ]
                }
            )
        if scenario == "verdicts_schema":
            return mock_completion({"statements": PRIVATE})
        return mock_completion(
            {
                "statements": [
                    {
                        "statement": "one claim",
                        "verdict": int(scenario == "supported"),
                        "reason": "mock",
                    }
                ]
            }
        )

    monkeypatch.setattr(httpx2.AsyncHTTPTransport, "handle_async_request", handle)
    args = [
        "--evaluation",
        str(ARCHIVE),
        "--cases-csv",
        str(CASES),
        "--output-dir",
        str(tmp_path / "out"),
        "--case-id",
        CASE_ID,
        "--judge",
    ]
    if status == "scored":
        main(args)
    else:
        with pytest.raises(SystemExit) as error:
            main(args)
        assert error.value.code == 1
    assert calls == ["/v1/chat/completions"] * expected_calls
    path = tmp_path / "out/scores.csv"
    with path.open(newline="", encoding="utf-8") as f:
        (row,) = csv.DictReader(f)
    (attempt,) = [a for a in json.loads(ARCHIVE.read_text()) if a["case_id"] == CASE_ID]
    assert row["judge_model"] == "gpt-6-luna"
    assert (row["run_id"], row["case_id"]) == (attempt["run_id"], CASE_ID)
    assert (row["status"], row["score"], row["reason"]) == (status, score, reason)
    detail = json.loads((path.parent / "judgment-details.jsonl").read_text())
    assert detail["run_id"] == row["run_id"]
    assert detail["evaluation_id"] == row["evaluation_id"]
    assert detail["model_input_chunk_ids"] == attempt["record"]["model_input_chunk_ids"]
    if scenario == "mixed":
        assert detail["statements"] == ["one claim", "another claim"]
        assert detail["verdicts"][1] == {
            "statement": "reworded claim",
            "verdict": 0,
            "reason": "missing evidence",
        }
    elif scenario == "empty":
        assert detail["statements"] == [] and detail["verdicts"] is None
    elif status == "scorer_error":
        assert detail["statements"] == (
            ["one claim"] if scenario.startswith("verdicts") else None
        )
        assert detail["verdicts"] is None
    elif status == "scored":
        assert detail["verdicts"] == [
            {"statement": "one claim", "verdict": int(float(score)), "reason": "mock"}
        ]
    assert PRIVATE not in json.dumps(detail)
    captured = capsys.readouterr()
    assert PRIVATE not in path.read_text() + captured.out + captured.err + caplog.text
