"""팀이 저장한 숫자 점수를 기존 Langfuse 실행과 대조한다."""

import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Literal
from urllib.parse import urlencode

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, field_validator

from src.evaluation.answer_metrics import _archive_rows
from src.observability.tracing import (
    SEARCH_VARIANTS,
    _identifier,
    _utc,
    trace_id_for_run,
)

PRECISION = "context_precision_id_at_5"
RECALL = "context_recall_id_at_5"
RELEVANCY = "answer_relevancy"


class SavedScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    traceId: str = Field(pattern=r"^[0-9a-f]{32}$")
    name: Literal[
        "answer_relevancy", "context_precision_id_at_5", "context_recall_id_at_5"
    ]
    value: StrictFloat = Field(ge=0, le=1, allow_inf_nan=False)
    timestamp: str
    comment: str = ""
    dataType: Literal["NUMERIC"] = "NUMERIC"
    environment: str | None = None

    @field_validator("timestamp")
    @classmethod
    def check_timestamp(cls, value: str) -> str:
        return _utc(value).isoformat()


def prepare_scores(preview: Path, archive: Path, expected_traces: int):
    rows = json.loads(preview.read_text(encoding="utf-8-sig"))
    if not isinstance(rows, list) or not rows:
        raise ValueError("점수 JSON에는 비어 있지 않은 행 배열이 필요합니다.")
    groups: dict[str, dict[str, SavedScore]] = defaultdict(dict)
    for row in rows:
        score = SavedScore.model_validate(row)
        group = groups[score.traceId]
        if score.name in group:
            raise ValueError("동일 trace에 같은 지표가 두 번 있습니다.")
        group[score.name] = score
    if len(groups) != expected_traces:
        raise ValueError("예상 실행 수와 JSON의 고유 trace 수가 다릅니다.")

    with _archive_rows(
        archive / "cases.csv", {"dataset_id", "case_id", "allowed_chunk_ids_json"}
    ) as reader:
        cases = {}
        for case_row in reader:
            key = (case_row["dataset_id"], case_row["case_id"])
            if key in cases:
                raise ValueError("중복 문항입니다.")
            cases[key] = case_row
    with _archive_rows(
        archive / "runs.csv",
        {
            "run_id",
            "dataset_id",
            "case_id",
            "run_kind",
            "candidate_count",
            "top_k",
            "status",
            "answer",
            "retrieval_status",
        },
    ) as reader:
        runs = {}
        for run_row in reader:
            if not run_row["run_id"]:
                continue
            trace = run_row.get("trace_id") or trace_id_for_run(run_row["run_id"])
            if trace in groups:
                if trace in runs:
                    raise ValueError("trace가 여러 실행에 연결됩니다.")
                runs[trace] = run_row
    if groups.keys() != runs.keys():
        raise ValueError("원본 runs.csv에서 모든 trace를 찾을 수 없습니다.")

    candidates: dict[str, dict[int, str]] = defaultdict(dict)
    selected = {r["run_id"]: r for r in runs.values()}
    if len(selected) != len(runs):
        raise ValueError("원본 run_id가 중복됩니다.")
    with _archive_rows(
        archive / "candidates.csv",
        {"run_id", "dataset_id", "case_id", "rank", "chunk_id"},
    ) as reader:
        for row in reader:
            run = selected.get(row["run_id"])
            if run is None:
                continue
            rank = int(row["rank"])
            ranked = candidates[row["run_id"]]
            if (
                any(row[k] != run[k] for k in ("dataset_id", "case_id"))
                or rank in ranked
                or not row["chunk_id"].strip()
            ):
                raise ValueError("검색 후보의 문항·순위·청크 ID를 확인하세요.")
            ranked[rank] = row["chunk_id"]

    payloads = []
    for trace, group in groups.items():
        run = runs[trace]
        case = cases.get((run["dataset_id"], run["case_id"]))
        if (
            case is None
            or run["run_kind"] not in {"rag", "demo"}
            or not case["dataset_id"]
            or not case["case_id"]
        ):
            raise ValueError("검색 실행과 평가 문항을 확인하세요.")
        ranked = candidates[run["run_id"]]
        if run["retrieval_status"] != "ok" or int(run["top_k"]) < 5:
            raise ValueError("상위 5개를 요청한 정상 검색 기록이 필요합니다.")
        if len(ranked) != int(run["candidate_count"]) or sorted(ranked) != list(
            range(1, len(ranked) + 1)
        ):
            raise ValueError("검색 후보 순위가 원본 건수와 다릅니다.")
        top = {chunk for rank, chunk in ranked.items() if rank <= 5}
        ids = json.loads(case["allowed_chunk_ids_json"])
        if not isinstance(ids, list) or not all(
            isinstance(i, str) and i.strip() for i in ids
        ):
            raise ValueError("잘못된 허용 청크 ID 목록입니다.")
        allowed = set(ids)
        hits = len(top & allowed)
        expected = {}
        if allowed:
            expected[RECALL] = hits / len(allowed)
            if top:
                expected[PRECISION] = hits / len(top)
        if group.keys() != expected.keys() | {RELEVANCY}:
            raise ValueError("지표가 누락됐거나 미정의 지표에 숫자가 있습니다.")
        for metric, value in expected.items():
            if not math.isclose(group[metric].value, value, abs_tol=1e-6):
                raise ValueError(
                    f"{trace} {metric}: 원본 청크 ID로 계산한 값과 다릅니다."
                )
        if (
            run["status"]
            not in {"answered", "needs_clarification", "insufficient_evidence"}
            or not run["answer"].strip()
        ):
            raise ValueError("관련성을 평가한 실제 답변 또는 보류 안내가 필요합니다.")
        if not group[RELEVANCY].comment.strip():
            raise ValueError(
                "관련성의 산출 방식과 보류 시 평가 대상을 comment에 적으세요."
            )
        for score in group.values():
            if score.environment not in (None, run["run_kind"]):
                raise ValueError("실행 환경이 다릅니다.")
            payload = {
                **score.model_dump(),
                "environment": run["run_kind"],
                "id": _identifier("extra-score", trace, score.name),
                "run_id": run["run_id"],
                "variant": run.get("variant"),
            }
            # 비교 화면이 점수를 같은 평가끼리 묶도록 원본 runs.csv의 평가 세트·리라이트 여부를 남긴다.
            # 이 지표들은 Faithfulness의 comparison_eligible과 따로 평가하므로 그 값은 넣지 않는다.
            grouping = {
                key: run[key]
                for key in ("dataset_id", "rewrite_enabled")
                if run.get(key) not in (None, "")
            }
            if grouping:
                payload["metadata"] = grouping
            if score.name == RELEVANCY and run["status"] != "answered":
                payload["comment"] = (
                    f"보류 안내 문구 평가 ({run['status']}). {score.comment}"
                )
            payloads.append(payload)
    return payloads


