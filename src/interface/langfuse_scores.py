"""비교 패널: Langfuse에 올라간 RAGAS 4대 지표 점수를 실행 방식(variant)별로 집계한다.

점수의 subject.id(trace ID)를 실행 루트 관측의 traceId와 잇고, 루트의 metadata에서 variant,
dataset_id, rewrite_enabled, comparison_eligible을 읽는다. 옛 트레이스에는 이 값이 없어서 루트의 run_id로
저장소 results/*/runs.csv, scores.csv를 맞춰 보충한다. 같은 평가 세트라도 리라이트 OFF와 ON은 따로 묶고,
comparison_eligible이 true인 점수만 평균에 넣는다. 방식(A/B/C)을 모르거나, 평가 세트·리라이트·비교 자격을
확인할 수 없는 점수는 평균에서 빼고 따로 센다.
이 서버는 v4 events_only 모드라 구형 /scores 조회는 404이고 v3 scores와 v2 observations만 된다.
"""

import base64
import csv
import json
import os
from dataclasses import dataclass, field
from http.client import HTTPException, HTTPSConnection
from math import isfinite
from pathlib import Path
from statistics import mean
from urllib.parse import urlencode, urlsplit

from src.interface.comparison import VARIANTS, VariantSummary

SCORES_PATH = "/api/public/v3/scores"
OBSERVATIONS_PATH = "/api/public/v2/observations"
MAX_PAGES = 20
RESULTS_DIR = Path(__file__).resolve().parents[2] / "results"
# (Langfuse 점수 이름, 화면 이름, 영문 이름). 근거 정밀도·재현율은 정답 근거 ID 기준 상위 5개 값이다.
METRICS = (
    ("faithfulness", "근거 충실도", "Faithfulness"),
    ("answer_relevancy", "답변 관련성", "Answer Relevancy"),
    ("context_precision_id_at_5", "근거 정밀도", "Context Precision@5"),
    ("context_recall_id_at_5", "근거 재현율", "Context Recall@5"),
)
METRIC_NAMES = tuple(name for name, _, _ in METRICS)


class LangfuseReadError(RuntimeError):
    """조회에 실패했다. 코드만 담고 주소·키·응답 내용은 넣지 않는다."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class DatasetGroup:
    dataset_id: str
    latest: str  # 가장 최근 실행 시각(UTC ISO 문자열)
    # 지표 이름 → 방식(A/B/C)별 건수·평균
    metrics: dict[str, list[VariantSummary]]
    rewrite_enabled: bool = False  # 같은 데이터셋이어도 리라이트 OFF와 ON은 따로 묶는다


def _zero() -> dict[str, int]:
    return {m: 0 for m in METRIC_NAMES}


@dataclass(frozen=True)
class LangfuseScores:
    groups: list[DatasetGroup]
    unlinked: dict[str, int]  # 지표별로 방식(A/B/C)을 알 수 없어 평균에서 뺀 점수 건수
    # 평가 세트·리라이트 여부·비교 자격을 확인할 수 없어 뺀 점수. 섞이면 틀린 평균이 되므로 따로 센다.
    unverified: dict[str, int] = field(default_factory=_zero)
    ineligible: dict[str, int] = field(
        default_factory=_zero
    )  # 비교 대상이 아니라고 기록된 점수


def _flag(value) -> bool | None:
    """true/false(불리언 또는 문자열)를 읽는다. 그 밖의 값은 알 수 없음(None)이다."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    return None


def load_run_index(results_dir: Path = RESULTS_DIR) -> dict[str, dict]:
    """저장소 results/*/runs.csv와 scores.csv에서 run_id → 평가 세트·리라이트·비교 자격을 읽는다.

    트레이스 메타데이터에 이 값이 없는 옛 점수를 run_id로 이어 확인하는 용도다.
    비교 자격(comparison_eligible)은 Faithfulness 점수의 속성이라 scores.csv에만 있고, 한 실행의 여러 행 중
    하나라도 false이면 false다. 하위 폴더(results/<실험>/abc/ 등)까지 찾는다.
    """
    runs: dict[str, dict] = {}

    def read(name: str):
        for path in sorted(results_dir.rglob(name)):
            if "local" in path.relative_to(results_dir).parts:
                continue  # results/local은 개인 실험 기록이라 쓰지 않는다.
            try:
                with path.open(encoding="utf-8-sig", newline="") as file:
                    yield from csv.DictReader(file)
            except OSError:
                continue

    for row in read("runs.csv"):
        runs.setdefault(
            row.get("run_id", ""),
            {
                "dataset_id": row.get("dataset_id") or None,
                "rewrite_enabled": _flag(row.get("rewrite_enabled")),
                "eligible": None,
            },
        )
    for row in read("scores.csv"):
        info = runs.setdefault(
            row.get("run_id", ""),
            {
                "dataset_id": row.get("dataset_id") or None,
                "rewrite_enabled": _flag(row.get("rewrite_enabled")),
                "eligible": None,
            },
        )
        eligible = _flag(row.get("comparison_eligible"))
        if eligible is not None and row.get("metric", "faithfulness") == "faithfulness":
            info["eligible"] = (
                eligible if info["eligible"] is None else info["eligible"] and eligible
            )
    return runs


