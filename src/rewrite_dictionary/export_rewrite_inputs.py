"""팀과 개인 포크의 별칭표, 개발용 평가 입력을 JSON으로 내보낸다."""

import argparse
import ast
import csv
import hashlib
import json
from pathlib import Path

ALIAS_SOURCE = Path("src/query/aliases.py")
EVALUATION_SOURCE = Path("learning/recycling_chat/evaluation")
EVALUATION_FILES = (
    "rewrite_cases.tsv",
    "nationwide_dialect_cases.json",
    "multi_item_cases.json",
    "personal_retrieval_cases.json",
)


def read_alias_profile(repo: Path) -> dict:
    source = (repo / ALIAS_SOURCE).read_bytes()
    assignments = ast.parse(source).body
    for assignment in assignments:
        if isinstance(assignment, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "ITEM_ALIASES"
            for target in assignment.targets
        ):
            aliases = ast.literal_eval(assignment.value)
            if not isinstance(aliases, dict) or not all(
                isinstance(alias, str) and isinstance(term, str)
                for alias, term in aliases.items()
            ):
                raise ValueError(f"문자열 별칭표가 아닙니다: {repo / ALIAS_SOURCE}")
            return {
                "source_file": ALIAS_SOURCE.as_posix(),
                "source_sha256": hashlib.sha256(source).hexdigest(),
                "alias_count": len(aliases),
                "item_aliases": aliases,
            }
    raise ValueError(f"ITEM_ALIASES가 없습니다: {repo / ALIAS_SOURCE}")


def read_evaluation_set(path: Path) -> dict:
    if path.suffix == ".tsv":
        with path.open(encoding="utf-8-sig", newline="") as stream:
            data = {"cases": list(csv.DictReader(stream, delimiter="\t"))}
    else:
        data = json.loads(path.read_text(encoding="utf-8"))
    return {"source_file": path.name, "case_count": len(data["cases"]), "data": data}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("team_repo", type=Path, help="팀 저장소 경로")
    parser.add_argument("personal_fork", type=Path, help="개인 포크 경로")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).parent)
    args = parser.parse_args()

    profiles = {
        "team": read_alias_profile(args.team_repo),
        "personal_fork": read_alias_profile(args.personal_fork),
    }
    sets = [
        read_evaluation_set(args.personal_fork / EVALUATION_SOURCE / filename)
        for filename in EVALUATION_FILES
    ]
    evaluation = {
        "schema_version": 1,
        "scope": "development_evaluation",
        "case_count": sum(dataset["case_count"] for dataset in sets),
        "datasets": sets,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for filename, data in (
        ("rewrite_alias_profiles.json", profiles),
        ("rewrite_evaluation.json", evaluation),
    ):
        (args.output_dir / filename).write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
