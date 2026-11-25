"""Synthetic source evidence cases for the answer experiment export."""

import csv
import json
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from src.evaluation.answer_experiments import csv_export
from src.generation.answer import generate_answer


def read_rows(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def evidence_runs():
    district = {"district": "서대문구"}
    signage_question = "서대문구에서 깨진 유리를 버릴 때 규격봉투를 써도 되나요?"

    def attempt(
        run_id,
        question_id,
        question,
        conditions,
        candidates,
        selected,
        draft,
        *,
        case_group="development",
        attempt_number=1,
    ):
        def generate(payload):
            actual_inputs.extend(
                csv_export.ModelInput(rank, evidence)
                for rank, evidence in zip(selected, payload["evidence"], strict=True)
            )
            if draft is None:
                raise AssertionError("This case should finish before drafting.")
            return draft

        actual_inputs = []
        evidence = None
        if selected is not None:
            evidence_by_rank = {item.rank: item.evidence for item in candidates}
            evidence = [evidence_by_rank[rank] for rank in selected]
        answer = generate_answer(
            {
                "original_question": question,
                "conditions": conditions,
                "evidence": evidence,
            },
            generate,
        )
        return csv_export.Run(
            run_id=run_id,
            question_id=question_id,
            attempt=attempt_number,
            experiment_kind="synthetic",
            case_group=case_group,
            original_question=question,
            conditions=conditions,
            retriever="synthetic_evidence" if candidates is not None else None,
            candidates=candidates,
            model_inputs=actual_inputs,
            answer=answer,
        )

    signage = csv_export.Candidate(
        1,
        {
            "source": {
                "document_id": "seodaemun-ordinance",
                "parent_mst": "2101297",
                "attachment_id": "160319461",
                "source_location": "별표 6 > 규격봉투판매소 표지판",
            },
            "text": "합성: 판매소 표지판의 글씨와 색상을 규정한다.",
            "chunk_id": None,
        },
    )
    colors = csv_export.Candidate(
        1,
        {
            "source": {
                "document_id": "seodaemun-rules",
                "parent_mst": "2101385",
                "attachment_id": "160561037",
                "source_location": "별표 1 > 공동주택 > 일반용기 설치 > 품목별 색상",
            },
            "text": (
                '합성: 공동주택 "일반용기" 기준\n'
                "캔류 회색, 유리병 주황색, 종이팩 녹색, PET병 노란색, "
                "플라스틱류 파란색, 비닐·필름류 보라색"
            ),
            "chunk_id": None,
        },
    )
    html = csv_export.Candidate(
        1,
        {
            "source": {
                "source_type": "official_operating_guide_html",
                "source_url": "https://www.songpa.go.kr/www/contents.do?key=3153",
                "source_location": "일반주택 표 > 위례동 > 일반·음식물 열",
            },
            "text": "합성: 위례동 일반주택의 일반·음식물 배출요일은 월·수·금",
            "chunk_id": None,
        },
    )
    pdf = csv_export.Candidate(
        2,
        {
            "source": {
                "source_type": "official_linked_PDF",
                "evidence_file": "official-20261014.pdf",
                "pdf_sha256": (
                    "8e0043431030c15a5bd1e0dac1e70dd3de4380bf4f0c6054cebb87e1d07ae7f0"
                ),
                "source_location": "PDF 파일 3쪽 > 인쇄면 4쪽 > 마지막 위례동 행",
            },
            "text": "합성: 위례동 일반주택의 일반·음식물 배출요일은 화·목·일",
            "chunk_id": None,
        },
    )
    return [
        attempt(
            "evidence-pending",
            "evidence-signage",
            signage_question,
            district,
            None,
            None,
            None,
        ),
        attempt(
            "evidence-zero",
            "evidence-signage",
            signage_question,
            district,
            [],
            [],
            None,
            attempt_number=2,
        ),
        attempt(
            "evidence-filtered",
            "evidence-signage",
            signage_question,
            district,
            [signage],
            [],
            None,
            attempt_number=3,
        ),
        attempt(
            "evidence-colors",
            "evidence-colors",
            "서대문구 공동주택 일반용기의 품목별 색은?",
            {**district, "housing_type": "공동주택", "container_type": "일반용기"},
            [colors],
            [1],
            {
                "status": "answered",
                "message": colors.evidence["text"],
                "citation_indices": [0],
            },
        ),
        attempt(
            "evidence-wirye",
            "evidence-wirye",
            "위례동 일반주택 일반·음식물쓰레기의 배출요일은?",
            {
                "district": "송파구",
                "dong": "위례동",
                "housing_type": "일반주택",
                "items": ["일반쓰레기", "음식물쓰레기"],
            },
            [html, pdf],
            [1, 2],
            {
                "status": "source_conflict",
                "conflict_sides": [
                    {"evidence_index": 0, "excerpt": html.evidence["text"]},
                    {"evidence_index": 1, "excerpt": pdf.evidence["text"]},
                ],
            },
            case_group="observation",
        ),
    ]


def write_evidence_sample(directory):
    """Regenerate the synthetic export in a new directory."""
    csv_export.save_experiment_csv(directory, evidence_runs())


class CsvExportTests(TestCase):
    def test_evidence_waiting_zero_and_filtered_remain_distinct_after_reading_both_csvs(
        self,
    ):
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "evidence"
            write_evidence_sample(output)
            runs = {row["run_id"]: row for row in read_rows(output / "runs.csv")}
            candidates = read_rows(output / "candidates.csv")

        self.assertEqual(len(runs), 5)
        self.assertEqual(
            {row["experiment_kind"] for row in runs.values()}, {"synthetic"}
        )
        pending = runs["evidence-pending"]
        self.assertEqual(pending["run_state"], "pending")
        for field in (
            "candidate_count",
            "status",
            "answer",
            "response_ms",
            "evaluation_score",
        ):
            self.assertEqual(pending[field], "")
        zero = runs["evidence-zero"]
        self.assertEqual(zero["run_state"], "completed")
        self.assertEqual(zero["candidate_count"], "0")
        self.assertEqual(zero["status"], "insufficient_evidence")
        self.assertEqual(json.loads(zero["citations_json"]), [])
        filtered = runs["evidence-filtered"]
        self.assertEqual(filtered["candidate_count"], "1")
        self.assertEqual(filtered["status"], "insufficient_evidence")
        self.assertEqual(json.loads(filtered["model_inputs_json"]), [])
        self.assertEqual(
            [
                runs[key]["attempt"]
                for key in ("evidence-pending", "evidence-zero", "evidence-filtered")
            ],
            ["1", "2", "3"],
        )
        self.assertFalse(
            {"evidence-pending", "evidence-zero"}
            & {row["run_id"] for row in candidates}
        )
        signage = next(
            row for row in candidates if row["run_id"] == "evidence-filtered"
        )
        self.assertEqual(signage["attachment_id"], "160319461")
        self.assertEqual(signage["used_in_model_input"], "false")
        self.assertEqual(signage["cited_in_answer"], "false")

    def test_wirye_is_an_observation_with_each_null_chunk_citation_linked(self):
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "evidence"
            write_evidence_sample(output)
            runs = read_rows(output / "runs.csv")
            candidates = read_rows(output / "candidates.csv")

        [observation] = [row for row in runs if row["case_group"] == "observation"]
        self.assertEqual(observation["run_id"], "evidence-wirye")
        self.assertEqual(observation["evaluation_score"], "")
        self.assertEqual(observation["status"], "insufficient_evidence")
        ranked = {
            int(row["rank"]): row
            for row in candidates
            if row["case_group"] == "observation"
        }
        self.assertEqual(set(ranked), {1, 2})
        self.assertIn("key=3153", ranked[1]["source_url"])
        self.assertIn("인쇄면 4쪽", ranked[2]["source_location"])
        self.assertTrue(ranked[2]["pdf_sha256"])
        self.assertIn("월·수·금", observation["answer"])
        self.assertIn("화·목·일", observation["answer"])
        self.assertIn("\n", observation["answer"])
        citations = json.loads(observation["citations_json"])
        model_inputs = json.loads(observation["model_inputs_json"])
        self.assertEqual({item["rank"] for item in model_inputs}, {1, 2})
        self.assertEqual({citation["rank"] for citation in citations}, {1, 2})
        for citation in citations:
            row = ranked[citation["rank"]]
            self.assertEqual(
                row["source_location"], citation["source"]["source_location"]
            )
            self.assertEqual(row["chunk_id"], "")
            self.assertIsNone(citation["source"]["chunk_id"])
            self.assertEqual(row["used_in_model_input"], "true")
            self.assertEqual(row["cited_in_answer"], "true")

    def test_color_evidence_preserves_korean_commas_quotes_and_newlines(self):
        colors = evidence_runs()[3]
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "colors"
            csv_export.save_experiment_csv(output, [colors])
            [row] = read_rows(output / "candidates.csv")
            [run] = read_rows(output / "runs.csv")

        [model_input] = json.loads(run["model_inputs_json"])
        [citation] = json.loads(run["citations_json"])
        self.assertEqual(row["text"], colors.candidates[0].evidence["text"])
        self.assertEqual(model_input["text"], row["text"])
        self.assertEqual(citation["source"]["attachment_id"], "160561037")
        self.assertEqual(run["district"], "서대문구")
        self.assertEqual(run["status"], "answered")

    def test_error_is_retained_with_unknown_candidate_count(self):
        pending = evidence_runs()[0]
        failed = replace(
            pending,
            answer={
                "status": "error",
                "message": "검색 요청 시간이 초과됐습니다.",
                "citations": [],
                "error_kind": "retrieval_timeout",
            },
        )
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "failed"
            csv_export.save_experiment_csv(output, [failed])
            [row] = read_rows(output / "runs.csv")
            candidates = read_rows(output / "candidates.csv")

        self.assertEqual(row["status"], "error")
        self.assertEqual(row["error_kind"], "retrieval_timeout")
        self.assertEqual(row["candidate_count"], "")
        self.assertEqual(candidates, [])

    def test_wrong_source_rank_and_unseen_citation_reject_the_entire_batch(self):
        pending, _, _, colors, observation = evidence_runs()
        wrong_input = csv_export.ModelInput(1, observation.model_inputs[0].evidence)
        cases = [
            replace(colors, model_inputs=[wrong_input]),
            replace(colors, model_inputs=[]),
            replace(colors, run_id=pending.run_id),
        ]
        with TemporaryDirectory() as tmp:
            for invalid in cases:
                with self.subTest(invalid=invalid):
                    output = Path(tmp) / "evidence"
                    with self.assertRaises(ValueError):
                        csv_export.save_experiment_csv(output, [pending, invalid])
                    self.assertFalse(output.exists())

    def test_existing_batch_survives_repeat_writes(self):
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "evidence"
            write_evidence_sample(output)
            before = {path.name: path.read_bytes() for path in output.iterdir()}
            with self.assertRaises(FileExistsError):
                csv_export.save_experiment_csv(output, [])
            after = {path.name: path.read_bytes() for path in output.iterdir()}

        self.assertEqual(after, before)

    def test_second_file_failure_leaves_no_visible_batch(self):
        write = csv_export._write_rows

        def fail_on_candidates(path, columns, rows):
            if path.name == "candidates.csv":
                raise OSError("Candidate write failed")
            write(path, columns, rows)

        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "evidence"
            with patch.object(
                csv_export, "_write_rows", side_effect=fail_on_candidates
            ):
                with self.assertRaises(OSError):
                    write_evidence_sample(output)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_pending_attempt_cannot_have_a_finished_response_time(self):
        pending = replace(evidence_runs()[0], response_ms=3.0)
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "evidence"
            with self.assertRaises(ValueError):
                csv_export.save_experiment_csv(output, [pending])
            self.assertFalse(output.exists())

    def test_answered_requires_at_least_one_grounded_citation(self):
        colors = evidence_runs()[3]
        answer = {**colors.answer, "citations": []}
        for model_inputs in ([], colors.model_inputs):
            with self.subTest(model_inputs=model_inputs), TemporaryDirectory() as tmp:
                output = Path(tmp) / "evidence"
                invalid = replace(colors, answer=answer, model_inputs=model_inputs)
                with self.assertRaises(ValueError):
                    csv_export.save_experiment_csv(output, [invalid])
                self.assertFalse(output.exists())

    def test_model_input_uses_validated_rank_when_evidence_has_a_rank_field(self):
        observation = evidence_runs()[-1]
        html_input, pdf_input = observation.model_inputs
        evidence_with_rank = {**html_input.evidence, "rank": pdf_input.rank}
        observation = replace(
            observation,
            model_inputs=[replace(html_input, evidence=evidence_with_rank), pdf_input],
        )
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "observation"
            csv_export.save_experiment_csv(output, [observation])
            [run] = read_rows(output / "runs.csv")
            candidates = read_rows(output / "candidates.csv")

        expected_ranks = {
            row["source_location"]: int(row["rank"]) for row in candidates
        }
        actual_ranks = {
            item["source"]["source_location"]: item["rank"]
            for item in json.loads(run["model_inputs_json"])
        }
        self.assertEqual(actual_ranks, expected_ranks)
        self.assertEqual(evidence_with_rank["rank"], pdf_input.rank)
