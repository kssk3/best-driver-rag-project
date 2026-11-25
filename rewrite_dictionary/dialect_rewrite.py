"""방언과 구어가 포함된 질문에서 검색에 사용할 문자열을 만든다."""

import json
import re
from collections.abc import Callable
from functools import cache, partial
from pathlib import Path

if __package__:
    from .technical_terms import expand_material_codes
else:
    from technical_terms import expand_material_codes

_DICTIONARY_PATH = Path(__file__).with_name("dialect_dictionary.json")
_LOANWORD_PATH = Path(__file__).with_name("loanword_dictionary.json")
_EXPRESSION_BOUNDARY = r"(?<!\w)"
_EXPRESSION_SPACE = r"[^\S\r\n]+"
_MODE_ORDER = ("word", "before_action", "before_disposal", "ending", "item")
_MODE_SUFFIXES = {
    "ending": r"(?=[?？.!！。… \t]*\Z)",
    "before_action": (
        r"(?=[^\S\r\n]*(?:버리|버려|버릴|내놓|내놔|배출|분리|수거|처리|반납))"
    ),
    "before_disposal": (
        r"(?=[^\S\r\n]+(?:그대로[^\S\r\n]+)?(?:버리|버려|버릴|내놓|내놔|내도|배출))"
    ),
    "word": r"(?!\w)",
}
_WASTE_CONTEXT = re.compile(
    r"쓰레기|폐기|분리|재활용|버리|버려|버릴|배출|수거|처리|내놓|내놔|반납"
    r"|\b(?:dispose|disposal|discard|recycle|waste|throw away)\b",
    re.IGNORECASE,
)
_WASHABLE_ITEM = re.compile(
    r"(?<!\w)(?:유리\s*병|우유\s*팩|두유\s*팩|종이\s*팩|페트\s*병|금속\s*캔|음료\s*캔)"
    r"(?:[은는이가을를도])?[^\S\r\n]+\Z"
)
_QUOTED = re.compile(
    r"""("[^"\n]*"|'[^'\n]*'|“[^”\n]*”|‘[^’\n]*’|「[^」\n]*」|『[^』\n]*』|《[^》\n]*》|〈[^〉\n]*〉)"""
)
_PARTICLE_PAIRS = (
    ("은", "는"),
    ("이", "가"),
    ("을", "를"),
    ("과", "와"),
    ("이랑", "랑"),
    ("이나", "나"),
    ("이요", "요"),
    ("으로", "로"),
)
_INFLECTED_PARTICLES = {particle: pair for pair in _PARTICLE_PAIRS for particle in pair}
_UNCHANGING_PARTICLES = ("에서", "에서만", "에", "에는", "도", "만", "의", "하고")
_PARTICLES = "|".join(
    sorted((*_INFLECTED_PARTICLES, *_UNCHANGING_PARTICLES), key=len, reverse=True)
)
_MODE_SUFFIXES["item"] = rf"(?P<particle>{_PARTICLES})?(?!\w)"
_QUESTION_END = re.compile(r"[?？.!！。… \t]+\Z")
_SHORT_ITEM_QUESTION = re.compile(
    r"[^\S\r\n]+어떻게 (?:해야 하나요|하나요|하려고 하나요)[?？.!！。… \t]*\Z"
)


def read_dictionary() -> dict:
    """품목 사전의 구성과 오프라인 실행에 같은 규칙을 쓴다."""
    return json.loads(_DICTIONARY_PATH.read_text(encoding="utf-8"))


def read_loanwords() -> dict:
    """외국어 제품명, 외래어 표기 변형, 일본어계 생활어를 읽는다."""
    return json.loads(_LOANWORD_PATH.read_text(encoding="utf-8"))


def language_matching_rules() -> dict:
    """실행 중 사용하는 언어 일치 조건을 품목 사전에 담는다."""
    return {
        "mode_order": _MODE_ORDER,
        "expression_left_boundary": _EXPRESSION_BOUNDARY,
        "expression_space_pattern": _EXPRESSION_SPACE,
        "suffix_patterns_by_mode": _MODE_SUFFIXES,
        "patterns": {
            name: {"pattern": regex.pattern, "flags": int(regex.flags)}
            for name, regex in {
                "waste_context": _WASTE_CONTEXT,
                "washable_item": _WASHABLE_ITEM,
                "protected_quotes": _QUOTED,
                "question_end": _QUESTION_END,
                "short_item_question": _SHORT_ITEM_QUESTION,
            }.items()
        },
        "particle_pairs": _PARTICLE_PAIRS,
        "unchanging_particles": _UNCHANGING_PARTICLES,
    }


