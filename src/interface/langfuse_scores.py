"""비교 패널: Langfuse에 올라간 RAGAS 4대 지표 점수를 실행 방식(variant)별로 집계한다.

점수의 subject.id(trace ID)를 실행 루트 관측의 traceId와 잇고, 루트의 metadata.variant와
dataset_id를 읽는다. variant가 A/B/C가 아니거나 루트를 못 찾은 점수는 평균에서 뺀다.
이 서버는 v4 events_only 모드라 구형 /scores 조회는 404이고 v3 scores와 v2 observations만 된다.
"""

import base64
import json
import os
from dataclasses import dataclass
from http.client import HTTPSConnection
from math import isfinite
from statistics import mean
from urllib.parse import urlencode, urlsplit

from src.interface.comparison import VARIANTS, VariantSummary

SCORES_PATH = "/api/public/v3/scores"
OBSERVATIONS_PATH = "/api/public/v2/observations"
MAX_PAGES = 20
UNKNOWN_DATASET = "알 수 없음"
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
    # dataset_id가 없는 옛 실행은 evaluation_id로 묶는다. 화면에서 "데이터셋"과 "평가"를 구별한다.
    by_evaluation: bool = False


@dataclass(frozen=True)
class LangfuseScores:
    groups: list[DatasetGroup]
    unlinked: dict[str, int]  # 지표별로 방식을 알 수 없어 평균에서 뺀 점수 건수


def build_scores(scores: list[dict], roots: dict[str, dict]) -> LangfuseScores:
    """순수 집계. roots는 traceId → {"variant", "dataset_id", "start"}."""
    values: dict[str, dict[str, dict[str, list[float]]]] = {}
    latest: dict[str, str] = {}
    evaluation_keys: set[str] = set()
    unlinked = {m: 0 for m in METRIC_NAMES}
    for score in scores:
        name = score.get("name")
        if name not in METRIC_NAMES:
            continue  # 우리가 보여 주는 지표가 아니다(Hit@k 등).
        subject = score.get("subject") or {}
        root = roots.get(str(subject.get("id")))
        if subject.get("kind") != "trace":
            root = None
        value = score.get("value")
        if (
            root is None
            or root.get("variant") not in VARIANTS
            or not isinstance(value, int | float)
            or not isfinite(value)
        ):
            unlinked[name] += 1
            continue
        dataset = root.get("dataset_id") or root.get("evaluation_id") or UNKNOWN_DATASET
        if not root.get("dataset_id") and root.get("evaluation_id"):
            evaluation_keys.add(dataset)
        by_metric = values.setdefault(
            dataset, {m: {v: [] for v in VARIANTS} for m in METRIC_NAMES}
        )
        by_metric[name][root["variant"]].append(float(value))
        latest[dataset] = max(latest.get(dataset, ""), root.get("start") or "")
    groups = [
        DatasetGroup(
            dataset,
            latest[dataset],
            {
                metric: [
                    VariantSummary(variant, len(found), mean(found) if found else None)
                    for variant, found in by_variant.items()
                ]
                for metric, by_variant in by_metric.items()
            },
            dataset in evaluation_keys,
        )
        for dataset, by_metric in values.items()
    ]
    groups.sort(key=lambda group: group.latest, reverse=True)
    return LangfuseScores(groups, unlinked)


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
            break
    return rows


def load_langfuse_scores() -> LangfuseScores:
    scores = _pages(
        SCORES_PATH, {"environment": "rag", "fields": "subject", "limit": 100}
    )
    observations = _pages(
        OBSERVATIONS_PATH, {"fields": "core,basic,metadata", "limit": 1000}
    )
    roots = {}
    for item in observations:
        if item.get("isRootObservation") and item.get("traceId"):
            metadata = item.get("metadata") or {}
            roots[item["traceId"]] = {
                "variant": metadata.get("variant"),
                "dataset_id": metadata.get("dataset_id"),
                "evaluation_id": metadata.get("evaluation_id"),
                "start": item.get("startTime") or "",
            }
    return build_scores(scores, roots)
