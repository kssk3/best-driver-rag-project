"""구성 비교: 저장된 실행(cases/runs/candidates.csv)에서 ID 기준 정밀도·재현율을 구성별로 센다.

사용: uv run --locked python -m src.evaluation.comparison results/<실행 폴더> [--k 5]

정의는 docs/problem.md의 `context_precision_id_at_5`, `context_recall_id_at_5`를 따른다.
허용 근거가 없는 문항과 검색이 실패한 실행(retrieval_status가 ok가 아님)은 두 값 모두 미정의(None)이고,
정상 검색의 후보가 0개면 정밀도만 미정의, 재현율은 0이다. 후보 행이 원본 건수와 다르거나 --k가 top_k보다 크면 중단한다.
"""

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def id_scores(
    returned: list[str], allowed: list[str]
) -> tuple[float | None, float | None]:
    """(정밀도, 재현율). 둘 다 서로 다른 chunk_id 기준이다."""
    wanted = set(allowed)
    if not wanted:
        return None, None
    found = set(returned)
    hit = len(found & wanted)
    return (hit / len(found) if found else None), hit / len(wanted)


def _check_candidates(run: dict[str, str], ranked: dict[int, str], k: int) -> None:
    """정상 검색의 후보 파일이 원본 건수·순위와 맞고 k가 저장 깊이 이내인지 확인한다."""
    if k > int(run["top_k"]):
        raise ValueError(f"--k {k}가 저장된 검색 깊이 top_k={run['top_k']}보다 큽니다.")
    if len(ranked) != int(run["candidate_count"]) or sorted(ranked) != list(
        range(1, len(ranked) + 1)
    ):
        raise ValueError(f"실행 {run['run_id']}의 후보 행이 원본 건수·순위와 다릅니다.")


def run_scores(archive: Path, k: int = 5) -> list[dict]:
    if k < 1:
        raise ValueError("--k는 1 이상이어야 합니다.")
    case_rows = _rows(archive / "cases.csv")
    if len({(c["dataset_id"], c["case_id"]) for c in case_rows}) != len(case_rows):
        raise ValueError(
            "cases.csv에 같은 (dataset_id, case_id)가 두 번 이상 있습니다."
        )
    cases = {
        (c["dataset_id"], c["case_id"]): json.loads(c["allowed_chunk_ids_json"] or "[]")
        for c in case_rows
    }
    runs = _rows(archive / "runs.csv")
    if len({r["run_id"] for r in runs}) != len(runs):
        raise ValueError("runs.csv에 같은 run_id가 두 번 이상 있습니다.")
    # run_kind가 빈 행은 실행 기록 없이 실패한 행이라 미정의로 남기고, 실제 기록이 rag가 아니면 막는다.
    if any(r["run_kind"] not in ("rag", "") for r in runs):
        raise ValueError("실제 검색(run_kind=rag)이 아닌 실행은 검색 지표에서 뺍니다.")
    owner = {r["run_id"]: (r["dataset_id"], r["case_id"]) for r in runs}
    ranked: dict[str, dict[int, str]] = defaultdict(dict)
    for c in _rows(archive / "candidates.csv"):
        if owner.get(c["run_id"]) != (c["dataset_id"], c["case_id"]):
            raise ValueError(
                f"후보 행의 실행 {c['run_id']}이 runs.csv의 문항·데이터셋과 다릅니다."
            )
        if not c["chunk_id"].strip():
            raise ValueError(f"실행 {c['run_id']}의 후보에 빈 chunk_id가 있습니다.")
        rank = int(c["rank"])
        if rank in ranked[c["run_id"]]:
            raise ValueError(
                f"실행 {c['run_id']}의 순위 {rank}가 후보 파일에 두 번 있습니다."
            )
        ranked[c["run_id"]][rank] = c["chunk_id"]
    result = []
    for run in runs:
        precision = recall = None  # 검색이 실패한 실행은 0점이 아니라 미정의다.
        if run["retrieval_status"] == "ok":
            _check_candidates(run, ranked[run["run_id"]], k)
            top = [c for rank, c in ranked[run["run_id"]].items() if rank <= k]
            precision, recall = id_scores(
                top, cases[(run["dataset_id"], run["case_id"])]
            )
        result.append(
            {
                "case_id": run["case_id"],
                "configuration": run.get("variant") or run["configuration"],
                "rewrite_enabled": run["rewrite_enabled"],
                "status": run["status"],
                "precision": precision,
                "recall": recall,
            }
        )
    return result


def by_configuration(rows: list[dict]) -> list[dict]:
    """구성(+리라이트 여부)별 평균과 표본 수. 미정의 값은 평균에서 빼고 n에 센다."""
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        groups[(row["configuration"], row["rewrite_enabled"])].append(row)
    summary = []
    for (configuration, rewrite), items in sorted(groups.items()):
        precision = [r["precision"] for r in items if r["precision"] is not None]
        recall = [r["recall"] for r in items if r["recall"] is not None]
        summary.append(
            {
                "configuration": configuration,
                "rewrite_enabled": rewrite,
                "precision": mean(precision) if precision else None,
                "precision_n": len(precision),
                "recall": mean(recall) if recall else None,
                "recall_n": len(recall),
            }
        )
    return summary


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--k", type=int, default=5)
    args = parser.parse_args(argv)
    for row in by_configuration(run_scores(args.archive, args.k)):
        precision = "-" if row["precision"] is None else f"{row['precision']:.3f}"
        recall = "-" if row["recall"] is None else f"{row['recall']:.3f}"
        print(
            f"{row['configuration']} rewrite={row['rewrite_enabled']}: "
            f"precision@{args.k}={precision} (n={row['precision_n']}) "
            f"recall@{args.k}={recall} (n={row['recall_n']})"
        )


if __name__ == "__main__":
    main()
