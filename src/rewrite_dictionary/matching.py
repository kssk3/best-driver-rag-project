"""문장 안에서 품목을 찾고 언어에 따라 검색어 표현을 정규화한다."""

import re
import unicodedata
from collections.abc import Mapping

from .aliases import item_key

_EXCLUDED_ITEM = re.compile(
    r"""["'”’)]?(?:은|는|이|가|을|를|만|도)?[^\S\r\n]*"""
    r"(?:말고|빼고|아닌|아니고|아니라|제외(?:하고|한|하면)?)(?!\w)"
)
_STATE_PREFIXES = ("깨진", "파손된", "빈", "비운", "투명", "무색")
_NEGATION = r"(?:전혀[^\S\r\n]+(?:안[^\S\r\n]+)?|(?:안|덜)[^\S\r\n]+)"
_NEGATED_STATE = re.compile(rf"(?<!\w){_NEGATION}\Z")
_OPTION_JOIN = re.compile(
    r"[^\S\r\n]*(?:하고|이랑|이나|랑|과|와|나|및|[,·+])[^\S\r\n]*"
)
_SELECTION = re.compile(r"[^\S\r\n]+중(?:에서|에는|에)?[^\S\r\n]+")
_ONLY = re.compile(r"[^\S\r\n]*만(?:은|을|이라도)?(?!\w)")
_DIRECT_DISPOSAL = re.compile(
    r"[^\S\r\n]*(?:(?:어디(?:에|로|다)?|어떻게)[^\S\r\n]+)?"
    r"(?:버려(?:요|도[^\S\r\n]+(?:돼(?:요)?|되나요))?|"
    r"버리(?:나요|려면|면[^\S\r\n]+되나요)|배출(?:해요|하나요))"
    r"[^\S\r\n]*[.?!…]*"
)
_LOCATION_PREFIX = re.compile(
    r"[^\S\r\n]*(?:(?:송파구|서대문구)(?:[^\S\r\n]+[가-힣]+[0-9]*동)?"
    r"(?:에서|은|는)?[^\S\r\n]+)?"
)
_STATE = rf"(?:{_NEGATION})?(?:씻은|비운|빈|깨진|파손된|오염된|내용물이[^\S\r\n]+남은)"
# (선택용 품목, 사전의 검색어, 같은 품목을 가리키는 확인된 표기)
_SELECTION_SPELLING_GROUPS = (
    ("스티로폼", "스티로폼", ("스치로폼", "스치로폴", "스티로품", "스티로폴")),
    ("페트병", "페트병", ("패트병",)),
    ("유리병", "유리병", ("유리벵",)),
    ("족발뼈", "돼지뼈", ("족빨뼈",)),
)
_STATE_BEFORE_ITEM = re.compile(rf"(?<!\w)({_STATE})[^\S\r\n]+\Z")
_STATE_WITHIN_ITEM = re.compile(rf"({_STATE})[^\S\r\n]+")


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


def selection_spelling_aliases(aliases: Mapping[str, str]) -> dict[str, str]:
    """현재 사전에도 같은 품목으로 등록된 표기 차이만 찾는다."""
    return {
        spelling: item
        for item, search_term, spellings in _SELECTION_SPELLING_GROUPS
        if item_key(aliases.get(item, item)) == search_term
        for spelling in spellings
        if item_key(aliases.get(spelling, "")) == search_term
    }


def _direct_disposal_selection(
    question: str,
    chosen: list[re.Match[str]],
    aliases: Mapping[str, str],
) -> bool:
    only = _ONLY.match(question, chosen[-1].end("item"))
    if only is None:
        return False
    end = only.end()

    # 줄여도 되는 단순한 배출 질문만 확인한다. 나머지나 다른 절이 있으면 전체를 보존한다.
    disposal = _DIRECT_DISPOSAL.fullmatch(question, end)
    if disposal is not None:
        return True

    # 이미 보강한 질의를 다시 처리할 때는 선택한 품목의 검색어만 끝에 허용한다.
    names = {aliases.get(fold_item_text(item["item"])) for item in chosen}
    suffixes = [re.escape(f" ({name})") for name in names if name]
    if not suffixes:
        return False
    suffix_pattern = "|".join(sorted(suffixes))
    return (
        re.fullmatch(
            rf"{_DIRECT_DISPOSAL.pattern}(?:{suffix_pattern})+",
            question[end:].rstrip(" \t"),
        )
        is not None
    )


