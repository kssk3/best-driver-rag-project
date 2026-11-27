"""품목 별칭과 언어 규칙으로 검색 질의를 보강한다."""

import argparse
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from .catalog import CATALOG_PATH, load_query_catalog
from .dialect_rewrite import make_language_rewriter
from .matching import (
    active_item_matches,
    compile_item_matcher,
    fold_item_text,
    mentioned_items,
    selection_spelling_aliases,
)

CATALOG_REWRITE_VERSION = "catalog-rules-v2"


class SearchQuery(Protocol):
    @property
    def search_query(self) -> str: ...


class QuestionRewriter(Protocol):
    def __call__(
        self, question: str, *, district: str | None = None, dong: str | None = None
    ) -> str: ...


def make_question_rewriter(path: Path = CATALOG_PATH) -> QuestionRewriter:
    """JSON의 언어 규칙, 재질 약어와 기본 별칭으로 검색어를 보강한다."""
    catalog = load_query_catalog(path)
    language = catalog["rewrite_rules"]["language"]
    normalize = make_language_rewriter(catalog)
    aliases = {
        fold_item_text(term): name for term, name in catalog["item_aliases"].items()
    }
    spelling_aliases = selection_spelling_aliases(aliases)
    exact = {
        fold_item_text(term): name
        for term, name in catalog["exact_item_aliases"].items()
    }
    item_terms = {
        fold_item_text(entry["item"]) for entry in catalog["items_by_key"].values()
    }
    item_pattern = compile_item_matcher(item_terms | aliases.keys(), language)
    canonical_pattern = compile_item_matcher(
        {fold_item_text(name) for name in (*aliases.values(), *exact.values())},
        language,
    )

    def rewrite(
        question: str, *, district: str | None = None, dong: str | None = None
    ) -> str:
        # 선택·제외 판단은 별칭 후보에만 적용하고 질문 본문은 줄이지 않는다.
        question = normalize(question)
        matched = mentioned_items(
            active_item_matches(item_pattern, question, spelling_aliases, aliases)
        )
        present = {
            fold_item_text(match["item"])
            for match in canonical_pattern.finditer(question)
        }
        candidates = [name for alias, name in aliases.items() if alias in matched]
        exact_match = exact.get(fold_item_text(question))
        if exact_match:
            candidates.append(exact_match)

        suffixes = []
        for name in candidates:
            key = fold_item_text(name)
            if key not in present:
                suffixes.append(f" ({name})")
                present.add(key)
        return question.rstrip() + "".join(suffixes) if suffixes else question

    return rewrite


def make_catalog_rewriter(path: Path = CATALOG_PATH) -> Callable[[SearchQuery], str]:
    """팀 런타임의 리라이트 콜백에 연결할 함수를 반환한다."""
    rewrite = make_question_rewriter(path)

    def rewrite_resolved(query: SearchQuery) -> str:
        district = getattr(query, "district", None)
        dong = getattr(query, "dong", None)
        return rewrite(
            query.search_query,
            district=district if isinstance(district, str) else None,
            dong=dong if isinstance(dong, str) else None,
        )

    return rewrite_resolved


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", help="지역이 해석된 검색 질의")
    parser.add_argument("--catalog", type=Path, default=CATALOG_PATH)
    args = parser.parse_args()
    print(make_question_rewriter(args.catalog)(args.question))


if __name__ == "__main__":
    main()