def _latest_per_trace_and_metric(scores: list[dict]) -> list[dict]:
    """같은 실행(trace)을 여러 번 채점하면 지표마다 가장 최근 점수 하나만 남긴다(표본이 겹쳐 가중되지 않게)."""
    best: dict[tuple[str, str], tuple[str, int, dict]] = {}
    others: list[dict] = []
    for index, score in enumerate(scores):
        subject = score.get("subject") or {}
        if score.get("name") not in METRIC_NAMES or subject.get("kind") != "trace":
            others.append(score)
            continue
        key = (str(subject.get("id")), score["name"])
        stamp = str(score.get("timestamp") or score.get("createdAt") or "")
        if key not in best or (stamp, index) > best[key][:2]:
            best[key] = (stamp, index, score)
    return others + [item[2] for item in best.values()]


def _resolve(
    root: dict, runs: dict[str, dict], meta: dict, metric: str
) -> tuple[str | None, bool | None, bool | None]:
    """(평가 세트, 리라이트 여부, 비교 자격). 점수 자체의 메타데이터를 먼저, 없는 값은 루트 메타데이터,
    그다음 루트의 run_id로 맞춘 로컬 기록으로 채운다."""
    info = runs.get(str(root.get("run_id"))) or {}
    dataset = meta.get("dataset_id") or root.get("dataset_id") or info.get("dataset_id")
    rewrite = _flag(meta.get("rewrite_enabled"))
    if rewrite is None:
        rewrite = _flag(root.get("rewrite_enabled"))
    eligible = _flag(meta.get("comparison_eligible"))
    if eligible is None:
        eligible = _flag(root.get("comparison_eligible"))
    if metric != "faithfulness":
        # 비교 자격은 Faithfulness 점수에만 붙는다(근거 없는 답변은 그 점수만 대상이 아니다).
        # 다른 지표는 평가 세트와 리라이트 여부가 확인되면 포함한다.
        eligible = True
    return (
        dataset,
        info.get("rewrite_enabled") if rewrite is None else rewrite,
        info.get("eligible") if eligible is None else eligible,
    )


def _score_metadata(score: dict) -> dict:
    """점수 응답의 비교용 메타데이터. v3 응답에서 어느 필드에 오는지 확인하지 못해 최상위와 details 안을 모두 읽는다."""
    details = score.get("details")
    inner = _metadata(details.get("metadata")) if isinstance(details, dict) else {}
    return inner | _metadata(score.get("metadata"))


def build_scores(
    scores: list[dict], roots: dict[str, dict], runs: dict[str, dict] | None = None
) -> LangfuseScores:
    """순수 집계. roots는 traceId → {"variant", "dataset_id", "run_id", "rewrite_enabled",
    "comparison_eligible", "start"}, runs는 run_id → load_run_index() 항목이다."""
    runs = runs or {}
    values: dict[tuple[str, bool], dict[str, dict[str, list[float]]]] = {}
    latest: dict[tuple[str, bool], str] = {}
    unlinked, unverified, ineligible = _zero(), _zero(), _zero()
    for score in _latest_per_trace_and_metric(scores):
        name = score.get("name")
        if name not in METRIC_NAMES:
            continue  # 우리가 보여 주는 지표가 아니다(Hit@k 등).
        subject = score.get("subject") or {}
        root = roots.get(str(subject.get("id")))
        if subject.get("kind") != "trace":
            root = None
        if root is not None and root.get("conflict"):
            unverified[name] += (
                1  # 한 trace에 루트가 둘 이상이라 어느 쪽 기준인지 모른다.
            )
            continue
        value = score.get("value")
        if (
            root is None
            or root.get("variant") not in VARIANTS
            or not isinstance(value, int | float)
            or not isfinite(value)
        ):
            unlinked[name] += 1
            continue
        dataset, rewrite, eligible = _resolve(root, runs, _score_metadata(score), name)
        if dataset is None or rewrite is None or eligible is None:
            unverified[name] += 1
            continue
        if not eligible:
            ineligible[name] += 1
            continue
        key = (dataset, rewrite)
        by_metric = values.setdefault(
            key, {m: {v: [] for v in VARIANTS} for m in METRIC_NAMES}
        )
        by_metric[name][root["variant"]].append(float(value))
        latest[key] = max(latest.get(key, ""), root.get("start") or "")
    groups = [
        DatasetGroup(
            key[0],
            latest[key],
            {
                metric: [
                    VariantSummary(variant, len(found), mean(found) if found else None)
                    for variant, found in by_variant.items()
                ]
                for metric, by_variant in by_metric.items()
            },
            key[1],
        )
        for key, by_metric in values.items()
    ]
    groups.sort(key=lambda group: group.latest, reverse=True)
    return LangfuseScores(groups, unlinked, unverified, ineligible)


