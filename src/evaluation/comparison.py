"""구성 비교: 저장된 실행(cases/runs/candidates.csv)에서 ID 기준 정밀도·재현율을 구성별로 센다.

사용: uv run --locked python -m src.evaluation.comparison results/<실행 폴더> [--k 5]

정의는 docs/problem.md의 `context_precision_id_at_5`, `context_recall_id_at_5`를 따른다.
허용 근거가 없는 문항은 두 값 모두 미정의(None)이고, 후보가 0개면 정밀도만 미정의다.
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


def run_scores(archive: Path, k: int = 5) -> list[dict]:
    cases = {
        (c["dataset_id"], c["case_id"]): json.loads(c["allowed_chunk_ids_json"] or "[]")
        for c in _rows(archive / "cases.csv")
    }
    top: dict[str, list[str]] = defaultdict(list)
    for c in _rows(archive / "candidates.csv"):
        if int(c["rank"]) <= k:
            top[c["run_id"]].append(c["chunk_id"])
    result = []
    for run in _rows(archive / "runs.csv"):
        precision, recall = id_scores(
            top[run["run_id"]], cases[(run["dataset_id"], run["case_id"])]
        )
        result.append(
            {
                "case_id": run["case_id"],
                "configuration": run["configuration"],
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
