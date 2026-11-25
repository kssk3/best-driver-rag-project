"""품목 사전 JSON으로 검색 질의를 다듬고 공식 기록을 로컬에서 검토한다."""

import argparse
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from .aliases import item_key
from .dialect_rewrite import make_language_normalizer
from .technical_terms import make_material_expander

CATALOG_PATH = Path(__file__).with_name("item_catalog.json")
_EXCLUDED_ITEM = re.compile(
    r"[^\S\r\n]+(?:말고|빼고|아닌|아니고|제외(?:하고|한|하면)?)(?!\w)"
)
_STATE_PREFIXES = ("깨진", "파손된", "빈", "비운", "투명", "무색")
_NEGATED_STATE = re.compile(r"(?<!\w)(?:안|덜|전혀)[^\S\r\n]+\Z")


class SearchQuery(Protocol):
    @property
    def search_query(self) -> str: ...


def _fold(text: str) -> str:
    return " ".join(text.casefold().split())


def _item_matcher(terms: set[str], rules: dict) -> re.Pattern[str]:
    separator = rules["expression_space_pattern"]
    expressions = (
        "|".join(
            separator.join(map(re.escape, term.split()))
            for term in sorted(terms, key=lambda term: (-len(term), term))
        )
        or r"(?!)"
    )
    left = rules["expression_left_boundary"]
    right = rules["suffix_patterns_by_mode"]["item"]
    return re.compile(f"{left}(?P<item>{expressions}){right}", re.IGNORECASE)


def _mentioned_items(pattern: re.Pattern[str], question: str) -> dict[str, str]:
    mentions = {}
    for match in pattern.finditer(question):
        if _EXCLUDED_ITEM.match(question, match.end()):
            continue
        surface = match["item"]
        if surface.startswith(_STATE_PREFIXES) and _NEGATED_STATE.search(
            question, 0, match.start()
        ):
            continue
        mentions.setdefault(_fold(surface), surface)
    return mentions


def _language_rewriter(catalog: dict) -> Callable[[str], str]:
    rules = catalog["rewrite_rules"]
    language = rules["language"]
    material_codes = catalog["technical_lookup"]["material_codes"]
    normalizers = {
        "dialect": make_language_normalizer(catalog["dialect"], language),
        "loanwords": make_language_normalizer(catalog["loanwords"], language),
        "material_codes": make_material_expander(
            {code: entry["term"] for code, entry in material_codes.items()},
            rules["materials"],
        ),
    }

    def normalize(question: str) -> str:
        for stage in rules["search_language_order"]:
            question = normalizers[stage](question)
        return question

    return normalize


def make_question_rewriter(path: Path = CATALOG_PATH) -> Callable[[str], str]:
    """JSON의 언어 규칙, 재질 약어와 기본 별칭으로 검색어를 보강한다."""
    catalog = json.loads(path.read_text(encoding="utf-8"))
    language = catalog["rewrite_rules"]["language"]
    normalize = _language_rewriter(catalog)
    aliases = {_fold(term): name for term, name in catalog["item_aliases"].items()}
    exact = {_fold(term): name for term, name in catalog["exact_item_aliases"].items()}
    item_terms = {_fold(entry["item"]) for entry in catalog["items_by_key"].values()}
    item_pattern = _item_matcher(item_terms | aliases.keys(), language)
    canonical_pattern = _item_matcher(
        {_fold(name) for name in (*aliases.values(), *exact.values())}, language
    )

    def rewrite(question: str) -> str:
        question = normalize(question)
        matched = _mentioned_items(item_pattern, question)
        present = {
            _fold(match["item"]) for match in canonical_pattern.finditer(question)
        }
        candidates = [name for alias, name in aliases.items() if alias in matched]
        exact_match = exact.get(_fold(question))
        if exact_match:
            candidates.append(exact_match)

        suffixes = []
        for name in candidates:
            key = _fold(name)
            if key not in present:
                suffixes.append(f" ({name})")
                present.add(key)
        return question.rstrip() + "".join(suffixes) if suffixes else question

    return rewrite


def make_catalog_rewriter(path: Path = CATALOG_PATH) -> Callable[[SearchQuery], str]:
    """팀 런타임의 리라이트 콜백에 연결할 함수를 반환한다."""
    rewrite = make_question_rewriter(path)

    def rewrite_resolved(query: SearchQuery) -> str:
        return rewrite(query.search_query)

    return rewrite_resolved


def review_district_records(catalog: dict, item: str, district: str) -> list[dict]:
    """로컬 검토용으로 해석된 구의 공식 기록만 조회한다."""
    lookup = catalog["official_source_lookup"]
    record_ids = lookup["by_district"].get(district, {}).get(item_key(item), [])
    return [lookup["records"][record_id] for record_id in record_ids]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", help="지역이 해석된 검색 질의")
    parser.add_argument("--catalog", type=Path, default=CATALOG_PATH)
    args = parser.parse_args()
    print(make_question_rewriter(args.catalog)(args.question))


if __name__ == "__main__":
    main()