def server_rows(client, path, **params):
    rows = []
    seen = set()
    while True:
        page = client.request("GET", path + "?" + urlencode(params))
        if (
            not isinstance(page, dict)
            or not isinstance(page.get("data"), list)
            or not isinstance(page.get("meta"), dict)
        ):
            raise ValueError("Langfuse 조회 결과를 확인할 수 없습니다.")
        if not all(isinstance(row, dict) for row in page["data"]):
            raise ValueError("Langfuse 조회 행을 확인할 수 없습니다.")
        rows.extend(page["data"])
        cursor = page["meta"].get("cursor")
        if cursor is None:
            return rows
        if not isinstance(cursor, str) or not cursor or cursor in seen:
            raise ValueError("Langfuse 조회 커서를 확인할 수 없습니다.")
        seen.add(cursor)
        params["cursor"] = cursor


def same_score(row, score):
    subject = row.get("subject")
    return (
        isinstance(subject, dict)
        and subject.get("kind") == "trace"
        and subject.get("id") == score["traceId"]
        and row.get("id") == score["id"]
        and row.get("name") == score["name"]
        and row.get("dataType") == "NUMERIC"
        and type(row.get("value")) in (float, int)
        and row["value"] == score["value"]
        and (row.get("comment") or "") == score["comment"]
        and row.get("environment") == score["environment"]
        and _utc(row["timestamp"]).isoformat(timespec="milliseconds")
        == _utc(score["timestamp"]).isoformat(timespec="milliseconds")
    )


def missing_scores(client, payloads, *, recovery=False):
    """전체 실행에서 충돌과 누락을 먼저 조회한다."""
    pending = []
    by_trace = defaultdict(list)
    for score in payloads:
        by_trace[score["traceId"]].append(score)
    for trace, group in by_trace.items():
        roots = server_rows(
            client,
            "/api/public/v2/observations",
            traceId=trace,
            isRootObservation="true",
            fields="core,basic,metadata",
            limit=2,
        )
        if (
            len(roots) != 1
            or roots[0].get("isRootObservation") is not True
            or roots[0].get("traceId") != trace
            or roots[0].get("environment") != group[0]["environment"]
        ):
            raise ValueError(
                f"{trace}: 같은 환경의 고유 실행 루트를 확인할 수 없습니다."
            )
        metadata = roots[0].get("metadata") or {}
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        server_variant = metadata.get("variant") if isinstance(metadata, dict) else None
        local_variant = group[0]["variant"]
        if recovery and (local_variant or None) != (server_variant or None):
            raise ValueError(f"{trace}: 복구할 실행의 검색 방식을 확인할 수 없습니다.")
        if (
            local_variant in SEARCH_VARIANTS
            and server_variant in SEARCH_VARIANTS
            and local_variant != server_variant
        ):
            raise ValueError(f"{trace}: 원본과 서버의 검색 방식이 다릅니다.")
        run_id = group[0]["run_id"]
        server_run = metadata.get("run_id") if isinstance(metadata, dict) else None
        if (
            server_run is not None or trace_id_for_run(run_id) != trace
        ) and server_run != run_id:
            raise ValueError(
                f"{trace}: 원본 run_id와 서버 루트의 연결을 확인할 수 없습니다."
            )
        rows = server_rows(
            client, "/api/public/v3/scores", traceId=trace, fields="subject,details"
        )
        if any(
            not isinstance(r.get("subject"), dict)
            or not r["subject"].get("id")
            or not r["subject"].get("kind")
            or not r.get("name")
            for r in rows
        ):
            raise ValueError("Langfuse 점수의 귀속을 확인할 수 없습니다.")
        for score in group:
            matches = [
                r
                for r in rows
                if r["subject"].get("id") == trace
                and r["subject"].get("kind") == "trace"
                and r["name"] == score["name"]
            ]
            if not matches:
                pending.append(score)
                continue
            if len(matches) != 1 or not same_score(matches[0], score):
                raise ValueError(f"{trace} {score['name']}: 기존 점수와 충돌합니다.")
    return pending
