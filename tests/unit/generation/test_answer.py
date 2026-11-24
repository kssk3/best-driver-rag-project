"""Synthetic P04 development and generation contract cases."""

from unittest import TestCase
from unittest.mock import Mock

from src.generation import answer


class AnswerPreflightTests(TestCase):
    def test_pending_versus_completed_empty_evidence(self):
        draft_answer = Mock()
        request = {
            "original_question": "서대문구에서 깨진 유리는 규격봉투에 버리나요?",
            "conditions": {"district": "서대문구", "item": "깨진 유리"},
            "evidence": None,
        }
        # The excluded signage (seodaemun-ordinance, MST 2101297, attachment
        # 160319461) is upstream metadata and never enters the completed input.
        self.assertIsNone(answer.generate_answer(request, draft_answer))

        response = answer.generate_answer({**request, "evidence": []}, draft_answer)
        self.assertEqual(response["status"], "insufficient_evidence")
        self.assertEqual(response["citations"], [])
        self.assertIn("확인", response["message"])
        draft_answer.assert_not_called()

    def test_rejects_malformed_envelope_even_while_evidence_is_pending(self):
        for request in (
            {"evidence": None},
            {"original_question": " ", "conditions": {}, "evidence": None},
            {"original_question": "배출 방법은?", "conditions": None, "evidence": None},
        ):
            with self.subTest(request=request):
                draft_answer = Mock()
                response = answer.generate_answer(request, draft_answer)

                self.assertEqual(response["status"], "error")
                self.assertEqual(response["error_kind"], "invalid_input")
                draft_answer.assert_not_called()


class GroundedAnswerTests(TestCase):
    def test_apartment_bin_colors_keep_scope_and_use_supplied_source(self):
        source = {
            "document_id": "seodaemun-rules",
            "parent_mst": "2101385",
            "attachment_id": "160561037",
            "source_location": "별표 1 > 공동주택 > 일반용기 설치 > 품목별 색상",
        }
        colors = (
            "캔류 회색",
            "유리병 주황색",
            "종이팩 녹색",
            "PET병 노란색",
            "플라스틱류 파란색",
            "비닐·필름류 보라색",
        )
        wording = "공동주택 일반용기 설치 기준은 " + ", ".join(colors) + "입니다."
        request = {
            "original_question": "서대문구 공동주택 일반용기의 품목별 색은?",
            "conditions": {
                "district": "서대문구",
                "housing_type": "공동주택",
                "container_type": "일반용기",
            },
            "evidence": [{"source": source, "text": wording, "chunk_id": None}],
        }
        draft_answer = Mock(
            return_value={"status": "answered", "message": wording, "citation_indices": [0]}
        )

        response = answer.generate_answer(request, draft_answer)

        self.assertEqual(response["status"], "answered")
        self.assertIn("공동주택 일반용기 설치 기준", response["message"])
        for fact in colors:
            self.assertIn(fact, response["message"])
        self.assertEqual(
            response["citations"],
            [{**source, "chunk_id": None, "chunk_id_status": "unconfirmed"}],
        )
        draft_answer.assert_called_once_with(request)


class ClarificationTests(TestCase):
    def test_asks_only_for_declared_missing_conditions(self):
        request = {
            "original_question": "종이팩 배출 방법은 어떻게 되나요?",
            "conditions": {"item": "종이팩", "district": "  "},
            "required_conditions": {"item": "품목", "district": "자치구"},
            "evidence": [],
        }
        draft_answer = Mock()

        response = answer.generate_answer(request, draft_answer)

        self.assertEqual(response["status"], "needs_clarification")
        self.assertIn("자치구", response["message"])
        self.assertNotIn("품목", response["message"])
        self.assertEqual(response["citations"], [])
        draft_answer.assert_not_called()

    def test_missing_evidence_key_is_a_contract_error(self):
        request = {"original_question": "배출 방법은?", "conditions": {}}
        draft_answer = Mock()

        response = answer.generate_answer(request, draft_answer)

        self.assertEqual(response["status"], "error")
        self.assertEqual(response["error_kind"], "invalid_input")
        draft_answer.assert_not_called()