def _selection_options(
    question: str,
    matches: list[re.Match[str]],
    spelling_aliases: Mapping[str, str],
    aliases: Mapping[str, str],
) -> tuple[set[int], list[tuple[int, int]]]:
    """같은 열거에서 명시적으로 선택한 범위와 선택하지 않은 품목을 찾는다."""

    def selection_key(match: re.Match[str]) -> str:
        key = item_key(match["item"])
        return spelling_aliases.get(key, key)

    excluded: set[int] = set()
    spans: list[tuple[int, int]] = []
    for index in range(2, len(matches)):
        first_selected = matches[index]
        last_option = matches[index - 1]
        if not _SELECTION.fullmatch(
            question, last_option.end("item"), first_selected.start()
        ):
            continue
        last_selected = index
        while last_selected + 1 < len(matches) and _OPTION_JOIN.fullmatch(
            question,
            matches[last_selected].end("item"),
            matches[last_selected + 1].start(),
        ):
            last_selected += 1
        if not _direct_disposal_selection(
            question, matches[index : last_selected + 1], aliases
        ):
            continue
        first_option = index - 1
        while first_option > 0 and _OPTION_JOIN.fullmatch(
            question,
            matches[first_option - 1].end("item"),
            matches[first_option].start(),
        ):
            first_option -= 1
        prior_terms = [selection_key(match) for match in matches[first_option:index]]
        selected_terms = {
            selection_key(match) for match in matches[index : last_selected + 1]
        }
        if selected_terms < set(prior_terms):
            excluded.update(
                option
                for option, term in enumerate(prior_terms, start=first_option)
                if term not in selected_terms
            )
            spans.append((matches[first_option].start(), first_selected.start()))
    return excluded, spans


def _is_location_prefix(prefix: str, district: str | None, dong: str | None) -> bool:
    names = [re.escape(fold_item_text(name)) for name in (district, dong) if name]
    if not names:
        return _LOCATION_PREFIX.fullmatch(prefix) is not None
    if len(names) == 2:
        names.append(r"[^\S\r\n]+".join(names))
    location = rf"(?:{'|'.join(names)})(?:에서|은|는)?"
    return re.fullmatch(rf"[^\S\r\n]*(?:{location}[^\S\r\n]+)?", prefix) is not None


def project_selected_items(
    pattern: re.Pattern[str],
    question: str,
    spelling_aliases: Mapping[str, str],
    aliases: Mapping[str, str],
    *,
    district: str | None = None,
    dong: str | None = None,
) -> str:
    """문장 첫 열거문만 덜어내며, 앞부분에 지역 외 조건이 있으면 보존한다."""
    _, spans = _selection_options(
        question, list(pattern.finditer(question)), spelling_aliases, aliases
    )
    if len(spans) == 1:
        start, end = spans[0]
        prefix = question[:start]
        if _is_location_prefix(prefix, district, dong):
            return prefix + question[end:]
    return question


def active_item_matches(
    pattern: re.Pattern[str],
    question: str,
    spelling_aliases: Mapping[str, str],
    aliases: Mapping[str, str],
) -> list[re.Match[str]]:
    question = unicodedata.normalize("NFC", question)
    matches = list(pattern.finditer(question))
    excluded, _ = _selection_options(question, matches, spelling_aliases, aliases)
    active: list[re.Match[str]] = []
    for index, match in enumerate(matches):
        if index in excluded or is_excluded_mention(question, match.end()):
            continue
        negation = _NEGATED_STATE.search(question, 0, match.start())
        if negation and match["item"].startswith(_STATE_PREFIXES):
            # 부정된 상태의 별칭을 피하고 확인된 기본 품목을 읽는다.
            state = _STATE_WITHIN_ITEM.match(match["item"])
            if state is None:
                continue
            base = pattern.fullmatch(question, match.start() + state.end(), match.end())
            if base is None or base["item"].startswith(_STATE_PREFIXES):
                continue
            match = base
        active.append(match)
    return active


def mentioned_items(matches: list[re.Match[str]]) -> dict[str, str]:
    mentions: dict[str, str] = {}
    for match in matches:
        surface = match["item"]
        mentions.setdefault(fold_item_text(surface), surface)
    return mentions


def stated_item_condition(match: re.Match[str]) -> str | None:
    """품목 바로 앞 또는 품목명 첫머리에서 명시된 상태만 읽는다."""
    state = _STATE_BEFORE_ITEM.search(match.string, 0, match.start())
    if state is None:
        state = _STATE_WITHIN_ITEM.match(match["item"])
    return state[1] if state else None
