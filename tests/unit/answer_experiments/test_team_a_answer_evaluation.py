import json
import sys
from hashlib import sha256
from unittest.mock import Mock

import langchain_openai
import pytest
from langchain_core.messages import AIMessage

from scripts.evaluate import main
from src.contracts import Chunk
from src.evaluation.answer_experiments import answer_evaluation_runtimes as runtimes
from src.infrastructure import chat_models
from src.infrastructure.embeddings import create_openai_embeddings
from src.infrastructure.stores import save_index
from src.ingestion.indexing import build_index
from src.rewrite_dictionary.catalog import CATALOG_PATH


@pytest.mark.parametrize("factory", ["create_a_runtime", "create_a_rewrite_comparison"])
def test_a_evaluation_retrieves_and_cites_for_each_question(
    monkeypatch, tmp_path, factory
):
    original = "잠실동에서 안 씻은 우유펙은 우야노?"
    expanded = "잠실동에서 안 씻은 우유펙은 어떻게 해야 하나요? (종이팩)"
    questions = {"서대문구 첫 질문?": "서대문구", original: "송파구"}
    vectors = {
        "서대문구 첫 질문?": [1.0, 0.0],
        original: [0.0, 1.0],
        expanded: [0.0, 1.0],
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
            if district == "송파구":
                assert payload["conditions"]["dong"] == "잠실동"
                assert payload["conditions"]["housing"] == "일반주택"
            assert set(payload) == {"original_question", "conditions", "evidence"}
            [evidence] = payload["evidence"]
            return AIMessage(
                content=json.dumps(
                    {
                        "status": "answered",
                        "message": evidence["text"],
                        "citation_indices": [0],
                    }
                )
            )

    monkeypatch.setattr(langchain_openai, "OpenAIEmbeddings", FakeEmbeddings)
    monkeypatch.setenv("OPENAI_API_KEY", "offline-unit-test-key")
    monkeypatch.setattr(chat_models, "ChatOpenAI", FakeChat)
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
                    "conditions": {"housing": "일반주택"},
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
                "pipeline": {
                    "versions": {
                        "model": "fake-model",
                        "candidate_policy": "old-hybrid",
                        "reranker_model": "old-reranker",
                        "reranker_prompt": "old-reranker-prompt",
                        "rewrite": "old-rewrite",
                        "rewrite_catalog": "old-catalog",
                        "dataset": "synthetic-v1",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "output"
    index_loader = Mock(wraps=runtimes.load_index)
    monkeypatch.setattr(runtimes, "load_index", index_loader)
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
            f"src.evaluation.answer_experiments.answer_evaluation_runtimes:{factory}",
        ],
    )

    main()

    rows = json.loads((output / "evaluation.json").read_text(encoding="utf-8"))
    index_loader.assert_called_once_with(index_path)
    comparison = factory == "create_a_rewrite_comparison"
    configurations = {"rewrite-off", "rewrite-on"} if comparison else {"configured"}
    assert len(rows) == len(questions) * len(configurations)
    assert {row["configuration"] for row in rows} == configurations
    assert {row["case_id"] for row in rows} == set(questions.values())
    assert searched == set(questions) | ({expanded} if comparison else set())
    assert len({row["record"]["options"]["versions"]["index"] for row in rows}) == 1
    for row in rows:
        district = row["case_id"]
        record = row["record"]
        assert record["run_kind"] == "rag"
        question = next(q for q, target in questions.items() if target == district)
        enabled = row["configuration"] == "rewrite-on"
        assert record["request"]["question"] == question
        assert record["request"]["conditions"] == {"housing": "일반주택"}
        assert record["search_query"] == (
            expanded if enabled and district == "송파구" else question
        )
        assert record["options"]["rewrite_enabled"] is enabled
        rewrite = next(
            stage for stage in record["stages"] if stage["name"] == "rewrite"
        )
        assert rewrite["status"] == ("ok" if enabled else "skipped")
        versions = record["options"]["versions"]
        assert {"candidate_policy", "reranker_model", "reranker_prompt"}.isdisjoint(
            versions
        )
        assert versions["dataset"] == "synthetic-v1"
        if enabled:
            assert versions["rewrite"] == "catalog-rules-v1"
            assert (
                versions["rewrite_catalog"]
                == sha256(CATALOG_PATH.read_bytes()).hexdigest()
            )
        else:
            assert "rewrite" not in versions
            assert "rewrite_catalog" not in versions
        assert [(c["rank"], c["chunk"]["chunk_id"]) for c in record["candidates"]] == [
            (1, district)
        ]
        assert record["model_input_chunk_ids"] == [district]
        assert row["response"]["answer"] == f"{district}의 합성 근거"
        assert [c["chunk_id"] for c in row["response"]["citations"]] == [district]
        assert (output / "runs" / f"{row['run_id']}.json").is_file()