class InvalidDraftTests(TestCase):
    def setUp(self):
        self.request = {
            "original_question": "종이팩은 어떻게 버리나요?",
            "conditions": {},
            "evidence": [
                {
                    "source": {
                        "source_url": "https://example.org/guide",
                        "source_location": "종이팩 항목",
                    },
                    "text": "종이팩 분리배출 합성 안내",
                    "chunk_id": None,
                },
            ],
        }

    def test_answer_requires_refs_to_evidence_supplied_for_this_request(self):
        for refs in ([], [1], [-1], ["0"], [False]):
            with self.subTest(refs=refs):
                draft_answer = Mock(
                    return_value={
                        "status": "answered",
                        "message": "합성 응답입니다.",
                        "citation_indices": refs,
                    }
                )

                response = answer.generate_answer(self.request, draft_answer)

                self.assertEqual(response["status"], "error")
                self.assertEqual(response["citations"], [])

    def test_uses_request_provenance_even_after_provider_mutation(self):
        original_url = self.request["evidence"][0]["source"]["source_url"]

        def draft_answer(model_input):
            model_input["evidence"][0]["source"]["source_url"] = (
                "https://example.org/other"
            )
            return {
                "status": "answered",
                "message": "합성 응답입니다.",
                "citation_indices": [0],
            }

        response = answer.generate_answer(self.request, draft_answer)

        self.assertEqual(response["citations"][0]["source_url"], original_url)
        self.assertEqual(self.request["evidence"][0]["source"]["source_url"], original_url)

    def test_generation_failure_returns_error(self):
        draft_answer = Mock(side_effect=TimeoutError("provider detail"))

        response = answer.generate_answer(self.request, draft_answer)

        self.assertEqual(response["status"], "error")
        self.assertEqual(response["error_kind"], "generation_failed")
        self.assertEqual(response["citations"], [])
        self.assertNotIn("provider detail", response["message"])

    def test_conflict_excerpt_must_come_from_its_cited_source(self):
        request = {
            **self.request,
            "evidence": [
                *self.request["evidence"],
                {
                    "source": {
                        "source_url": "https://example.org/other-guide",
                        "source_location": "종이팩 항목",
                    },
                    "text": "종이팩을 금요일에 수거",
                    "chunk_id": None,
                },
            ],
        }
        draft_answer = Mock(
            return_value={
                "status": "source_conflict",
                "conflict_sides": [
                    {"evidence_index": 0, "excerpt": "종이팩을 금요일에 수거"},
                    {"evidence_index": 1, "excerpt": "종이팩을 토요일에 수거"},
                ],
            }
        )

        response = answer.generate_answer(request, draft_answer)

        self.assertEqual(response["status"], "error")
        self.assertEqual(response["error_kind"], "invalid_draft")
        self.assertEqual(response["citations"], [])


    def test_generated_body_accepts_prose_and_leaves_links_in_citations(self):
        for markup in (
            "https://example.org/unverified",
            "[안내](//example.org/unverified)",
            "www.example.org/unverified",
            '<a href="https://example.org/unverified">안내</a>',
            "[안내][출처]\n[출처]: example.org/unverified",
        ):
            with self.subTest(markup=markup):
                draft_answer = Mock(
                    return_value={
                        "status": "answered",
                        "message": f"종이팩 배출 안내는 {markup}에 있습니다.",
                        "citation_indices": [0],
                    }
                )
                response = answer.generate_answer(self.request, draft_answer)

                self.assertEqual(response["status"], "error")
                self.assertEqual(response["error_kind"], "invalid_draft")
                self.assertNotIn(markup, response["message"])

        message = "[수거 범위] (공동주택) 캔·유리병을 오전 09:00에 수거합니다."
        draft_answer = Mock(
            return_value={"status": "answered", "message": message, "citation_indices": [0]}
        )
        response = answer.generate_answer(self.request, draft_answer)

        self.assertEqual(response["message"], message)
        self.assertEqual(
            response["citations"][0]["source_url"], "https://example.org/guide"
        )

    def test_conflict_excerpts_cannot_add_links_to_message(self):
        sources = [
            {"source_url": "https://example.org/guide"},
            {"source_url": "https://example.org/other-guide"},
        ]
        excerpts = ["수거요일은 월요일 (www.example.org/unverified)", "수거요일은 목요일"]
        response = self._generate_conflict(sources, excerpts)

        self.assertEqual(response["status"], "error")
        self.assertNotIn("www.example.org/unverified", response["message"])

    def test_conflict_rejects_same_source_with_mixed_metadata(self):
        first = {"source_url": "https://example.org/guide?key=3153"}
        for other in (
            {"document_id": "guide-id", "source_url": first["source_url"]},
            {"pdf_sha256": "a" * 64, "source_url": f'{first["source_url"]}#page=3'},
            {"document_version": "revision", "source_url": first["source_url"]},
        ):
            with self.subTest(other=other):
                response = self._generate_conflict(
                    [first, other], ["수거요일은 월요일", "수거요일은 목요일"]
                )

                self.assertEqual(response["status"], "error")
                self.assertEqual(response["citations"], [])

    def test_conflict_preserves_qualified_annexes_and_versions(self):
        common = {"document_id": "guide-id", "source_url": "https://example.org/guide"}
        for qualifiers in (
            ({"attachment_id": "1"}, {"attachment_id": "2"}),
            ({"parent_mst": "1"}, {"parent_mst": "2"}),
            ({"pdf_sha256": "a" * 64}, {"pdf_sha256": "b" * 64}),
            ({"document_version": "old"}, {"document_version": "new"}),
        ):
            with self.subTest(qualifiers=qualifiers):
                response = self._generate_conflict(
                    [{**common, **qualifiers[0]}, {**common, **qualifiers[1]}],
                    ["수거요일은 월요일", "수거요일은 목요일"],
                )

                self.assertEqual(response["status"], "insufficient_evidence")
                self.assertEqual(len(response["citations"]), 2)

    def _generate_conflict(self, sources, excerpts):
        evidence = [
            {
                "source": {**source, "source_location": f"수거요일 항목 {position}"},
                "text": excerpt,
                "chunk_id": None,
            }
            for position, (source, excerpt) in enumerate(
                zip(sources, excerpts, strict=True)
            )
        ]
        draft_answer = Mock(
            return_value={
                "status": "source_conflict",
                "conflict_sides": [
                    {"evidence_index": index, "excerpt": excerpt}
                    for index, excerpt in enumerate(excerpts)
                ],
            }
        )
        return answer.generate_answer({**self.request, "evidence": evidence}, draft_answer)
