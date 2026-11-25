"""질문 한 건에 해당하는 리라이트·답변 프롬프트 문맥을 생성한다."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path

from .aliases import item_key
from .runtime import (
    CATALOG_PATH,
    _fold,
    _item_matcher,
    _language_rewriter,
    _mentioned_items,
)


def make_prompt_context_builder(path: Path = CATALOG_PATH) -> Callable[..., dict]:
    """한 번 읽은 JSON에서 질문별 품목 별칭과 확인할 조건만 골라낸다."""
    catalog = json.loads(path.read_text(encoding="utf-8"))
    language = catalog["rewrite_rules"]["language"]
    normalize = _language_rewriter(catalog)
    aliases = {_fold(term): name for term, name in catalog["item_aliases"].items()}
    exact_aliases = {
        _fold(term): name for term, name in catalog["exact_item_aliases"].items()
    }
    items = catalog["items_by_key"]
    canonical_terms = {_fold(entry["item"]): key for key, entry in items.items()}
    vocabulary = catalog.get("prompt_vocabulary", {})
    ambiguity = {
        _fold(form): check["reason"]
        for name in ("dialect", "loanwords")
        for check in catalog[name]["context_required"]
        for form in check["expression"].split("·")
        if len(form) > 1
    }
    ambiguity.update(
        {
            _fold(term): check
            for term, check in vocabulary.get("ambiguous_expressions", {}).items()
        }
    )
    item_conditions = {
        _fold(term): checks
        for term, checks in vocabulary.get("item_conditions", {}).items()
    }
    group_conditions = catalog["lookup_context"]
    facilities = {
        _fold(name): profile
        for profile in catalog["facility_lookup"]["profiles"].values()
        for name in profile["names"]
    }
    pattern = _item_matcher(
        set(canonical_terms)
        | aliases.keys()
        | exact_aliases.keys()
        | ambiguity.keys()
        | facilities.keys(),
        language,
    )

    def build(
        question: str, *, district: str | None = None, dong: str | None = None
    ) -> dict:
        normalized = normalize(question)
        original_matches = _mentioned_items(pattern, question)
        exact_match = _fold(question)
        selected_aliases = {
            surface: aliases[term]
            for term, surface in original_matches.items()
            if term in aliases
        }
        if exact_match in exact_aliases and exact_match not in ambiguity:
            selected_aliases[question.strip()] = exact_aliases[exact_match]

        matches = original_matches.copy()
        if normalized != question:
            for term, surface in _mentioned_items(pattern, normalized).items():
                matches.setdefault(term, surface)

        item_context = {}
        facility_context = {}
        for term, surface in matches.items():
            canonical = selected_aliases.get(surface)
            key = item_key(canonical) if canonical else canonical_terms.get(term)
            if key in items:
                checks = item_conditions.get(term) or item_conditions.get(
                    _fold(canonical or items[key]["item"])
                )
                if not checks:
                    checks = dict.fromkeys(
                        check
                        for group in items[key]["groups"]
                        for check in group_conditions.get(group, [])
                    )
                if checks:
                    item_context.setdefault(
                        key, {"item": canonical or surface, "checks": list(checks)[:4]}
                    )
            if term in facilities:
                profile = facilities[term]
                facility_context.setdefault(
                    profile["name"],
                    {"place": surface, "checks": profile["conditions_to_preserve"][:4]},
                )

        return {
            "question": question,
            "district": district,
            "dong": dong,
            "language_normalized_question": normalized
            if normalized != question
            else None,
            "item_aliases": dict(list(selected_aliases.items())[:8]),
            "item_context": list(item_context.values())[:6],
            "facility_context": list(facility_context.values())[:3],
            "ambiguous_expressions": [
                {"expression": surface, "check": ambiguity[term]}
                for term, surface in original_matches.items()
                if term in ambiguity
            ][:4],
        }

    return build


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question")
    parser.add_argument("--district", help="지역 해석에서 확인된 구")
    parser.add_argument("--dong", help="지역 해석에서 확인된 동")
    parser.add_argument("--catalog", type=Path, default=CATALOG_PATH)
    args = parser.parse_args()
    build = make_prompt_context_builder(args.catalog)
    context = build(args.question, district=args.district, dong=args.dong)
    print(json.dumps(context, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
