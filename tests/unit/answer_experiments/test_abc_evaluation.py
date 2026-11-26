"""외부 모델 경계만 대체하고 평가·채점 CLI 사이의 저장 계약을 검증한다."""

import csv
import json
import re
import sys
from types import SimpleNamespace

import langchain_openai
import pytest
from langchain_core.messages import AIMessage

from scripts import evaluate, score_answers
from src.contracts import Chunk
from src.infrastructure import chat_models
from src.infrastructure.embeddings import create_openai_embeddings
from src.infrastructure.stores import save_index
from src.ingestion.indexing import build_index

FACTORY = "src.evaluation.answer_experiments.abc_runtimes:create_abc_runtimes"


def table(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


@pytest.fixture
def experiment(tmp_path, monkeypatch):
    from ragas.llms.base import InstructorLLM

    trace = SimpleNamespace(
        queries=[], reranks=[], generations=[], judgments=[], failure=None
    )
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test")
    monkeypatch.setenv("RAGAS_DO_NOT_TRACK", "true")

    class Embeddings:
        def __init__(self, **kwargs):
            self.openai_api_base = "https://api.openai.com/v1"

        def embed_documents(self, texts):
            return [[1.0, 0.0] for _ in texts]

        def embed_query(self, text):
            trace.queries.append(text)
            return [1.0, 0.0]

    class Chat:
        def __init__(self, *, model, **kwargs):
            self.model = model

        def bind(self, **options):
            return self

        def invoke(self, messages):
            payload = json.loads(messages[-1][1])
            if self.model == "rank-model":
                passages = [p["text"] for p in payload["passages"]]
                trace.reranks.append(passages)
                scores = [10 if "EVID_5" in p else 0 for p in passages]
                if trace.failure == "retrieve":
                    scores.pop()
                response = {"scores": scores}
            else:
                assert self.model == "answer-model"
                texts = [e["text"] for e in payload["evidence"]]
                trace.generations.append(texts)
                if trace.failure == "generate" and "EVID_5" in texts[0]:
                    return AIMessage(content="{}")
                response = {
                    "status": "answered",
                    "message": texts[0],
                    "citation_indices": [0],
                }
            return AIMessage(content=json.dumps(response, ensure_ascii=False))

    async def judge(self, prompt, response_model):
        if response_model.__name__ == "StatementGeneratorOutput":
            return response_model(statements=["진술"])
        markers = re.findall(r"EVID_\d+", prompt)
        trace.judgments.append(markers)
        return response_model(
            statements=[
                {
                    "statement": "진술",
                    "reason": "모의",
                    "verdict": int(markers[0] != "EVID_0"),
                }
            ]
        )

    monkeypatch.setattr(langchain_openai, "OpenAIEmbeddings", Embeddings)
    monkeypatch.setattr(chat_models, "ChatOpenAI", Chat)
    monkeypatch.setattr(InstructorLLM, "agenerate", judge)

    chunks = [
        Chunk(
            chunk_id=f"id-{i}",
            source_document_id="문서",
            source_document_version="1",
            title="합성",
            content_format="html",
            content=f"EVID_{i}" + (" 페트병" if i == 1 else ""),
            source_url="https://example.org",
            source_location=str(i),
            scope_type="district",
            districts=["서대문구"],
            chunking_version="1",
        )
        for i in range(6)
    ]
    index = tmp_path / "index.json"
    save_index(build_index(chunks, create_openai_embeddings("embed-model")), index)
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "index_path": str(index),
                "pipeline": {
                    "top_k": 5,
                    "max_context_chars": 400,
                    "versions": {
                        "model": "answer-model",
                        "reranker_model": "rank-model",
                    },
                },
            }
        )
    )

    def run(failure=None):
        trace.failure = failure
        cases = tmp_path / "cases.json"
        cases.write_text(
            json.dumps(
                [
                    {
                        "case_id": "q1",
                        "question": "페트병",
                        "district": "송파구" if failure == "empty" else "서대문구",
                        "allowed_chunk_ids": ["id-5"],
                    }
                ]
            )
        )
        out = tmp_path / "runs"
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "evaluate",
                "--cases",
                str(cases),
                "--settings",
                str(settings),
                "--output-dir",
                str(out),
                "--factory",
                FACTORY,
            ],
        )
        if failure in {"retrieve", "generate"}:
            with pytest.raises(SystemExit) as err:
                evaluate.main()
            assert err.value.code == 1
        else:
            evaluate.main()
        return out

    return run, trace


def score(out, path):
    score_answers.main(
        [
            "--evaluation",
            str(out / "evaluation.json"),
            "--cases-csv",
            str(out / "cases.csv"),
            "--output-dir",
            str(path),
            "--judge-model",
            "gpt-4o-mini",
        ]
    )
    return table(path / "scores.csv")


