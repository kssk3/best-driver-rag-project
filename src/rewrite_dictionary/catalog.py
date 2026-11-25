"""검색 질의와 프롬프트가 읽는 품목 사전 필드를 정의한다."""

import json
from pathlib import Path
from typing import TypedDict

CATALOG_PATH = Path(__file__).with_name("item_catalog.json")


class CatalogItem(TypedDict):
    item: str
    groups: list[str]


class CatalogFacility(TypedDict):
    name: str
    names: list[str]
    conditions_to_preserve: list[str]


class QueryCatalog(TypedDict):
    rewrite_rules: dict
    dialect: dict
    loanwords: dict
    material_names: dict[str, str]
    item_aliases: dict[str, str]
    exact_item_aliases: dict[str, str]
    items_by_key: dict[str, CatalogItem]
    prompt_vocabulary: dict
    lookup_context: dict[str, list[str]]
    facilities: list[CatalogFacility]


def load_query_catalog(path: Path) -> QueryCatalog:
    """출처·적용 기준과 평가 자료를 제외하고 검색에 쓰는 필드만 로드한다."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != 1:
        raise ValueError("지원하지 않는 품목 사전 버전입니다.")
    return {
        "rewrite_rules": data["rewrite_rules"],
        "dialect": data["dialect"],
        "loanwords": data["loanwords"],
        "material_names": {
            code: entry["term"]
            for code, entry in data["technical_lookup"]["material_codes"].items()
        },
        "item_aliases": data["item_aliases"],
        "exact_item_aliases": data["exact_item_aliases"],
        "items_by_key": {
            key: {"item": entry["item"], "groups": entry["groups"]}
            for key, entry in data["items_by_key"].items()
        },
        "prompt_vocabulary": data.get("prompt_vocabulary", {}),
        "lookup_context": data["lookup_context"],
        "facilities": [
            {
                "name": profile["name"],
                "names": profile["names"],
                "conditions_to_preserve": profile["conditions_to_preserve"],
            }
            for profile in data["facility_lookup"]["profiles"].values()
        ],
    }
