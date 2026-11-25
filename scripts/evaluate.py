"""명시한 문항을 공통 파이프라인으로 실행한다. 자동 품질 지표는 계산하지 않는다."""

import argparse
import importlib
import json
from pathlib import Path

from src.config import load_settings
from src.demo import create_demo_pipeline
from src.evaluation.runner import evaluate_cases, load_evaluation_cases
from src.pipeline import RAGPipeline


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--settings", type=Path)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--demo", action="store_true")
    source.add_argument(
        "--factory", help="팀원 연결 함수 module:function. 인자는 RuntimeSettings"
    )
    args = parser.parse_args()
    settings = load_settings(args.settings)
    cases = load_evaluation_cases(args.cases)
    output = args.output_dir.resolve()
    if output.exists():
        parser.error(
            "기존 실행 결과를 덮어쓸 수 없습니다. 새 --output-dir를 지정하세요."
        )
    settings.runs_path = output / "runs"
    if args.demo:
        pipelines = {"synthetic-demo": create_demo_pipeline(settings)}
    else:
        module_name, separator, function_name = args.factory.partition(":")
        if not separator or not module_name or not function_name.isidentifier():
            parser.error("--factory는 module:function 형식이어야 합니다.")
        # 사용자가 명령행에 지정한 로컬 연결 코드만 실행한다. 평가 파일에서 함수를 읽지 않는다.
        configured = getattr(importlib.import_module(module_name), function_name)(
            settings
        )
        pipelines = (
            {"configured": configured}
            if isinstance(configured, RAGPipeline)
            else configured
        )
        if (
            not isinstance(pipelines, dict)
            or not pipelines
            or not all(
                isinstance(key, str) and isinstance(value, RAGPipeline)
                for key, value in pipelines.items()
            )
        ):
            parser.error(
                "factory는 RAGPipeline 또는 구성 이름별 RAGPipeline dict를 반환해야 합니다."
            )
    output.mkdir(parents=True, exist_ok=False)
    results = evaluate_cases(cases, pipelines)
    path = output / "evaluation.json"
    path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"{len(results)}회 실행 기록: {path}")
    if any(result["status"] == "error" for result in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