def test_abc_cli_preserves_reranked_evidence_and_scores(experiment, tmp_path):
    run, trace = experiment
    out = run()
    attempts = json.loads((out / "evaluation.json").read_text())
    runs = table(out / "runs.csv")
    scores = score(out, tmp_path / "scored")
    cases = table(out / "cases.csv")
    candidates = table(out / "candidates.csv")
    assert len(cases) == 1 and len({r["run_id"] for r in runs}) == 3
    assert trace.queries == ["페트병"] * 3
    assert len(trace.reranks) == 1
    assert trace.reranks[0][:5] == trace.generations[1]
    assert trace.reranks[0][5:] == ["EVID_5"]
    assert [g[0] for g in trace.generations] == ["EVID_0", "EVID_1 페트병", "EVID_5"]
    for i, (v, attempt, row, s) in enumerate(
        zip("ABC", attempts, runs, scores, strict=True)
    ):
        run_id = row["run_id"]
        original = json.loads((out / "runs" / f"{run_id}.json").read_text())
        assert original == attempt["record"]
        assert run_id == attempt["run_id"] == original["run_id"] == s["run_id"]
        assert row["dataset_id"] == cases[0]["dataset_id"] == s["dataset_id"]
        assert row["case_id"] == cases[0]["case_id"] == s["case_id"] == "q1"
        assert (
            attempt["configuration"]
            == row["configuration"]
            == s["configuration"]
            == s["variant"]
            == original["options"]["variant"]
            == v
        )
        assert (row["rewrite_enabled"], row["run_kind"], row["retrieval_status"]) == (
            "false",
            "rag",
            "ok",
        )
        assert (row["top_k"], row["max_context_chars"]) == ("5", "400")
        assert (s["comparison_eligible"], s["score"]) == (
            "true",
            ["0.0", "1.0", "1.0"][i],
        )
        ids = original["model_input_chunk_ids"]
        saved = [r for r in candidates if r["run_id"] == run_id]
        assert [r["chunk_id"] for r in saved] == ids
        assert [r["text"] for r in saved] == trace.generations[i]
        assert trace.judgments[i] == [text.split()[0] for text in trace.generations[i]]
        versions = json.loads(row["versions_json"])
        assert versions == json.loads(s["versions_json"])
        assert versions["model"] == "answer-model"
        assert ("reranker_model" in versions) == (v == "C")
        if v == "C":
            assert ids[0] == "id-5"
            assert (
                versions["reranker_model"] == "rank-model"
                and versions["reranker_prompt"]
            )
            assert (
                versions["candidate_policy"]
                != json.loads(runs[1]["versions_json"])["candidate_policy"]
            )
    for field in ["index_id", "embedding", "chunking_version", "model"]:
        assert len({row[field] for row in runs}) == 1

    # 같은 보관본에서 A의 구성 이름만 손상되면 정상 B/C만 다시 채점한다.
    attempts[0]["configuration"] = "B"
    (out / "evaluation.json").write_text(json.dumps(attempts))
    trace.judgments.clear()
    with pytest.raises(SystemExit) as err:
        score(out, tmp_path / "tampered")
    assert err.value.code == 1
    bad, *others = table(tmp_path / "tampered/scores.csv")
    assert (bad["reason"], bad["score"]) == ("run_configuration_mismatch", "")
    assert [r["score"] for r in others] == ["1.0", "1.0"]
    assert trace.judgments == [
        [text.split()[0] for text in g] for g in trace.generations[1:]
    ]


@pytest.mark.parametrize("stage", ["retrieve", "generate"])
def test_c_failure_keeps_ab_scores_and_original_stage(experiment, tmp_path, stage):
    run, trace = experiment
    out = run(stage)
    a, b, c = table(out / "runs.csv")
    assert a["status"] == b["status"] == "answered"
    assert c["status"] == "error" and c["failed_stage"] == stage
    assert c["retrieval_status"] == ("error" if stage == "retrieve" else "ok")
    assert c["candidate_count"] == ("" if stage == "retrieve" else "5")
    assert (out / "runs" / (c["run_id"] + ".json")).is_file()
    scores = score(out, tmp_path / "scored")
    assert [r["score"] for r in scores] == ["0.0", "1.0", ""]
    assert scores[2]["reason"] == "response_error" and len(trace.judgments) == 2


def test_empty_candidates_skip_model_calls(experiment, tmp_path):
    run, trace = experiment
    out = run("empty")
    assert [row["candidate_count"] for row in table(out / "runs.csv")] == ["0"] * 3
    assert [r["score"] for r in score(out, tmp_path / "scored")] == [""] * 3
    assert not trace.reranks and not trace.generations and not trace.judgments


@pytest.mark.parametrize(
    ("pipeline", "code"),
    [
        ({"rewrite_enabled": True}, "evaluation.unsupported_configuration"),
        ({"run_kind": "fixed_evidence"}, "evaluation.unsupported_configuration"),
        ({"versions": {"model": "answer"}}, "evaluation.missing_reranker_model"),
    ],
)
def test_invalid_comparison_settings_fail_before_loading_index(pipeline, code):
    from src.config import RuntimeSettings
    from src.evaluation.answer_experiments.abc_runtimes import create_abc_runtimes
    from src.pipeline import PipelineConfigurationError

    with pytest.raises(PipelineConfigurationError) as error:
        create_abc_runtimes(RuntimeSettings.model_validate({"pipeline": pipeline}))
    assert error.value.code == code


def test_comparison_options_do_not_leak_across_runs(experiment, tmp_path):
    from src.config import load_settings
    from src.evaluation.answer_experiments.abc_runtimes import create_abc_runtimes

    settings = load_settings(tmp_path / "settings.json")
    settings.pipeline.versions.update(
        rewrite="old", rewrite_catalog="old", reranker_prompt="old"
    )
    before = settings.model_dump()
    pipelines = create_abc_runtimes(settings)
    assert settings.model_dump() == before
    for pipeline in pipelines.values():
        assert "rewrite" not in pipeline.options.versions
        assert "rewrite_catalog" not in pipeline.options.versions
    pipelines["A"].options.versions["model"] = "changed"
    pipelines["A"].options.top_k = 1
    for other in (pipelines["B"].options, pipelines["C"].options, settings.pipeline):
        assert other.versions["model"] == "answer-model" and other.top_k == 5
