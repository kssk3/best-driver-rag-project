"""Synthetic P04 observation cases, separate from development scoring."""

from unittest import TestCase
from unittest.mock import Mock

from src.generation import answer


class AnswerObservationTests(TestCase):
    def test_wirye_schedule_conflict_reports_both_sources_and_abstains(self):
        html = {
            "source_type": "official_operating_guide_html",
            "source_url": "https://www.songpa.go.kr/www/contents.do?key=3153",
            "source_location": "위례동 일반주택 일반·음식물 배출요일 열",
        }
        pdf = {
            "source_type": "official_linked_PDF",
            "evidence_file": "official-20261014.pdf",
            "pdf_sha256": (
                "8e0043431030c15a5bd1e0dac1e70dd3de4380bf4f0c6054cebb87e1d07ae7f0"
            ),
            "source_location": "PDF 파일 3쪽 > 인쇄면 4쪽 > 마지막 위례동 행",
        }
        html_excerpt = "위례동 일반주택의 일반·음식물 배출요일은 월·수·금"
        pdf_excerpt = "위례동 일반주택의 일반·음식물 배출요일은 화·목·일"
        request = {
            "original_question": "위례동 일반주택의 일반·음식물쓰레기 배출요일은?",
            "conditions": {
                "district": "송파구",
                "dong": "위례동",
                "housing_type": "일반주택",
                "items": ["일반쓰레기", "음식물쓰레기"],
            },
            "evidence": [
                {"source": html, "text": html_excerpt, "chunk_id": None},
                {"source": pdf, "text": pdf_excerpt, "chunk_id": None},
            ],
        }
        draft_answer = Mock(return_value={
            "status": "source_conflict",
            "conflict_sides": [
                {"evidence_index": 0, "excerpt": html_excerpt},
                {"evidence_index": 1, "excerpt": pdf_excerpt},
            ],
            "message": "월·수·금으로 확정합니다.",
        })

        response = answer.generate_answer(request, draft_answer)

        self.assertEqual(response["status"], "insufficient_evidence")
        self.assertIn(f"[1] {html_excerpt}", response["message"])
        self.assertIn(f"[2] {pdf_excerpt}", response["message"])
        self.assertIn("확정하기 어렵습니다", response["message"])
        self.assertNotIn("월·수·금으로 확정합니다", response["message"])
        self.assertEqual(response["citations"], [
            {**html, "chunk_id": None, "chunk_id_status": "unconfirmed"},
            {**pdf, "chunk_id": None, "chunk_id_status": "unconfirmed"},
        ])
