import json
from pathlib import Path

from src.config import load_settings
from src.contracts import Chunk, PipelineRequest, ResolvedQuery, SearchCandidate
from src.evaluation.answer_experiments.answer_evaluation_runtimes import (
    MissingEvaluationModelError,
)
from src.evaluation.runner import load_evaluation_cases
from src.generation.model_draft import make_model_draft
from src.generation.pipeline_adapter import make_answer_generator
from src.runtime import create_runtime


def main() -> None:
    # 개발 문항과 저장된 검색 결과가 같은 질문인지 확인한다.
    cases = load_evaluation_cases("eval/dev.json")
    case = next(c for c in cases if c.case_id == "p04-colors-trick")
    path = Path("results/local/color-table-retrieval-top5.json")
    search = json.loads(path.read_text(encoding="utf-8"))
    if (search["question"], search["district"]) != (case.question, case.district):
        raise SystemExit("검색 기록의 질문 또는 자치구가 다릅니다.")

    # 검색 결과의 순서, 점수, 본문을 그대로 복원한다 .
    [index] = search["results"]
    candidates = [
        SearchCandidate(
            rank=rank, score=m["score"], chunk=Chunk.model_validate(m["chunk"])
        )
        for rank, m in enumerate(index["matches"], start=1)
    ]
    ranked_ids = [item.chunk.chunk_id for item in candidates]
    if len(ranked_ids) != 5 or len(set(ranked_ids)) != 5:
        raise SystemExit("서로 다른 검색 후보 5개가 필요합니다.")

    # 이번 실행에서 다섯 본문이 모두 모델에 들어가도록 설정한다.
    settings = load_settings("configs/answer-model-settings.json")
    settings.runs_path = Path("results/local/color-table-answers/runs")
    options = settings.pipeline
    model = options.versions.get("model", "").strip()
    if not model:
        raise MissingEvaluationModelError("답변 모델 ID가 필요합니다.")

    options.max_context_chars = sum(len(c.chunk.content) for c in candidates)
    options.run_kind = "fixed_evidence"

    # 기존 답변 생성기에 질문과 검색 후보를 연결한다.
    runtime = create_runtime(
        settings,
        resolver=lambda req: ResolvedQuery(
            search_query=req.question, district=req.district, dong=req.dong
        ),
        retriever=lambda *_args, **_kwargs: candidates,
        generator=make_answer_generator(make_model_draft(model)),
    )
    request = PipelineRequest(
        question=case.question,
        district=case.district,
        dong=case.dong,
        conditions=case.conditions,
    )

    record = runtime.run(request)

    print("실행 기록:", settings.runs_path / f"{record.run_id}.json")

    if record.response.status != "answered":
        raise SystemExit(
            f"{record.response.status} · {record.response.error or record.response.answer}"
        )
    if record.model_input_chunk_ids != ranked_ids:
        raise SystemExit("실제 모델 입력이 검색 Top-5의 순서 또는 개수와 다릅니다.")

    # 답변은 모범 답안과 나란히 보고, 인용은 청크 ID로 대조한다.
    cited = [citation.chunk_id for citation in record.response.citations]
    print("모델 답변:", record.response.answer)
    print("모범 답안:", case.reference_answer)
    print("인용한 검색 순위:", [ranked_ids.index(chunk_id) + 1 for chunk_id in cited])
    print(
        "1위가 허용 정답이면서 인용됐나:",
        ranked_ids[0] in case.allowed_chunk_ids and ranked_ids[0] in cited,
    )


if __name__ == "__main__":
    main()
