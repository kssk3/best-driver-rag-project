"""문장 안에서 품목을 찾고 언어에 따라 검색어 표현을 정규화한다."""

import re
import unicodedata

_EXCLUDED_ITEM = re.compile(
    r"""["'”’)]?(?:은|는|이|가|을|를|만|도)?[^\S\r\n]*"""
    r"(?:말고|빼고|아닌|아니고|아니라|제외(?:하고|한|하면)?)(?!\w)"
)
_STATE_PREFIXES = ("깨진", "파손된", "빈", "비운", "투명", "무색")
_NEGATED_STATE = re.compile(r"(?<!\w)(?:안|덜|전혀)[^\S\r\n]+\Z")


def fold_item_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())


def compile_item_matcher(terms: set[str], rules: dict) -> re.Pattern[str]:
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


def is_excluded_mention(question: str, end: int) -> bool:
    """확인한 품목이나 재질 표현 바로 뒤의 명시적 제외를 찾는다."""
    return _EXCLUDED_ITEM.match(question, end) is not None


def mentioned_items(pattern: re.Pattern[str], question: str) -> dict[str, str]:
    question = unicodedata.normalize("NFC", question)
    mentions: dict[str, str] = {}
    for match in pattern.finditer(question):
        if is_excluded_mention(question, match.end()):
            continue
        surface = match["item"]
        if surface.startswith(_STATE_PREFIXES) and _NEGATED_STATE.search(
            question, 0, match.start()
        ):
            continue
        mentions.setdefault(fold_item_text(surface), surface)
    return mentions