def _connect() -> tuple[HTTPSConnection, str, str]:
    base = os.environ.get("LANGFUSE_BASE_URL", "").strip()
    public = os.environ.get("LANGFUSE_PUBLIC_KEY", "").strip()
    secret = os.environ.get("LANGFUSE_SECRET_KEY", "").strip()
    if not (base and public and secret):
        raise LangfuseReadError("not_configured")
    try:
        url = urlsplit(base)
        hostname, port = url.hostname, url.port
    except ValueError:
        raise LangfuseReadError("not_configured") from None
    if (
        url.scheme != "https"
        or not hostname
        or url.username is not None
        or url.password is not None
        or url.query
        or url.fragment
    ):
        raise LangfuseReadError("not_configured")
    token = base64.b64encode(f"{public}:{secret}".encode()).decode("ascii")
    return HTTPSConnection(hostname, port, timeout=15), url.path.rstrip("/"), token


def _get(path: str, params: dict) -> dict:
    connection, prefix, token = _connect()
    try:
        connection.request(
            "GET",
            f"{prefix}{path}?{urlencode(params)}",
            headers={"Authorization": "Basic " + token},
        )
        response = connection.getresponse()
        body = response.read()
        if response.status != 200:
            raise LangfuseReadError(f"http_{response.status}")
        data = json.loads(body)
    except LangfuseReadError:
        raise
    except TimeoutError:
        # 서버는 열려 있지만 응답이 느린 경우(서버가 바쁠 때)다. 연결 실패와 구별한다.
        raise LangfuseReadError("timeout") from None
    except HTTPException:
        # 응답 본문이 중간에 끊기는 경우(IncompleteRead 등)다.
        raise LangfuseReadError("bad_response") from None
    except (OSError, ValueError):
        raise LangfuseReadError("unreachable") from None
    finally:
        connection.close()
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        raise LangfuseReadError("bad_response")
    return data


def _pages(path: str, params: dict) -> list[dict]:
    rows: list[dict] = []
    cursor = None
    for _ in range(MAX_PAGES):
        data = _get(path, params | ({"cursor": cursor} if cursor else {}))
        rows.extend(item for item in data["data"] if isinstance(item, dict))
        cursor = (data.get("meta") or {}).get("cursor")
        if not cursor:
            return rows
    # 상한에서 잘린 부분 데이터로 평균을 내면 틀린 값이 되므로 오류로 알린다.
    raise LangfuseReadError("too_many_pages")


def _metadata(raw) -> dict:
    """루트 메타데이터는 dict이거나 JSON 문자열일 수 있다. 읽을 수 없으면 빈 dict(미연결로 센다)."""
    if isinstance(raw, str) and raw.lstrip().startswith("{"):
        try:
            raw = json.loads(raw)
        except ValueError:
            return {}
    return raw if isinstance(raw, dict) else {}


def load_langfuse_scores() -> LangfuseScores:
    scores = _pages(
        SCORES_PATH, {"environment": "rag", "fields": "subject,details", "limit": 100}
    )
    observations = _pages(
        OBSERVATIONS_PATH,
        {"fields": "core,basic,metadata", "limit": 1000, "isRootObservation": "true"},
    )
    roots = {}
    for item in observations:
        # 기존 업로더(extra_scores.py)와 같이 루트인 행만, traceId가 있는 것만 쓴다.
        if item.get("isRootObservation") is True and item.get("traceId"):
            if item["traceId"] in roots:
                roots[item["traceId"]] = {"conflict": True}
                continue
            metadata = _metadata(item.get("metadata"))
            roots[item["traceId"]] = {
                "variant": metadata.get("variant"),
                "dataset_id": metadata.get("dataset_id"),
                "run_id": metadata.get("run_id"),
                "rewrite_enabled": metadata.get("rewrite_enabled"),
                "comparison_eligible": metadata.get("comparison_eligible"),
                "start": item.get("startTime") or "",
            }
    return build_scores(scores, roots, load_run_index())
