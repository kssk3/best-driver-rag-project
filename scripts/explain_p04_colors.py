"""P04 색상표가 답변과 인용으로 이어지는 과정을 출력한다."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from src.config import RuntimeSettings
from src.contracts import PipelineOptions, ResolvedQuery, SearchCandidate
from src.evaluation.answer_experiments.evidence_answer_probe import (
    draft_evidence_answer,
    make_evidence_request,
)
from src.generation.answer import AnswerDraft, GenerationInput
from src.generation.pipeline_adapter import make_answer_generator
from src.ingestion.preprocessed_bundle import load_preprocessed_bundle
from src.ingestion.preprocessed_chunking import chunk_preprocessed_documents
from src.runtime import create_runtime

PROJECT = Path(__file__).resolve().parents[1]
BUNDLE = PROJECT / "data/handoff/jungeun/ordinance-handoff-2026-11-24"
COLOR_DOCUMENT_ID = "seodaemun-rules:attachment:160561037"


def main() -> None:
    request = make_evidence_request(
        "서대문구 공동주택 일반용기에서 유리병은 회색이고 캔은 주황색이 맞죠?",
        district="서대문구",
        conditions={"housing_type": "공동주택", "container_type": "일반용기"},
    )
    print(f"질문: {request.question}")

    # 색상표의 JSON 청크를 고정해 검색과 답변 작성을 따로 살펴본다.
    bundle = load_preprocessed_bundle(BUNDLE, project_root=PROJECT, version="v1")
    documents = [
        doc for doc in bundle.documents if doc.document_id == COLOR_DOCUMENT_ID
    ]
    chunks = chunk_preprocessed_documents(documents)
    color_chunk = next(
        chunk
        for chunk in chunks
        if chunk.content_format == "json" and chunk.source_location == "table-1/row[0]"
    )
    print("\n1. 고정 검색 후보")
    print(
        f"   순위 1 · {color_chunk.source_document_id} · {color_chunk.source_location}"
    )

    def show_draft(payload: GenerationInput) -> AnswerDraft:
        # 답변 함수가 실제로 받은 근거를 펼쳐 보여준다.
        evidence = payload["evidence"][0]
        content = json.loads(evidence["text"])
        print("\n2. 초안 함수에 들어온 근거")
        print(f"   조건: {payload['conditions']}")
        print(f"   evidence[0].chunk_id: {evidence['chunk_id']}")
        for row in content["structured_image_summary"]["colors"]:
            print(f"   {row['item']} → {row['color']}")

        draft = draft_evidence_answer(payload)
        print("\n3. 로컬 초안 함수가 반환한 값")
        print(f"   상태: {draft['status']}")
        print(f"   답변: {draft.get('message')}")
        print(f"   근거 목록의 위치(citation_indices): {draft.get('citation_indices')}")
        return draft

    with TemporaryDirectory(prefix="p04-colors-") as directory:
        runtime = create_runtime(
            RuntimeSettings(
                runs_path=Path(directory),
                pipeline=PipelineOptions(run_kind="fixed_evidence"),
            ),
            resolver=lambda question: ResolvedQuery(
                search_query=question.question, district=question.district
            ),
            retriever=lambda *_args, **_kwargs: [
                SearchCandidate(chunk=color_chunk, rank=1)
            ],
            generator=make_answer_generator(show_draft),
        )
        record = runtime.run(request)

    # 공통 런타임이 만든 인용을 실제 생성 입력의 ID와 대조한다.
    print("\n4. 사용자에게 전달되는 최종 인용")
    response = record.response
    print(f"   상태: {response.status}")
    if response.status != "answered":
        raise SystemExit(response.error or response.answer)
    for citation in response.citations:
        print(f"   청크 ID: {citation.chunk_id}")
        print(f"   원문 위치: {citation.source_location}")
        citation_in_input = citation.chunk_id in record.model_input_chunk_ids
        print(f"   생성 입력에 포함된 ID인가: {citation_in_input}")


if __name__ == "__main__":
    main()
