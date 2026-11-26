"""팀 전처리 품목표와 지자체 안내에서 리라이트용 품목 목록을 만든다."""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from .aliases import EXACT_ITEM_ALIASES, ITEM_ALIASES, item_key
from .catalog_bulky_specs import BULKY_SPEC_TERMS
from .catalog_extended_terms import (
    ADDITIONAL_GUIDES,
    EXTENDED_REFERENCES,
    EXTENDED_SEARCH_TERMS,
)
from .catalog_terms import ANNEX_TERMS, GUIDE_TERMS
from .dialect_rewrite import language_matching_rules, read_dictionary, read_loanwords
from .facility_profiles import FACILITY_GUIDES, FACILITY_PROFILES
from .technical_terms import (
    MATERIAL_CODES,
    TECHNICAL_SOURCES,
    TECHNICAL_TERMS,
    material_matching_rules,
)

SOURCE_FILES = {
    "seodaemun_bulky": "annex/2101297_160319451.json",
    "songpa_bulky": "annex/1481479_121237861.json",
    "seodaemun_recycling": "annex/2101297_160319453.json",
    "seodaemun_bins": "annex/2101385_160561037.json",
    "seodaemun_food_supplies": "annex/2101385_160561043.json",
    "seodaemun_ordinance": "body/seodaemun-ordinance.json",
    "seodaemun_rules": "body/seodaemun-rules.json",
    "songpa_ordinance": "body/songpa-ordinance.json",
    "songpa_rules": "body/songpa-rules.json",
}
BULKY_COLUMNS = {
    "seodaemun_bulky": {1: (0, 3)},
    "songpa_bulky": {number: (1, 5) for number in (4, 5, 6, 7)},
}
GUIDES = {
    **ADDITIONAL_GUIDES,
    **FACILITY_GUIDES,
    **TECHNICAL_SOURCES,
    "seodaemun_food_guide": (
        "서대문구",
        "2025년 5월 서대문구 소식지의 음식물쓰레기 안내",
        "https://www.sdm.go.kr/fileUpload/board/92/20250425_87330449891481869.pdf",
    ),
    "seodaemun_food_faq": (
        "서대문구",
        "2026년 6월 서대문구 소식지의 음식물쓰레기 문답",
        "https://www.sdm.go.kr/fileUpload/board/92/20260601_15855869764698833.pdf",
    ),
    "seodaemun_waste_guide": (
        "서대문구",
        "생활쓰레기 배출",
        "https://www.sdm.go.kr/civil/type/household.do?sdmBoardSeq=301226",
    ),
    "songpa_food_guide": (
        "송파구",
        "음식물쓰레기 배출안내",
        "https://www.songpa.go.kr/www/contents.do?key=3161",
    ),
    "songpa_waste_guide": (
        "송파구",
        "쓰레기 배출요령",
        "https://www.songpa.go.kr/www/contents.do?key=3153",
    ),
    "seodaemun_appliance_guide": (
        "서대문구",
        "폐금속자원 배출",
        "https://www.sdm.go.kr/civil/type/metal.do?sdmBoardSeq=301238",
    ),
    "seodaemun_appliance_notice": (
        "서대문구",
        "소형폐가전 수거체계 변경 안내",
        "https://www.sdm.go.kr/news/news/notice.do?mode=view&sdmBoardSeq=309565",
    ),
    "songpa_appliance_guide": (
        "송파구",
        "폐소형·대형 가전제품 무상수거",
        "https://www.songpa.go.kr/www/contents.do?key=3171",
    ),
}

BODY_TERMS = (
    (
        "seodaemun_ordinance",
        "000200",
        "생활폐기물",
        (
            "생활폐기물",
            "사업장폐기물",
            "사업장생활계폐기물",
            "공사장생활폐기물",
        ),
    ),
    ("seodaemun_ordinance", "000200", "목재·가구", ("폐목재", "가구")),
    ("seodaemun_ordinance", "000400", "음식물 관련", ("음식물류폐기물",)),
    ("seodaemun_ordinance", "002300", "일반·특수폐기물", ("연탄재", "종량제 폐기물")),
    (
        "seodaemun_ordinance",
        "002400",
        "봉투·배출 도구",
        (
            "규격봉투",
            "일반규격봉투",
            "특수규격봉투",
            "공공용봉투",
            "재사용봉투",
            "음식물류봉투",
            "생활폐기물용 봉투",
            "특수생활폐기물용 봉투",
        ),
    ),
    ("seodaemun_rules", "000900", "봉투·배출 도구", ("종량제봉투",)),
    (
        "songpa_ordinance",
        "000200",
        "생활폐기물",
        (
            "생활폐기물",
            "사업장 생활계폐기물",
            "재활용가능자원",
        ),
    ),
    ("songpa_ordinance", "000800", "봉투·배출 도구", ("종량제봉투", "규격봉투")),
    ("songpa_ordinance", "001000", "대형폐기물", ("대형폐기물",)),
    ("songpa_ordinance", "001003", "생활폐기물", ("공사장생활폐기물",)),
    ("songpa_ordinance", "002700", "일반·특수폐기물", ("일반쓰레기",)),
    ("songpa_ordinance", "002700", "음식물 관련", ("음식물류폐기물",)),
    (
        "songpa_ordinance",
        "002700",
        "봉투·배출 도구",
        ("납부필증", "전자방식의 계량기기"),
    ),
    ("seodaemun_ordinance", "001600", "대형폐기물", ("대형폐기물",)),
)

