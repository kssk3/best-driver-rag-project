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
    ("scenario", "status", "score", "reason"),
    [
        ("supported", "scored", "1.0", ""),
        ("unsupported", "scored", "0.0", ""),
        ("statements_http", "scorer_error", "", "judge_statements_http_429"),
        ("verdicts_schema", "scorer_error", "", "judge_verdicts_invalid_response"),
        ("statements_connect", "scorer_error", "", "judge_statements_connection"),
    ],
)
def test_judge_http_responses(
    scenario, status, score, reason, tmp_path, monkeypatch, caplog, capsys
):
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://offline.invalid/v1")
    monkeypatch.setenv("NO_PROXY", "*")
    calls = []

    async def handle(self, request):
        assert request.url.host == "offline.invalid"
        assert json.loads(request.content)["model"] == "gpt-6-luna"
        calls.append(request.url.path)
        if scenario == "statements_http":
            return httpx2.Response(429, json={"error": {"message": PRIVATE}})
        if scenario == "statements_connect":
            raise httpx2.ConnectError(PRIVATE, request=request)
        if len(calls) == 1:
            return mock_completion({"statements": ["one claim"]})
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
        assert len(calls) == 2
    else:
        with pytest.raises(SystemExit) as error:
            main(args)
        assert error.value.code == 1
    assert len(calls) == (1 if scenario.startswith("statements_") else 2)
    assert set(calls) == {"/v1/chat/completions"}
    path = tmp_path / "out/scores.csv"
    with path.open(newline="", encoding="utf-8") as f:
        (row,) = csv.DictReader(f)
    (attempt,) = [a for a in json.loads(ARCHIVE.read_text()) if a["case_id"] == CASE_ID]
    assert row["judge_model"] == "gpt-6-luna"
    assert (row["run_id"], row["case_id"]) == (attempt["run_id"], CASE_ID)
    assert (row["status"], row["score"], row["reason"]) == (status, score, reason)
    captured = capsys.readouterr()
    assert PRIVATE not in path.read_text() + captured.out + captured.err + caplog.text
