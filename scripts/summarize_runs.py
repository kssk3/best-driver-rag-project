"""평가 실행 표(runs.csv)를 구성별로 단순 집계한다: 호출 성공 수/전체, 응답 시간 평균·중앙값·n, 오류 수.

사용: uv run --locked python -m scripts.summarize_runs results/local/<실행 폴더>/runs.csv
응답 시간(duration_ms)은 한 실행의 전체 시간이며 검색·생성과 질문 다듬기를 쓴 경우 그 시간도 포함한다.
"""

import argparse
import csv
from collections import defaultdict
from pathlib import Path
from statistics import mean, median

# 모델·검색 호출이 정상 끝난 상태. 근거 없음 안내(insufficient_evidence)는 정상 응답이라 성공에 넣는다.
SUCCESS_STATUSES = ("answered", "insufficient_evidence", "needs_clarification")


def summarize(rows: list[dict]) -> list[dict]:
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        key = (
            row.get("variant") or row.get("configuration") or "?",
            row.get("rewrite_enabled", ""),
        )
        groups[key].append(row)
    result = []
    for (variant, rewrite), items in sorted(groups.items()):
        ok = [r for r in items if r["status"] in SUCCESS_STATUSES]
        times = [float(r["duration_ms"]) for r in ok if r.get("duration_ms")]
        result.append(
            {
                "variant": variant,
                "rewrite_enabled": rewrite,
                "total": len(items),
                "succeeded": len(ok),
                "errors": sum(
                    1 for r in items if r["status"] == "error" or r.get("error_code")
                ),
                "n_timed": len(times),
                "mean_ms": mean(times) if times else None,
                "median_ms": median(times) if times else None,
            }
        )
    return result


def format_rows(summary: list[dict]) -> str:
    def ms(value: float | None) -> str:
        return "—" if value is None else f"{value:.0f}"

    lines = ["variant rewrite 성공/전체 오류 시간n 평균(ms) 중앙값(ms)"]
    for s in summary:
        lines.append(
            f"{s['variant']:<7} {s['rewrite_enabled'] or '-':<7} {s['succeeded']}/{s['total']} "
            f"{s['errors']} {s['n_timed']} {ms(s['mean_ms'])} {ms(s['median_ms'])}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs_csv", type=Path)
    args = parser.parse_args(argv)
    with args.runs_csv.open(encoding="utf-8", newline="") as file:
        print(format_rows(summarize(list(csv.DictReader(file)))))


if __name__ == "__main__":
    main()