def _particle_for(word: str, particle: str, pairs: dict[str, list[str]]) -> str:
    pair = pairs.get(particle)
    if pair is None or not "가" <= word[-1] <= "힣":
        return particle
    final_consonant = (ord(word[-1]) - ord("가")) % 28
    if particle in {"으로", "로"} and final_consonant == 8:
        return "로"
    return pair[0 if final_consonant else 1]


def make_language_normalizer(vocabulary: dict, config: dict) -> Callable[[str], str]:
    patterns = {
        name: re.compile(entry["pattern"], entry["flags"])
        for name, entry in config["patterns"].items()
    }
    pairs = {particle: pair for pair in config["particle_pairs"] for particle in pair}
    forms_by_mode = {mode: {} for mode in config["mode_order"]}
    for rule in vocabulary["rules"]:
        forms = forms_by_mode[rule["match"]]
        for expression, standard in rule["forms"].items():
            expression = expression.casefold()
            if expression in forms:
                raise ValueError(f"중복 언어 사전 표현: {expression}")
            forms[expression] = standard

    matchers = []
    for mode, forms in forms_by_mode.items():
        if not forms:
            continue
        separator = config["expression_space_pattern"]
        expressions = "|".join(
            separator.join(map(re.escape, expression.split()))
            for expression in sorted(forms, key=len, reverse=True)
        )
        boundary = config["expression_left_boundary"]
        suffix = config["suffix_patterns_by_mode"][mode]
        matcher = re.compile(
            f"{boundary}(?P<expression>{expressions}){suffix}", re.IGNORECASE
        )
        matchers.append((mode, matcher, forms))

    def replacement(
        match: re.Match[str], *, mode: str, forms: dict[str, str], item_context: bool
    ) -> str:
        if mode == "before_disposal" and not patterns["washable_item"].search(
            match.string[: match.start()]
        ):
            return match[0]
        standard = forms.get(" ".join(match["expression"].casefold().split()))
        if standard is None:
            return match[0]
        if mode == "before_action" and not match.string[match.end()].isspace():
            return standard + " "
        if mode == "item":
            if not item_context and not patterns["short_item_question"].match(
                match.string, match.end()
            ):
                return match[0]
            return standard + _particle_for(standard, match["particle"] or "", pairs)
        return standard

    def normalize(question: str) -> str:
        parts = patterns["protected_quotes"].split(question)
        waste_context = any(
            patterns["waste_context"].search(part) for part in parts[::2]
        )
        for index in range(0, len(parts), 2):
            part = parts[index]
            for mode, matcher, forms in matchers:
                if mode == "ending" and index != len(parts) - 1:
                    continue
                item_context = waste_context or (
                    mode == "item"
                    and len(parts) == 1
                    and matcher.fullmatch(
                        patterns["question_end"].sub("", part).strip()
                    )
                    is not None
                )
                part = matcher.sub(
                    partial(
                        replacement, mode=mode, forms=forms, item_context=item_context
                    ),
                    part,
                )
            parts[index] = part
        return "".join(parts)

    return normalize


@cache
def _default_dialect_normalizer() -> Callable[[str], str]:
    return make_language_normalizer(read_dictionary(), language_matching_rules())


@cache
def _default_loanword_normalizer() -> Callable[[str], str]:
    return make_language_normalizer(read_loanwords(), language_matching_rules())


def normalize_dialect(question: str) -> str:
    """인용문과 나머지 조건을 유지하며 방언 문형을 표준 검색 표현으로 바꾼다."""
    return _default_dialect_normalizer()(question)


def normalize_search_language(question: str) -> str:
    """방언과 외래어를 다듬고 재질 문맥의 약어를 검색어로 보강한다."""
    language = _default_loanword_normalizer()(normalize_dialect(question))
    return expand_material_codes(language)
