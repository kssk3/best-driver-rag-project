import json
import sys
from types import SimpleNamespace

import langchain_openai

from scripts.evaluate import main
from src.contracts import Chunk
from src.generation import model_draft
from src.infrastructure.embeddings import create_openai_embeddings
from src.infrastructure.stores import save_index
from src.ingestion.indexing import build_index


def test_a_evaluation_retrieves_and_cites_for_each_question(monkeypatch, tmp_path):
    questions = {"서대문구 첫 질문?": "서대문구", "송파구 두 번째 질문?": "송파구"}
    vectors = {
        "서대문구 첫 질문?": [1.0, 0.0],
        "송파구 두 번째 질문?": [0.0, 1.0],
        "서대문구의 합성 근거": [1.0, 0.0],
        "송파구의 합성 근거": [0.0, 1.0],
    }
    searched = set()

    class FakeEmbeddings:
        def __init__(self, **_settings):
            self.openai_api_base = "https://api.openai.com/v1"

        def embed_documents(self, texts):
            return [vectors[text] for text in texts]

        def embed_query(self, text):
            searched.add(text)
            return vectors[text]

    class FakeChat:
        def __init__(self, **_settings):
            pass

        def bind(self, **_options):
            return self

        def invoke(self, messages):
            payload = json.loads(messages[-1][1])
            district = questions[payload["original_question"]]
            assert payload["conditions"]["district"] == district
            assert set(payload) == {"original_question", "conditions", "evidence"}
            [evidence] = payload["evidence"]
            return SimpleNamespace(
                content=json.dumps(
                    {
                        "status": "answered",
                        "message": evidence["text"],
                        "citation_indices": [0],
                    }
                )
            )

    monkeypatch.setattr(langchain_openai, "OpenAIEmbeddings", FakeEmbeddings)
    monkeypatch.setattr(model_draft, "ChatOpenAI", FakeChat)
    chunks = [
        Chunk(
            chunk_id=district,
            source_document_id=district,
            source_document_version="v1",
            title=f"{district} 합성 자료",
            content_format="json",
            content=f"{district}의 합성 근거",
            source_url="https://example.org/guide",
            source_location="합성 근거",
            scope_type="district",
            districts=[district],
            chunking_version="synthetic-v1",
        )
        for district in questions.values()
    ]
    index_path = tmp_path / "index.json"
    save_index(
        build_index(chunks, create_openai_embeddings("text-embedding-3-small")),
        index_path,
    )
    cases = tmp_path / "cases.json"
    cases.write_text(
        json.dumps(
            [
                {
                    "case_id": district,
                    "question": question,
                    "reference_answer": "Synthetic scoring data",
                    "allowed_chunk_ids": ["scoring-only-id"],
                }
                for question, district in questions.items()
            ]
        ),
        encoding="utf-8",
    )
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "index_path": str(index_path),
                "pipeline": {"versions": {"model": "fake-model"}},
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "output"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "evaluate",
            "--cases",
            str(cases),
            "--output-dir",
            str(output),
            "--settings",
            str(settings),
            "--factory",
            "src.evaluation.answer_experiments.p04_model_run:create_a_runtime",
        ],
    )

    main()

    rows = json.loads((output / "evaluation.json").read_text(encoding="utf-8"))
    assert {row["case_id"] for row in rows} == set(questions.values())
    assert searched == set(questions)
    for row in rows:
        district = row["case_id"]
        record = row["record"]
        assert record["run_kind"] == "rag"
        assert [(c["rank"], c["chunk"]["chunk_id"]) for c in record["candidates"]] == [
            (1, district)
        ]
        assert record["model_input_chunk_ids"] == [district]
        assert row["response"]["answer"] == f"{district}의 합성 근거"
        assert [c["chunk_id"] for c in row["response"]["citations"]] == [district]
        assert (output / "runs" / f"{row['run_id']}.json").is_file()
