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
from src.observability.tracing import trace_id_for_run

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
    # 비교 대상이 아니라고 기록된 점수
    ineligible: dict[str, int] = field(default_factory=_zero)
    # 문항(case_id)을 알 수 없어 다시 실행한 점수와의 중복을 확인하지 못한 점수(평균에는 들어간다).
    case_unknown: dict[str, int] = field(default_factory=_zero)


def _flag(value) -> bool | None:
    """true/false(불리언 또는 문자열)를 읽는다. 그 밖의 값은 알 수 없음(None)이다."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    return None


def _extra_dirs() -> list[Path]:
    """RAG_RESULTS_INDEX_DIRS(쉼표로 구분, 저장소 루트 기준 상대 경로 가능). 기본은 없음이다."""
    raw = os.environ.get("RAG_RESULTS_INDEX_DIRS", "")
    return [
        RESULTS_DIR.parent / part.strip() for part in raw.split(",") if part.strip()
    ]


def load_run_index(
    results_dir: Path = RESULTS_DIR, extra_dirs: list[Path] | None = None
) -> dict[str, dict]:
    """저장소 results/*/runs.csv와 scores.csv에서 run_id → 평가 세트·리라이트·비교 자격을 읽는다.

    트레이스 메타데이터에 이 값이 없는 옛 점수를 run_id로 이어 확인하는 용도다.
    비교 자격(comparison_eligible)은 Faithfulness 점수의 속성이라 scores.csv에만 있고, 한 실행의 여러 행 중
    하나라도 false이면 false다. 하위 폴더(results/<실험>/abc/ 등)까지 찾는다.
    """
    runs: dict[str, dict] = {}

    extras = _extra_dirs() if extra_dirs is None else extra_dirs

    def read(name: str):
        # 기본은 공유되는 결과(results/local 제외)다. 추가 폴더는 지정한 것만 그대로 읽는다.
        paths = [
            path
            for path in sorted(results_dir.rglob(name))
            if "local" not in path.relative_to(results_dir).parts
        ]
        for extra in extras:
            paths += sorted(extra.rglob(name))
        for path in paths:
            try:
                with path.open(encoding="utf-8-sig", newline="") as file:
                    yield from csv.DictReader(file)
            except OSError:
                continue

    def note(row: dict) -> dict:
        """run_id 한 건의 기록. 같은 run_id가 다른 평가 세트·리라이트로 또 나오면 모호하다고 표시한다."""
        dataset = row.get("dataset_id") or None
        rewrite = _flag(row.get("rewrite_enabled"))
        info = runs.setdefault(
            row.get("run_id", ""),
            {
                "dataset_id": dataset,
                "rewrite_enabled": rewrite,
                "eligible": None,
                "case_id": row.get("case_id") or None,
            },
        )
        if (dataset and info["dataset_id"] and dataset != info["dataset_id"]) or (
            rewrite is not None
            and info["rewrite_enabled"] is not None
            and rewrite != info["rewrite_enabled"]
        ):
            info["ambiguous"] = True
        return info

    for row in read("runs.csv"):
        note(row)
    for row in read("scores.csv"):
        info = note(row)
        eligible = _flag(row.get("comparison_eligible"))
        if eligible is not None and row.get("metric", "faithfulness") == "faithfulness":
            info["eligible"] = (
                eligible if info["eligible"] is None else info["eligible"] and eligible
            )
    return runs


def _is_numeric_score(score: dict) -> bool:
    value = score.get("value")
    return (
        score.get("dataType", "NUMERIC") == "NUMERIC"
        and isinstance(value, int | float)
        and not isinstance(value, bool)
        and isfinite(value)
    )


def _latest_per_trace_and_metric(scores: list[dict]) -> list[dict]:
    """같은 실행(trace)을 여러 번 채점하면 지표마다 가장 최근 점수 하나만 남긴다(표본이 겹쳐 가중되지 않게)."""
    best: dict[tuple[str, str], tuple[str, int, dict]] = {}
    others: list[dict] = []
    for index, score in enumerate(scores):
        subject = score.get("subject") or {}
        if (
            score.get("name") not in METRIC_NAMES
            or subject.get("kind") != "trace"
            or not _is_numeric_score(score)
        ):
            # 같은 이름의 텍스트 주석 점수 같은 것은 후보가 아니다. 정상 숫자 점수를 가리지 않게 따로 둔다.
            others.append(score)
            continue
        key = (str(subject.get("id")), score["name"])
        stamp = str(score.get("timestamp") or score.get("createdAt") or "")
        if key not in best or (stamp, index) > best[key][:2]:
            best[key] = (stamp, index, score)
    return others + [item[2] for item in best.values()]


def _runs_by_trace(runs: dict[str, dict]) -> dict[str, list[str]]:
    """trace ID → run_id 목록. 보관본 업로더의 복구 루트에는 run_id가 없어 trace ID로 대조한다."""
    by_trace: dict[str, list[str]] = {}
    for run_id in runs:
        if run_id:
            by_trace.setdefault(trace_id_for_run(run_id), []).append(run_id)
    return by_trace


def _case_id(root: dict, runs: dict[str, dict], trace_id: str, by_trace) -> str | None:
    """문항 ID. 루트 메타데이터에 있으면 그것을, 없으면 run 인덱스(run_id 또는 trace ID로 유일하게 일치)에서 얻는다."""
    if root.get("case_id"):
        return str(root["case_id"])
    info = runs.get(str(root.get("run_id"))) or {}
    if not info:
        matches = (by_trace or {}).get(trace_id, [])
        info = runs[matches[0]] if len(matches) == 1 else {}
    return None if info.get("ambiguous") else info.get("case_id")


def _resolve(
    root: dict,
    runs: dict[str, dict],
    meta: dict,
    metric: str,
    trace_id: str = "",
    by_trace: dict[str, list[str]] | None = None,
) -> tuple[str | None, bool | None, bool | None]:
    """(평가 세트, 리라이트 여부, 비교 자격). 점수 자체의 메타데이터를 먼저, 없는 값은 루트 메타데이터,
    그다음 루트의 run_id로 맞춘 로컬 기록으로 채운다."""
    info = runs.get(str(root.get("run_id"))) or {}
    if not info:
        # 루트 메타데이터에 run_id가 없으면 trace ID로 맞춘다. 일치하는 run이 하나일 때만 쓴다.
        matches = (by_trace or {}).get(trace_id, [])
        info = runs[matches[0]] if len(matches) == 1 else {}
    if info.get("ambiguous"):
        info = {}  # 같은 run_id가 서로 다른 평가로 기록돼 있어 어느 쪽인지 모른다.
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
    by_trace = _runs_by_trace(runs)
    unlinked, unverified, ineligible, case_unknown = _zero(), _zero(), _zero(), _zero()
    # (평가 세트, 리라이트, 문항, 방식, 지표)마다 가장 최근 점수 하나만 쓴다. 같은 데이터셋을 다시 실행해
    # run_id가 달라도 같은 문항이 두 번 세지지 않고, 일부 방식만 다시 실행해도 다른 방식은 그대로다.
    chosen: dict[tuple, tuple[str, int, float, str]] = {}
    for index, score in enumerate(_latest_per_trace_and_metric(scores)):
        name = score.get("name")
        if name not in METRIC_NAMES:
            continue  # 우리가 보여 주는 지표가 아니다(Hit@k 등).
        subject = score.get("subject") or {}
        trace_id = str(subject.get("id"))
        root = roots.get(trace_id)
        if subject.get("kind") != "trace":
            root = None
        if root is not None and root.get("conflict"):
            unverified[name] += (
                1  # 한 trace에 루트가 둘 이상이라 어느 쪽 기준인지 모른다.
            )
            continue
        meta = _score_metadata(score)
        # 방식(A/B/C)은 루트 metadata를, 없으면 점수 metadata를 쓴다(보관본 복구 루트에는 variant가 없을 수 있다).
        variant = root.get("variant") if root else None
        if variant not in VARIANTS:
            variant = meta.get("variant")
        if root is None or variant not in VARIANTS or not _is_numeric_score(score):
            unlinked[name] += 1
            continue
        dataset, rewrite, eligible = _resolve(
            root, runs, meta, name, trace_id, by_trace
        )
        if dataset is None or rewrite is None or eligible is None:
            unverified[name] += 1
            continue
        if not eligible:
            ineligible[name] += 1
            continue
        case = (
            str(meta["case_id"])
            if meta.get("case_id")
            else _case_id(root, runs, trace_id, by_trace)
        )
        if case is None:
            case_unknown[name] += 1  # 문항을 모르면 이 trace 하나를 단위로 둔다.
        key = (dataset, rewrite, case or f"trace:{trace_id}", variant, name)
        stamp = str(score.get("timestamp") or score.get("createdAt") or "")
        if key not in chosen or (stamp, index) > chosen[key][:2]:
            chosen[key] = (stamp, index, float(score["value"]), root.get("start") or "")
    values: dict[tuple[str, bool], dict[str, dict[str, list[float]]]] = {}
    latest: dict[tuple[str, bool], str] = {}
    for (dataset, rewrite, _case, variant, name), (
        _,
        _,
        value,
        start,
    ) in chosen.items():
        group = (dataset, rewrite)
        by_metric = values.setdefault(
            group, {m: {v: [] for v in VARIANTS} for m in METRIC_NAMES}
        )
        by_metric[name][variant].append(value)
        latest[group] = max(latest.get(group, ""), start)
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
    return LangfuseScores(groups, unlinked, unverified, ineligible, case_unknown)


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
        SCORES_PATH,
        {
            "environment": "rag",
            "name": ",".join(METRIC_NAMES),
            "fields": "subject,details",
            "limit": 100,
        },
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
                "case_id": metadata.get("case_id"),
                "rewrite_enabled": metadata.get("rewrite_enabled"),
                "comparison_eligible": metadata.get("comparison_eligible"),
                "start": item.get("startTime") or "",
            }
    return build_scores(scores, roots, load_run_index())