SMALL_APPLIANCE_TERMS = {
    "seodaemun_appliance_guide": (
        "감시카메라",
        "게임기",
        "공기청정기",
        "공유기",
        "내비게이션",
        "노트북",
        "다리미",
        "마우스",
        "믹서",
        "밥솥",
        "복사기",
        "비디오",
        "빔프로젝터",
        "선풍기",
        "소형자판기",
        "스캐너",
        "식품건조기",
        "에어프라이어",
        "연수기",
        "오디오",
        "음식물처리기",
        "재봉틀",
        "전기오븐",
        "전기포트",
        "전기프라이팬",
        "전기소형안마기",
        "전자레인지",
        "전자체중계",
        "제빵기",
        "족욕기",
        "청소기",
        "커피메이커",
        "컴퓨터",
        "컴퓨터 모니터",
        "컴퓨터 본체",
        "컴퓨터 자판",
        "토스터기",
        "튀김기",
        "팩시밀리",
        "프린터",
        "헤어드라이어",
        "환풍기",
        "휴대폰",
        "휴대폰 충전기",
    ),
    "songpa_appliance_guide": (
        "DVD",
        "가습기",
        "가정용 청소기",
        "가정용 팩시밀리",
        "가정용 프린터",
        "가정용 환풍기",
        "가스레인지",
        "녹즙기",
        "노트북",
        "다리미",
        "모뎀",
        "믹서기",
        "발마사지기",
        "보온밥통",
        "비디오(VTR)",
        "선풍기",
        "스캐너",
        "전화기",
        "전기밥솥",
        "전기히터",
        "전자레인지",
        "전자시계",
        "카세트 라디오",
        "커피포트",
        "컴퓨터",
        "컴퓨터 복합기",
        "컴퓨터 오락기",
        "컴퓨터 키보드",
        "탈수기",
        "토스터기",
        "헤어드라이어",
        "휴대폰",
        "휴대폰 충전기",
    ),
}
QUALIFIED_APPLIANCE_TERMS = (
    ("seodaemun_appliance_guide", "벽시계", "소형이고 목재가 아닌 제품"),
    ("seodaemun_appliance_guide", "건조기", "수거함에 들어가는 크기인지 확인"),
    ("songpa_appliance_guide", "가스오븐레인지", "1m 미만"),
    ("songpa_appliance_guide", "공기청정기", "가장 긴 면 1m 미만"),
    ("songpa_appliance_guide", "식기건조기", "1m 미만"),
    ("songpa_appliance_guide", "식기세척기", "1m 미만"),
    ("songpa_appliance_guide", "에어컨 실외기", "1m 미만"),
    ("songpa_appliance_guide", "오디오 본체", "1m 미만"),
    ("songpa_appliance_guide", "오디오 스피커", "1m 미만"),
    ("songpa_appliance_guide", "정수기", "1m 미만"),
)


def add_item(items, label, group, source, location, **details):
    label = " ".join(label.split())
    key = item_key(label)
    entry = items.setdefault(key, {"item": label, "groups": [], "sources": []})
    if group not in entry["groups"]:
        entry["groups"].append(group)
    reference = {
        "source": source,
        "location": location,
        "label": label,
        "group": group,
        **details,
    }
    if reference not in entry["sources"]:
        entry["sources"].append(reference)


