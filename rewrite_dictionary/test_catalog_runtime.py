"""실행기와 지역별 검토 조회가 JSON의 규칙을 지키는지 확인한다."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from rewrite_dictionary.prompt_context import make_prompt_context_builder
from rewrite_dictionary.runtime import (
    CATALOG_PATH,
    make_question_rewriter,
    review_district_records,
)


class CatalogRuntimeTests(TestCase):
    def test_rewrite_reads_aliases_and_stage_order_from_supplied_json(self):
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        catalog["item_aliases"] = {"회귀별칭": "회귀표준어"}
        catalog["rewrite_rules"]["search_language_order"] = []

        with TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            path.write_text(json.dumps(catalog, ensure_ascii=False), encoding="utf-8")
            rewrite = make_question_rewriter(path)
            self.assertEqual(
                rewrite("잠실동에서 회귀별칭 워떻게 버려?"),
                "잠실동에서 회귀별칭 워떻게 버려? (회귀표준어)",
            )

    def test_rewrite_respects_item_boundaries_and_preserves_conditions(self):
        rewrite = make_question_rewriter()
        cases = {
            "서대문구 깨진 유리 병이랑 음쓰 봉투는 어케 버려?": (
                "서대문구 깨진 유리 병이랑 음쓰 봉투는 어떻게 버려? (깨진 유리병) (음식물류봉투)"
            ),
            "런닝머신 매트와 LED전구 커버는 어떻게 버려요?": (
                "런닝머신 매트와 LED전구 커버는 어떻게 버려요? (러닝머신 매트) (LED 전구 커버)"
            ),
            "송파구 불투명 패트병과 PC 본체를 버려요?": (
                "송파구 불투명 패트병과 PC 본체를 버려요? (컴퓨터 본체)"
            ),
            "우유팩하고 안 씻은 두유팩은?": "우유팩하고 안 씻은 두유팩은? (종이팩)",
            "스타일러": "스타일러 (의류관리기)",
            "헤어 스타일러를 버려요?": "헤어 스타일러를 버려요?",
        }
        for question, expected in cases.items():
            with self.subTest(question=question):
                self.assertEqual(rewrite(question), expected)
                self.assertEqual(rewrite(expected), expected)

    def test_new_material_codes_require_material_context(self):
        rewrite = make_question_rewriter()
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        official_names = catalog["official_source_lookup"]["material_names"][
            "names_by_code"
        ]
        for code in ("PBS", "PBSA", "PBAT", "PBT", "POM"):
            with self.subTest(code=code):
                question = f"{code} 수지로 된 용기에요."
                self.assertEqual(
                    rewrite(question), f"{question} ({official_names[code]})"
                )
                unrelated = f"{code} 장비를 버려요?"
                self.assertEqual(rewrite(unrelated), unrelated)

    def test_expanded_search_terms_preserve_parts_and_exclusions(self):
        rewrite = make_question_rewriter()
        cases = {
            "종이 뽁뽁이랑 LED전구 소켓은 우야노?": (
                "종이 뽁뽁이랑 LED전구 소켓은 어떻게 해야 하나요? (종이 완충재) (LED 전구 소켓)"
            ),
            "비닐 붙은 종이 뽁뽁이 봉투는 어떻게 버려요?": (
                "비닐 붙은 종이 뽁뽁이 봉투는 어떻게 버려요?"
            ),
            "패트병 말고 전등 기구만 버려요.": "패트병 말고 전등 기구만 버려요. (조명기구)",
            "투명 패트병이랑 폐건전지는 우야노?": (
                "투명 패트병이랑 폐건전지는 어떻게 해야 하나요? (전지류) (페트병)"
            ),
            "안 깨진 유리벵과 LED전구는?": "안 깨진 유리벵과 LED전구는? (LED 전구)",
            "스치로폼이랑 족발뼈는 우야노?": (
                "스치로폼이랑 족발뼈는 어떻게 해야 하나요? (돼지뼈) (스티로폼)"
            ),
            "laptop charger랑 LED bulb cover는 어떻게 버려요?": (
                "노트북 충전기랑 LED 전구 커버는 어떻게 버려요?"
            ),
        }
        for question, expected in cases.items():
            with self.subTest(question=question):
                self.assertEqual(rewrite(question), expected)
                self.assertEqual(rewrite(expected), expected)

    def test_prompt_context_includes_only_the_requested_items_and_place(self):
        build = make_prompt_context_builder()
        question = (
            "마천2동 실험실에서 안 씻은 reagent bottle cap이랑 포도 씨앗은 어디다 버려?"
        )
        result = build(question, district="송파구", dong="마천2동")
        self.assertEqual(result["question"], question)
        self.assertEqual((result["district"], result["dong"]), ("송파구", "마천2동"))
        self.assertEqual(
            result["language_normalized_question"],
            "마천2동 실험실에서 안 씻은 시약병 뚜껑이랑 포도 씨앗은 어디에 버려?",
        )
        self.assertEqual(result["item_aliases"], {"포도 씨앗": "포도씨"})
        self.assertEqual(
            {item["item"] for item in result["item_context"]}, {"포도씨", "시약병 뚜껑"}
        )
        self.assertEqual(
            [place["place"] for place in result["facility_context"]], ["실험실"]
        )
        serialized = json.dumps(result, ensure_ascii=False)
        for marker in ("http", "source_ids", "example_item_keys", "expected", "수수료"):
            self.assertNotIn(marker, serialized)

    def test_prompt_context_preserves_unresolved_items_and_conditions(self):
        build = make_prompt_context_builder()
        question = "스타일러 말고 헤어 스타일러랑 안 깨진 폐 형광등, 내용물이 남은 농약 공병은?"
        result = build(question)
        self.assertEqual(result["question"], question)
        self.assertIsNone(result["district"])
        self.assertIsNone(result["dong"])
        self.assertEqual(result["item_aliases"], {})
        self.assertEqual(
            [item["item"] for item in result["item_context"]],
            ["헤어 스타일러"],
        )
        self.assertEqual(
            [check["expression"] for check in result["ambiguous_expressions"]],
            ["남은 농약 공병"],
        )
        for expression in ("원형 형광등", "원형형광등", "스타일러", "다마", "PC/ABS"):
            with self.subTest(expression=expression):
                payload = build(expression)
                self.assertEqual(payload["item_aliases"], {})
                self.assertEqual(
                    [entry["expression"] for entry in payload["ambiguous_expressions"]],
                    [expression],
                )

    def test_review_records_use_only_the_requested_district(self):
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        for district, expected_source_id in (
            ("서대문구", "seodaemun_recycling"),
            ("송파구", "songpa_recycling_guide"),
        ):
            with self.subTest(district=district):
                records = review_district_records(catalog, "종이 컵", district)
                self.assertEqual(
                    [record["source_id"] for record in records], [expected_source_id]
                )
                self.assertTrue(
                    all(record["district"] == district for record in records)
                )

        self.assertEqual(review_district_records(catalog, "종이컵", "마포구"), [])
        self.assertEqual(review_district_records(catalog, "안마의자", "송파구"), [])

    def test_source_links_remain_within_verified_scope(self):
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        lookup = catalog["official_source_lookup"]
        records = lookup["records"]
        self.assertEqual(lookup["use"], "review_only")
        self.assertEqual(records["ecycle_multiple_pickup"]["minimum_count"], 5)
        for item in ("의류관리기", "제습기", "노트북", "스피커"):
            with self.subTest(item=item):
                self.assertNotIn(
                    "ecycle_pickup_size_quantity", lookup["by_item_key"].get(item, [])
                )
                self.assertNotIn(
                    "ecycle_multiple_pickup", lookup["by_item_key"].get(item, [])
                )

        for key in ("과일껍질", "과일씨", "바나나껍질", "귤껍질"):
            self.assertNotIn(
                "songpa_hard_fruit_shells_pits", lookup["by_item_key"].get(key, [])
            )
        self.assertNotIn(
            "폴리젖산", records["mfds_food_contact_resin_names"]["item_keys"]
        )
        self.assertNotIn(
            "내용물", " ".join(records["mafra_farm_waste_film"]["conditions"])
        )
