"""전문 용어가 배출 조건을 바꾸지 않고 리라이트에 들어가는지 검증한다."""

import json
from pathlib import Path
from unittest import TestCase

from rewrite_dictionary.dialect_rewrite import (
    language_matching_rules,
    normalize_search_language,
)
from rewrite_dictionary.technical_terms import (
    MATERIAL_CODES,
    TECHNICAL_TERMS,
    expand_material_codes,
    material_matching_rules,
)


class TechnicalRewriteTests(TestCase):
    def test_expands_material_codes_with_item_or_label_context(self):
        cases = {
            "오염된 LDPE 비닐은 워떻게 배출해요?": (
                "오염된 LDPE 비닐은 어떻게 배출해요? (저밀도 폴리에틸렌)"
            ),
            "뚜껑: HDPE / 라벨: PP로 표기된 유색 병이에요.": (
                "뚜껑: HDPE / 라벨: PP로 표기된 유색 병이에요. "
                "(고밀도 폴리에틸렌) (폴리프로필렌)"
            ),
            "송파구 유색 PET병은 어떻게 배출해요?": (
                "송파구 유색 PET병은 어떻게 배출해요? (폴리에틸렌테레프탈레이트)"
            ),
            "서대문구 PET-G 용기는?": ("서대문구 PET-G 용기는? (글리콜변성 PET 수지)"),
            "테이프 붙은 EPS 완충재는?": ("테이프 붙은 EPS 완충재는? (발포폴리스티렌)"),
            "PC 재질 용기와 PVC 파이프를 구분하나요?": (
                "PC 재질 용기와 PVC 파이프를 구분하나요? (폴리카보네이트) (폴리염화비닐)"
            ),
            "ABS 수지 케이스 안에 배터리가 남았어요.": (
                "ABS 수지 케이스 안에 배터리가 남았어요. "
                "(아크릴로니트릴-부타디엔-스티렌 공중합체)"
            ),
            "PA 필름과 PVDC 랩은 같은 재질인가요?": (
                "PA 필름과 PVDC 랩은 같은 재질인가요? (폴리아미드) (폴리염화비닐리덴)"
            ),
            "분해되지 않은 PU 폼과 EVA 매트": (
                "분해되지 않은 PU 폼과 EVA 매트 (폴리우레탄) (에틸렌-초산비닐 공중합체)"
            ),
            "뚜껑과 분리된 PLA 컵": "뚜껑과 분리된 PLA 컵 (폴리젖산)",
            "뚜껑(HDPE)은 분리했어요.": "뚜껑(HDPE)은 분리했어요. (고밀도 폴리에틸렌)",
            "OTHER 표시가 붙은 포장재?": "OTHER 표시가 붙은 포장재? (기타 재질 표시)",
        }
        for question, expected in cases.items():
            with self.subTest(question=question):
                actual = normalize_search_language(question)
                self.assertEqual(actual, expected)
                self.assertEqual(normalize_search_language(actual), actual)

    def test_leaves_ambiguous_and_partial_code_mentions_in_place(self):
        cases = (
            "PC 본체는 어디에 버려요?",
            "본체: PC를 반납하나요?",
            "ABS 센서와 브레이크 부품은 어떻게 버려요?",
            "자동차 ABS 표시등이 켜졌어요.",
            "자동차 ABS 마크를 확인했어요.",
            "ABS 표시가 난 브레이크 센서 버릴까요?",
            "본체: ABS 센서입니다.",
            "PLA는요?",
            "유리병",
            "PP는요?",
            "PS 게임기를 버려요?",
            "다른 other 포장재도 있어요?",
            "PVCX 파이프는 어떻게 버려요?",
            "Pſ 트레이는요?",
            "PP-XYZ 트레이는요?",
            "비닐 안쪽 글리콜변성 PET 수지는요?",
        )
        for query in cases:
            with self.subTest(query=query):
                self.assertEqual(normalize_search_language(query), query)
                self.assertEqual(expand_material_codes(query), query)

    def test_generated_dictionary_contains_current_technical_vocabulary(self):
        path = Path(__file__).with_name("item_catalog.json")
        catalog = json.loads(path.read_text(encoding="utf-8"))
        technical = catalog["technical_lookup"]
        self.assertEqual(
            len(technical["terms_by_key"]),
            sum(len(group) for group in TECHNICAL_TERMS.values()),
        )
        self.assertEqual(
            {
                code: {
                    field: entry[field] for field in ("term", "context", "source_ids")
                }
                for code, entry in technical["material_codes"].items()
            },
            {
                code: {"term": term, "context": context, "source_ids": list(sources)}
                for code, term, sources, context in MATERIAL_CODES
            },
        )
        for entry in (
            *technical["terms_by_key"].values(),
            *technical["material_codes"].values(),
        ):
            self.assertLessEqual(set(entry["source_ids"]), set(catalog["sources"]))
            key = "".join(entry["term"].casefold().split())
            self.assertIn(key, catalog["items_by_key"])

    def test_catalog_exports_current_language_and_material_matching_rules(self):
        path = Path(__file__).with_name("item_catalog.json")
        catalog = json.loads(path.read_text(encoding="utf-8"))
        rules = catalog["rewrite_rules"]

        self.assertEqual(
            rules["language"], json.loads(json.dumps(language_matching_rules()))
        )
        self.assertEqual(
            rules["materials"], json.loads(json.dumps(material_matching_rules()))
        )

    def test_official_sources_preserve_item_location_and_scope(self):
        path = Path(__file__).with_name("item_catalog.json")
        catalog = json.loads(path.read_text(encoding="utf-8"))
        official = catalog["official_source_lookup"]
        records = official["records"]
        cases = {
            "종이컵": ("songpa_paper_cup", "송파구"),
            "깨진형광등": ("seodaemun_broken_lamp", "서대문구"),
            "불투명패트병": ("songpa_colored_opaque_containers", "송파구"),
            "안마의자": ("ecycle_massage_chair_pickup", None),
            "폴리락타이드": ("mfds_food_contact_resin_names", None),
            "빈농약병": ("mafra_empty_pesticide_containers", None),
        }
        for key, (record_id, district) in cases.items():
            with self.subTest(key=key):
                self.assertIn(record_id, official["by_item_key"][key])
                self.assertEqual(records[record_id]["district"], district)
                self.assertIn(
                    record_id,
                    {
                        entry.get("official_record_id")
                        for entry in catalog["items_by_key"][key]["sources"]
                    },
                )

        self.assertNotIn("삼자형led등", records["seodaemun_broken_lamp"]["item_keys"])
        self.assertNotIn(
            "남은농약", records["mafra_empty_pesticide_containers"]["item_keys"]
        )
        self.assertEqual(
            catalog["technical_lookup"]["material_codes"]["PLA"]["official_name"],
            "폴리락타이드",
        )