def load_sources(bundle):
    manifest = json.loads((bundle / "bundle_manifest.json").read_text(encoding="utf-8"))
    checksums = {entry["path"]: entry["sha256"] for entry in manifest["files"]}
    documents = {}
    sources = {}
    for key, path in SOURCE_FILES.items():
        path = f"processed/{path}"
        payload = (bundle / path).read_bytes()
        if hashlib.sha256(payload).hexdigest() != checksums[path]:
            raise ValueError(f"전처리 파일 체크섬 불일치: {path}")
        document = json.loads(payload)
        documents[key] = document
        sources[key] = {
            "kind": "processed_ordinance",
            "district": document["district"],
            "title": " ".join(document["title"].split()),
            "path": path,
            "effective_date": document["effective_date"],
            "url": document["source_url"],
            "sha256": checksums[path],
        }
    for key, (district, title, url) in GUIDES.items():
        sources[key] = {
            "kind": "district_guide" if district else "product_reference",
            "district": district,
            "title": title,
            "url": url,
            "checked_on": "2026-11-25",
        }
    sources["resident_search_vocabulary"] = {
        "kind": "search_vocabulary",
        "district": None,
        "title": "사용자 질문 예시와 연관된 검색 표현",
    }
    sources["language_vocabulary"] = {
        "kind": "language_reference",
        "district": None,
        "title": "방언과 외래어 사전에서 연결한 표준 검색어",
    }
    sources["facility_query_examples"] = {
        "kind": "search_vocabulary",
        "district": None,
        "title": "시설에서 발생할 수 있는 품목의 검색 예시",
    }
    sources["technical_vocabulary"] = {
        "kind": "language_reference",
        "district": None,
        "title": "재질·조례·공식 안내의 전문 용어 풀이",
    }
    return documents, sources


def annex_rows(document, table):
    candidate = next(
        row for row in document["tables"] if row["table_id"] == f"table-{table}"
    )
    if document["deleted_marker"] or candidate["deleted_section"]:
        raise ValueError(f"삭제 표시 표: {document['title']} table-{table}")
    return {row["row"]: row for row in candidate["rows_for_search"]}


def add_bulky(items, documents):
    counts = Counter()
    for key, tables in BULKY_COLUMNS.items():
        for table, columns in tables.items():
            for number, row in annex_rows(documents[key], table).items():
                for cell in row["cell_values"]:
                    label = cell["search_text"]
                    col = cell["origin_col"]
                    if (
                        not label
                        or col not in columns
                        or cell["origin_row"] != number
                        or number == 0
                    ):
                        continue
                    add_item(
                        items,
                        label,
                        "대형폐기물",
                        key,
                        f"table-{table}/row[{number}]",
                        cell_id=cell["cell_id"],
                    )
                    counts[key] += 1
    for key, table, number, column, terms in BULKY_SPEC_TERMS:
        row = annex_rows(documents[key], table)[number]
        cell = next(cell for cell in row["cell_values"] if cell["origin_col"] == column)
        for term in terms:
            if item_key(term) not in item_key(cell["search_text"]):
                raise ValueError(
                    f"규격 셀의 품목명 미확인: {key} {cell['cell_id']} {term}"
                )
            add_item(
                items,
                term,
                "대형폐기물",
                key,
                f"table-{table}/row[{number}]",
                cell_id=cell["cell_id"],
                source_label=cell["search_text"],
            )
    return dict(counts)


def add_processed_terms(items, documents):
    for key, table, number, group, terms in ANNEX_TERMS:
        annex_rows(documents[key], table)[number]
        for label in terms:
            add_item(items, label, group, key, f"table-{table}/row[{number}]")
    for key, article, group, terms in BODY_TERMS:
        unit = next(
            unit
            for unit in documents[key]["units"]
            if unit.get("article_number") == article and not unit["deleted_article"]
        )
        for label in terms:
            if item_key(label) not in item_key(unit["text"]):
                raise ValueError(f"조문에서 용어 미확인: {key} {article} {label}")
            add_item(
                items,
                label,
                group,
                key,
                unit["source_location"],
                unit_id=unit["unit_id"],
            )
    for position, label in enumerate(
        ("캔류", "유리병", "종이팩", "PET병", "플라스틱류", "비닐(필름)류")
    ):
        block = 8 + position // 2
        text = documents["seodaemun_bins"]["blocks"][block]["text"]
        if item_key(label) not in item_key(text):
            raise ValueError(f"재활용품 용기 안내에서 용어 미확인: {label}")
        add_item(
            items,
            label,
            "재활용품",
            "seodaemun_bins",
            f"blocks[{block}]",
            qualifier="공동주택의 일반용기",
        )


