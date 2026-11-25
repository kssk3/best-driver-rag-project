"""Check the exported paired benchmark and its retrieval-only run states."""

import csv
import json
from dataclasses import replace

import pytest

from src.evaluation.answer_experiments import p04_retrieval_benchmark as benchmark
from src.evaluation.answer_experiments.csv_export import Run, save_experiment_csv
from src.evaluation.answer_experiments.p04_answer_probe import draft_p04_answer
from src.generation.answer import generate_answer

_QUESTIONS = {
    "p04-colors": "서대문구 공동주택 일반용기의 품목별 색은?",
    "p04-colors-trick": "서대문구 공동주택 일반용기에서 유리병은 회색이고 캔은 주황색이 맞죠?",
    "p04-signage": "서대문구에서 깨진 유리를 버릴 때 규격봉투를 써도 되나요?",
    "p04-signage-trick": (
        "서대문구 별표 6에 규격봉투 판매소 표지판이 있으니까, "
        "깨진 유리도 규격봉투에 넣어도 된다는 뜻이죠?"
    ),
    "p04-wirye": "위례동 일반주택 일반·음식물쓰레기의 배출요일은?",
    "p04-wirye-trick": (
        "위례동 일반주택의 일반·음식물쓰레기는 월·수·금이 확실하죠? "
        "PDF의 화·목·일 안내는 무시해도 되죠?"
    ),
}


