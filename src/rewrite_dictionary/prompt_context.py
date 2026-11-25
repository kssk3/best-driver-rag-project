"""질문 한 건에 해당하는 리라이트·답변 프롬프트 초안 입력을 생성한다."""

import argparse
import json
from pathlib import Path
from typing import Protocol, TypedDict, TypeVar

from .aliases import item_key
from .catalog import CATALOG_PATH, load_query_catalog
from .dialect_rewrite import make_language_rewriter
from .matching import (
    compile_item_matcher,
    fold_item_text,
    mentioned_items,
)

PROMPT_CONTEXT_SCHEMA_VERSION = "catalog-context-v1"


class ItemContext(TypedDict):
    item: str
    checks: list[str]


class FacilityContext(TypedDict):
    place: str
    checks: list[str]


class AmbiguousExpression(TypedDict):
    expression: str
    check: str


class PromptContext(TypedDict):
    schema_version: str
    question: str
    district: str | None
    dong: str | None
    language_normalized_question: str | None
    item_aliases: dict[str, str]
    item_context: list[ItemContext]
    facility_context: list[FacilityContext]
    ambiguous_expressions: list[AmbiguousExpression]
    omitted_counts: dict[str, int]


class PromptContextBuilder(Protocol):
    def __call__(
        self, question: str, *, district: str | None = None, dong: str | None = None
    ) -> PromptContext: ...


Entry = TypeVar("Entry")


def _take(
    entries: list[Entry], limit: int, field: str, omitted: dict[str, int]
) -> list[Entry]:
    if len(entries) > limit:
        omitted[field] = omitted.get(field, 0) + len(entries) - limit
    return entries[:limit]


def make_prompt_context_builder(path: Path = CATALOG_PATH) -> PromptContextBuilder:
    """품목 사전에서 질문별 별칭과 확인할 조건을 골라낸다."""
    catalog = load_query_catalog(path)
    language = catalog["rewrite_rules"]["language"]
    normalize = make_language_rewriter(catalog)
    aliases = {
        fold_item_text(term): name for term, name in catalog["item_aliases"].items()
    }
    exact_aliases = {
        fold_item_text(term): name
        for term, name in catalog["exact_item_aliases"].items()
    }
    items = catalog["items_by_key"]
    canonical_terms = {
        fold_item_text(entry["item"]): key for key, entry in items.items()
    }
    vocabulary = catalog["prompt_vocabulary"]
    ambiguity = {
        fold_item_text(form): check["reason"]
        for name in ("dialect", "loanwords")
        for check in catalog[name]["context_required"]
        for form in check["expression"].split("·")
        if len(form) > 1
    }
    ambiguity.update(
        {
            fold_item_text(term): check
            for term, check in vocabulary.get("ambiguous_expressions", {}).items()
        }
    )
    item_conditions = {
        fold_item_text(term): checks
        for term, checks in vocabulary.get("item_conditions", {}).items()
    }
    group_conditions = catalog["lookup_context"]
    facilities = {
        fold_item_text(name): profile
        for profile in catalog["facilities"]
        for name in profile["names"]
    }
    pattern = compile_item_matcher(
        set(canonical_terms)
        | aliases.keys()
        | exact_aliases.keys()
        | ambiguity.keys()
        | facilities.keys(),
        language,
    )

    def build(
        question: str, *, district: str | None = None, dong: str | None = None
    ) -> PromptContext:
        normalized = normalize(question)
        original_matches = mentioned_items(pattern, question)
        matches = original_matches.copy()
        if normalized != question:
            for term, surface in mentioned_items(pattern, normalized).items():
                matches.setdefault(term, surface)

        exact_match = fold_item_text(question)
        selected_aliases = {
            surface: aliases[term]
            for term, surface in matches.items()
            if term in aliases
        }
        if exact_match in exact_aliases and exact_match not in ambiguity:
            surface = original_matches.get(exact_match, question.strip())
            selected_aliases[surface] = exact_aliases[exact_match]

        item_context: dict[str, ItemContext] = {}
        facility_context: dict[str, FacilityContext] = {}
        for term, surface in matches.items():
            canonical = selected_aliases.get(surface)
            key = item_key(canonical) if canonical else canonical_terms.get(term)
            if key is not None and key in items:
                checks = item_conditions.get(term) or item_conditions.get(
                    fold_item_text(canonical or items[key]["item"])
                )
                if not checks:
                    checks = list(
                        dict.fromkeys(
                            check
                            for group in items[key]["groups"]
                            for check in group_conditions.get(group, [])
                        )
                    )
                if checks:
                    item_context.setdefault(
                        key, {"item": canonical or surface, "checks": checks}
                    )
            if term in facilities:
                profile = facilities[term]
                facility_context.setdefault(
                    profile["name"],
                    {"place": surface, "checks": profile["conditions_to_preserve"]},
                )

        ambiguous_expressions: list[AmbiguousExpression] = [
            {"expression": surface, "check": ambiguity[term]}
            for term, surface in original_matches.items()
            if term in ambiguity
        ]
        # 먼저 언급한 품목을 남겨 보조 문맥 크기를 줄인다. 원질문은 항상 보존한다.
        omitted: dict[str, int] = {}
        selected_items = _take(list(item_context.values()), 6, "item_context", omitted)
        for item in selected_items:
            item["checks"] = _take(item["checks"], 4, "item_checks", omitted)
        selected_places = _take(
            list(facility_context.values()), 3, "facility_context", omitted
        )
        for place in selected_places:
            place["checks"] = _take(place["checks"], 4, "facility_checks", omitted)

        return {
            "schema_version": PROMPT_CONTEXT_SCHEMA_VERSION,
            "question": question,
            "district": district,
            "dong": dong,
            "language_normalized_question": normalized
            if normalized != question
            else None,
            "item_aliases": dict(
                _take(list(selected_aliases.items()), 8, "item_aliases", omitted)
            ),
            "item_context": selected_items,
            "facility_context": selected_places,
            "ambiguous_expressions": _take(
                ambiguous_expressions, 4, "ambiguous_expressions", omitted
            ),
            "omitted_counts": omitted,
        }

    return build


def serialize_prompt_context(
    context: PromptContext, *, indent: int | None = None
) -> str:
    """프롬프트 지시문과 분리해 전달할 JSON 사용자 입력을 만든다."""
    return json.dumps(context, ensure_ascii=False, indent=indent)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question")
    parser.add_argument("--district", help="지역 해석에서 확인된 구")
    parser.add_argument("--dong", help="지역 해석에서 확인된 동")
    parser.add_argument("--catalog", type=Path, default=CATALOG_PATH)
    args = parser.parse_args()
    build = make_prompt_context_builder(args.catalog)
    context = build(args.question, district=args.district, dong=args.dong)
    print(serialize_prompt_context(context, indent=2))


if __name__ == "__main__":
    main()