def add_guides(items):
    for key, location, group, terms in GUIDE_TERMS:
        for label in terms:
            add_item(items, label, group, key, location)
    for key, terms in SMALL_APPLIANCE_TERMS.items():
        for label in ("소형가전", *terms):
            add_item(items, label, "소형가전", key, "소형폐가전 대상품목")
    for key, label, condition in QUALIFIED_APPLIANCE_TERMS:
        add_item(
            items, label, "소형가전", key, "소형폐가전 대상품목", qualifier=condition
        )
    for label in ("가스레인지", "가스히터", "가스오븐"):
        add_item(
            items,
            label,
            "소형가전 수거함 제외 예시",
            "seodaemun_appliance_notice",
            "유의 사항의 연료 혼용 제품",
        )
    for key, location, group, labels, qualifier in EXTENDED_REFERENCES:
        for label in labels:
            details = {"qualifier": qualifier} if qualifier else {}
            add_item(items, label, group, key, location, **details)

    for group, labels in EXTENDED_SEARCH_TERMS.items():
        for label in labels:
            entry = items.get(item_key(label))
            if entry is None:
                add_item(
                    items, label, group, "resident_search_vocabulary", "품목명 검색어"
                )
                continue
            if group not in entry["groups"]:
                # 이미 확인한 품목의 출처를 새 검색 분야에서도 찾을 수 있게 한다.
                for reference in tuple(entry["sources"]):
                    add_item(
                        items,
                        reference["label"],
                        group,
                        reference["source"],
                        reference["location"],
                        **{
                            key: reference[key]
                            for key in (
                                "qualifier",
                                "cell_id",
                                "source_label",
                                "unit_id",
                            )
                            if key in reference
                        },
                    )


def add_facility_profiles(items, sources):
    profiles = {}
    names_to_profile = {}
    for profile_id, (
        names,
        labels,
        conditions,
        source_ids,
    ) in FACILITY_PROFILES.items():
        for name in names:
            key = item_key(name)
            if key in names_to_profile:
                raise ValueError(f"중복 장소 표현: {name}")
            names_to_profile[key] = profile_id
        keys = []
        for label in labels:
            key = item_key(label)
            if key not in items:
                add_item(
                    items,
                    label,
                    "시설별 검색 예시",
                    "facility_query_examples",
                    names[0],
                )
            keys.append(key)
        for source_id in source_ids:
            if source_id not in sources:
                raise ValueError(f"시설 참고 자료 미등록: {source_id}")
        profiles[profile_id] = {
            "name": names[0],
            "names": names,
            "example_item_keys": keys,
            "conditions_to_preserve": conditions,
            "context_source_ids": source_ids,
        }
    return {
        "purpose": "발생 장소에서 물을 수 있는 품목을 찾는 검색 색인",
        "use": "장소와 배출 주체는 검색 문맥으로 유지하고, 폐기물 분류와 지역별 배출은 품목의 근거를 조회한다.",
        "by_name": dict(sorted(names_to_profile.items())),
        "profiles": profiles,
    }


def add_technical_lookup(items, sources):
    terms, codes = {}, {}
    for group, entries in TECHNICAL_TERMS.items():
        for label, meaning, related, source_ids in entries:
            key = item_key(label)
            terms[key] = {
                "term": label,
                "group": group,
                "meaning": meaning,
                "related_terms": related,
                "source_ids": source_ids,
            }
    for code, label, source_ids, context in MATERIAL_CODES:
        codes[code] = {"term": label, "context": context, "source_ids": source_ids}
    for entry in (*terms.values(), *codes.values()):
        for source_id in entry["source_ids"]:
            if source_id not in sources:
                raise ValueError(f"전문 용어 출처 미등록: {source_id}")
        label = entry["term"]
        key = item_key(label)
        if key not in items:
            add_item(
                items, label, "전문 용어", "technical_vocabulary", "전문 용어 사전"
            )
    return {
        "use": "용어와 표시를 풀어 검색한다. 표시만으로 실제 제품의 재질 또는 배출 방법을 추정하지 않는다.",
        "terms_by_key": dict(sorted(terms.items())),
        "material_codes": codes,
    }


