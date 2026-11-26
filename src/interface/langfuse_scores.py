"""비교 패널: Langfuse에 올라간 faithfulness 점수를 실행 방식(variant)별로 집계한다.

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


class LangfuseReadError(RuntimeError):
    """조회에 실패했다. 코드만 담고 주소·키·응답 내용은 넣지 않는다."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class DatasetGroup:
    dataset_id: str
    latest: str  # 가장 최근 실행 시각(UTC ISO 문자열)
    summaries: list[VariantSummary]


@dataclass(frozen=True)
class LangfuseScores:
    groups: list[DatasetGroup]
    unlinked: int  # 방식을 알 수 없어 평균에서 뺀 점수 건수


def build_scores(scores: list[dict], roots: dict[str, dict]) -> LangfuseScores:
    """순수 집계. roots는 traceId → {"variant", "dataset_id", "start"}."""
    values: dict[str, dict[str, list[float]]] = {}
    latest: dict[str, str] = {}
    unlinked = 0
    for score in scores:
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
            unlinked += 1
            continue
        dataset = root.get("dataset_id") or UNKNOWN_DATASET
        by_variant = values.setdefault(dataset, {name: [] for name in VARIANTS})
        by_variant[root["variant"]].append(float(value))
        latest[dataset] = max(latest.get(dataset, ""), root.get("start") or "")
    groups = [
        DatasetGroup(
            dataset,
            latest[dataset],
            [
                VariantSummary(name, len(found), mean(found) if found else None)
                for name, found in by_variant.items()
            ],
        )
        for dataset, by_variant in values.items()
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
        SCORES_PATH,
        {
            "name": "faithfulness",
            "environment": "rag",
            "fields": "subject",
            "limit": 100,
        },
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
                "start": item.get("startTime") or "",
            }
    return build_scores(scores, roots)
