"""명시적으로 선택한 평가 문항을 구성별로 실행하고 원본 결과를 반환한다."""

from collections.abc import Mapping, Sequence
import json
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from src.contracts import EvaluationCase, PipelineRequest
from src.pipeline import RAGPipeline


class EvaluationCaseError(ValueError):
    """평가 입력 파일의 구조나 문항 식별자가 잘못된 경우."""


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise EvaluationCaseError(f"중복 JSON 필드: {key}")
        result[key] = value
    return result


def load_evaluation_cases(path: str | Path) -> list[EvaluationCase]:
    """문항 목록 또는 is_synthetic/cases 객체를 읽는다. 기본 평가셋을 추정하지 않는다."""
    path = Path(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=_unique_keys)
        if isinstance(payload, dict):
            if set(payload) != {"is_synthetic", "cases"} or not isinstance(payload["is_synthetic"], bool):
                raise EvaluationCaseError("묶음에는 bool is_synthetic과 cases 목록만 있어야 합니다.")
            payload = payload["cases"]
        if not isinstance(payload, list):
            raise EvaluationCaseError("평가 문항은 목록이어야 합니다.")
        allowed = set(EvaluationCase.model_fields)
        for index, item in enumerate(payload):
            if not isinstance(item, dict):
                raise EvaluationCaseError(f"cases[{index}]는 객체여야 합니다.")
            unexpected = set(item) - allowed
            if unexpected:
                raise EvaluationCaseError(f"cases[{index}]의 지원하지 않는 필드: {sorted(unexpected)}")
        cases = TypeAdapter(list[EvaluationCase]).validate_python(payload, strict=True)
        seen: set[str] = set()
        for index, case in enumerate(cases):
            if not case.case_id.strip() or not case.question.strip():
                raise EvaluationCaseError(f"cases[{index}]의 case_id와 question은 비어 있을 수 없습니다.")
            if case.case_id in seen:
                raise EvaluationCaseError(f"중복 case_id: {case.case_id}")
            seen.add(case.case_id)
        return cases
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, EvaluationCaseError) as error:
        raise EvaluationCaseError(f"{path}: {error}") from error


def evaluate_cases(
    cases: Sequence[EvaluationCase], pipelines: Mapping[str, RAGPipeline]
) -> list[dict]:
    """모든 문항/구성을 호출한다. record와 response는 JSON 직렬화 가능한 dict다.

    정답과 허용 근거는 평가 자료에만 둔다. 요청 생성 시 검색/생성 입력으로 전달하지 않는다.
    Ragas나 Hit 점수는 계산하지 않고, 후속 평가자가 사용할 실제 실행 결과만 반환한다.
    """
    results: list[dict] = []
    for case in cases:
        for configuration, pipeline in pipelines.items():
            try:
                request = PipelineRequest(
                    question=case.question, district=case.district, dong=case.dong,
                    conditions=dict(case.conditions),
                )
                record = pipeline.run(request)
                results.append({
                    "case_id": case.case_id, "configuration": configuration,
                    "run_id": record.run_id, "status": record.response.status,
                    "response": record.response.model_dump(mode="json"),
                    "record": record.model_dump(mode="json"), "error": record.response.error,
                })
            except Exception as error:
                # 기록 자체를 돌려받지 못한 호출도 누락하지 않는다. 실행 ID를 지어내지 않는다.
                results.append({
                    "case_id": case.case_id, "configuration": configuration,
                    "run_id": None, "status": "error", "response": None, "record": None,
                    "error": f"{type(error).__name__}: {error}",
                })
    return results