def build_catalog(bundle: Path) -> dict:
    documents, sources = load_sources(bundle)
    items: dict[str, dict] = {}
    counts = add_bulky(items, documents)
    add_processed_terms(items, documents)
    add_guides(items)
    prompt_vocabulary = json.loads(
        Path(__file__).with_name("prompt_vocabulary.json").read_text(encoding="utf-8")
    )
    for group, labels in prompt_vocabulary["search_terms"].items():
        for label in labels:
            add_item(items, label, group, "resident_search_vocabulary", "질문 검색어")
    facility_lookup = add_facility_profiles(items, sources)
    technical_lookup = add_technical_lookup(items, sources)
    dialect, loanwords = read_dictionary(), read_loanwords()
    alias_profiles_path = Path(__file__).with_name("rewrite_alias_profiles.json")
    alias_profiles = json.loads(alias_profiles_path.read_text(encoding="utf-8"))
    for name, vocabulary in (("dialect", dialect), ("loanwords", loanwords)):
        for rule in vocabulary["rules"]:
            if rule["match"] == "item":
                for label in rule["forms"].values():
                    if item_key(label) not in items:
                        add_item(
                            items, label, "언어 검색어", "language_vocabulary", name
                        )
    for alias, canonical in ITEM_ALIASES.items():
        entry = items.get(item_key(canonical))
        if entry is None:
            raise ValueError(f"품목 목록에 없는 리라이트 검색어: {canonical}")
        entry.setdefault("rewrite_aliases", []).append(alias)
    for alias, canonical in EXACT_ITEM_ALIASES.items():
        entry = items[item_key(canonical)]
        entry.setdefault("exact_item_aliases", []).append(alias)
    for label in prompt_vocabulary["item_conditions"]:
        if item_key(ITEM_ALIASES.get(label, label)) not in items:
            raise ValueError(f"품목 목록에 없는 프롬프트 확인 조건: {label}")
    for entry in items.values():
        entry["districts"] = sorted(
            {
                sources[ref["source"]]["district"]
                for ref in entry["sources"]
                if sources[ref["source"]]["district"]
            }
        )
    ordered_items = dict(sorted(items.items()))
    grouped_items: dict[str, list[str]] = {}
    for key, entry in ordered_items.items():
        for group in entry["groups"]:
            grouped_items.setdefault(group, []).append(key)
    return {
        "version": 1,
        "source_bundle": bundle.name,
        "item_count": len(items),
        "rewrite_alias_count": len(ITEM_ALIASES),
        "bulky_item_cell_counts": counts,
        "group_counts": {
            group: len(keys) for group, keys in sorted(grouped_items.items())
        },
        "sources": sources,
        "item_aliases": ITEM_ALIASES,
        "exact_item_aliases": EXACT_ITEM_ALIASES,
        "alias_profiles": alias_profiles,
        "dialect": dialect,
        "loanwords": loanwords,
        "facility_lookup": facility_lookup,
        "technical_lookup": technical_lookup,
        "prompt_vocabulary": {
            "item_conditions": prompt_vocabulary["item_conditions"],
            "ambiguous_expressions": prompt_vocabulary["ambiguous_expressions"],
        },
        "rewrite_rules": {
            "regex_engine": "python.re",
            "search_language_order": ["dialect", "loanwords", "material_codes"],
            "language": language_matching_rules(),
            "materials": material_matching_rules(),
        },
        "lookup_context": {
            "음식물 관련": ["식재료와 부위", "포장재·이물질", "발생 장소"],
            "가전·전자제품": ["본체·부속품", "전원·배터리", "크기·수량"],
            "소형가전": ["본체·부속품", "전원·배터리", "크기·수량"],
            "재활용품": ["재질 표시", "복합재 분리 여부", "내용물·오염"],
            "목재·가구": [
                "완성 가구·판재",
                "재질과 코팅",
                "크기",
                "공사에서 발생했는지",
            ],
            "안마용품": ["의자형·소형 기기·기타", "크기", "전원"],
            "성인용품": ["구체 품목", "재질", "크기", "전원·배터리"],
            "운동기구·헬스용품": [
                "가정용·업소용",
                "크기와 무게",
                "전원",
                "기구·매트·부품",
            ],
            "사우나·온열기기": ["설치형·이동형", "전원·연료", "크기", "철거 여부"],
            "실험실 약품·폐기물": [
                "물질명·표지",
                "액상·고상",
                "잔류·오염",
                "소속 연구실",
            ],
            "농업용 약품·포장재": [
                "내용물 잔류",
                "제품 용도",
                "용기 재질",
                "배출 주체",
            ],
            "포장재": ["단일·복합 재질", "테이프·이물질", "봉투와 완충재의 분리 여부"],
            "전구·조명": [
                "램프·조명기구 본체·부품",
                "전구 방식과 모양",
                "파손 여부",
                "배출 지역",
            ],
        },
        "items_by_group": dict(sorted(grouped_items.items())),
        "items_by_key": ordered_items,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path, help="팀 전처리 묶음 경로")
    parser.add_argument(
        "--output", type=Path, default=Path(__file__).with_name("item_catalog.json")
    )
    args = parser.parse_args()
    data = build_catalog(args.bundle)
    args.output.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        f"품목·검색어 {data['item_count']}개, 리라이트 별칭 {data['rewrite_alias_count']}개"
    )


if __name__ == "__main__":
    main()