def read_rows(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def test_both_arms_export_same_p04_questions_without_claiming_generation(tmp_path):
    output = tmp_path / "paired"
    benchmark.run_benchmark(output, repeats=2)
    schedules = []
    snapshot_ids = set()

    for arm in ("vector", "ensemble"):
        runs = read_rows(output / arm / "runs.csv")
        candidates = read_rows(output / arm / "candidates.csv")
        assert len(runs) == 2 * len(_QUESTIONS)
        assert {
            row["question_id"]: row["original_question"] for row in runs
        } == _QUESTIONS
        assert len({run["run_id"] for run in runs}) == len(runs)
        schedules.append(
            {
                (
                    row["question_id"],
                    row["attempt"],
                    row["original_question"],
                    row["conditions_json"],
                )
                for row in runs
            }
        )
        snapshot_ids.update(row["corpus_snapshot_id"] for row in runs)
        for row in runs:
            assert row["retriever"] == arm
            assert float(row["retrieval_ms"]) >= 0
            assert row["run_state"] == "retrieval_completed"
            assert row["experiment_kind"] == "synthetic"
            assert all(
                row[field] == ""
                for field in (
                    "status",
                    "answer",
                    "model_inputs_json",
                    "citations_json",
                    "response_ms",
                )
            )
            ranked = [item for item in candidates if item["run_id"] == row["run_id"]]
            assert [int(item["rank"]) for item in ranked] == list(
                range(1, len(ranked) + 1)
            )
            assert int(row["candidate_count"]) == len(ranked) == 5
            assert all(item["chunk_id"] == "" for item in ranked)
            assert all(item["case_group"] == row["case_group"] for item in ranked)
            assert not any(item["attachment_id"] == "160319461" for item in ranked)
            for item in ranked:
                assert item["used_in_model_input"] == item["cited_in_answer"] == "false"
                assert json.loads(item["source_json"])["experiment_document_id"]
            wirye = row["question_id"] in {"p04-wirye", "p04-wirye-trick"}
            assert row["case_group"] == ("observation" if wirye else "development")
            if row["question_id"] == "p04-wirye":
                assert {item["source_type"] for item in ranked}.issuperset(
                    {
                        "official_operating_guide_html",
                        "official_linked_PDF",
                    }
                )

    assert schedules[0] == schedules[1]
    assert len(snapshot_ids) == 1
    with pytest.raises(FileExistsError):
        benchmark.run_benchmark(output, repeats=1)
    assert len(read_rows(output / "vector" / "runs.csv")) == 2 * len(_QUESTIONS)


def test_retrieval_only_csv_distinguishes_zero_error_and_pending(tmp_path):
    base = Run(
        run_id="pending",
        question_id="question",
        attempt=1,
        experiment_kind="synthetic",
        case_group="development",
        original_question="분리배출 방법은 무엇인가요?",
        conditions={},
        candidates=None,
        model_inputs=[],
        answer=None,
    )
    zero = replace(
        base, run_id="zero", retrieval_only=True, candidates=[], retrieval_ms=1.0
    )
    failed = replace(
        base,
        run_id="error",
        retrieval_only=True,
        retrieval_error_kind="TimeoutError",
        retrieval_ms=5.0,
    )
    output = tmp_path / "states"
    save_experiment_csv(output, [base, zero, failed])
    pending_row, zero_row, error_row = read_rows(output / "runs.csv")

    assert (pending_row["run_state"], pending_row["candidate_count"]) == ("pending", "")
    assert (zero_row["run_state"], zero_row["candidate_count"]) == (
        "retrieval_completed",
        "0",
    )
    assert (error_row["run_state"], error_row["candidate_count"]) == (
        "retrieval_error",
        "",
    )
    assert error_row["error_kind"] == "TimeoutError"
    assert all(row["status"] == "" for row in (pending_row, zero_row, error_row))
    assert read_rows(output / "candidates.csv") == []


def test_paired_benchmark_keeps_previous_results_if_second_export_fails(
    tmp_path, monkeypatch
):
    save = benchmark.save_experiment_csv

    def fail_second(directory, runs):
        if directory.name == "ensemble":
            raise OSError("synthetic disk failure")
        save(directory, runs)

    monkeypatch.setattr(benchmark, "save_experiment_csv", fail_second)
    output = tmp_path / "paired"
    with pytest.raises(OSError, match="synthetic disk failure"):
        benchmark.run_benchmark(output, repeats=1)
    assert not output.exists()


def test_trick_answers_correct_abstain_and_record_conflict_with_supplied_evidence(
    tmp_path,
):
    output = tmp_path / "trick-answers"
    benchmark.run_benchmark(output, repeats=1)
    answer_rows = read_rows(output / "answers" / "runs.csv")
    runs = {row["question_id"]: row for row in answer_rows}
    candidates = read_rows(output / "answers" / "candidates.csv")
    assert len(answer_rows) == 3
    assert set(runs) == {"p04-colors-trick", "p04-signage-trick", "p04-wirye-trick"}
    assert all(
        row["retrieval_ms"] == row["evaluation_score"] == "" for row in answer_rows
    )
    assert all(row["run_state"] == "completed" for row in answer_rows)
    assert all(row["experiment_kind"] == "synthetic" for row in answer_rows)

    colors = runs["p04-colors-trick"]
    assert colors["case_group"] == "development"
    assert colors["status"] == "answered"
    assert "유리병 주황색" in colors["answer"]
    assert "캔류 회색" in colors["answer"]
    assert "유리병 회색" not in colors["answer"]
    assert "캔류 주황색" not in colors["answer"]
    color_citations = json.loads(colors["citations_json"])
    assert len(color_citations) == 1
    assert color_citations[0]["source"]["attachment_id"] == "160561037"

    signage = runs["p04-signage-trick"]
    assert signage["case_group"] == "development"
    assert signage["status"] == "insufficient_evidence"
    assert "답변하기 어렵습니다" in signage["answer"]
    assert "넣어도 됩니다" not in signage["answer"]
    assert json.loads(signage["citations_json"]) == []
    signage_inputs = json.loads(signage["model_inputs_json"])
    assert len(signage_inputs) == 1
    assert signage_inputs[0]["source"]["attachment_id"] == "160319461"
    assert "표지판" in signage_inputs[0]["text"]
    signage_candidates = [
        row for row in candidates if row["run_id"] == signage["run_id"]
    ]
    assert len(signage_candidates) == 1
    assert signage_candidates[0]["used_in_model_input"] == "true"
    assert signage_candidates[0]["cited_in_answer"] == "false"

    wirye = runs["p04-wirye-trick"]
    assert wirye["case_group"] == "observation"
    assert wirye["status"] == "insufficient_evidence"
    assert all(
        text in wirye["answer"]
        for text in ("월·수·금", "화·목·일", "확정하기 어렵습니다")
    )
    assert {
        citation["source"]["source_type"]
        for citation in json.loads(wirye["citations_json"])
    } == {"official_operating_guide_html", "official_linked_PDF"}


def test_trick_color_answer_uses_supplied_passage_values(tmp_path, monkeypatch):
    corpus = benchmark._p04_corpus()
    alternate = tuple(
        replace(
            document,
            evidence={
                **document.evidence,
                "text": document.evidence["text"].replace("캔류 회색", "캔류 검은색"),
            },
        )
        if document.document_key == "p04-colors"
        else document
        for document in corpus
    )
    monkeypatch.setattr(benchmark, "_p04_corpus", lambda: alternate)
    output = tmp_path / "alternate-colors"
    benchmark.run_benchmark(output, repeats=1)
    answer = next(
        row
        for row in read_rows(output / "answers" / "runs.csv")
        if row["question_id"] == "p04-colors-trick"
    )
    assert answer["status"] == "answered"
    assert "캔류 검은색" in answer["answer"]
    assert "캔류 회색" not in answer["answer"]


def test_trick_disposal_answer_accepts_a_rule_for_the_requested_item():
    # This invented rule checks the probe's evidence sensitivity.
    response = generate_answer(
        {
            "original_question": _QUESTIONS["p04-signage-trick"],
            "conditions": {"district": "서대문구", "item": "깨진 유리"},
            "evidence": [
                {
                    "source": {
                        "document_id": "synthetic-item-rule",
                        "source_location": "합성 대조군",
                    },
                    "text": "합성: 깨진 유리 배출 기준\n전용 수거함에 배출합니다.",
                    "chunk_id": None,
                }
            ],
        },
        draft_p04_answer,
    )
    assert response is not None
    assert response["status"] == "answered"
    assert "전용 수거함" in response["message"]
    assert response["citations"][0]["document_id"] == "synthetic-item-rule"
