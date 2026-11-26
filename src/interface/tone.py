"""화면에 보이는 답변의 말투만 당번이(너구리)처럼 바꾼다. 실행 기록과 평가는 원문 그대로다.

첫 문장과 마지막 문장의 끝(다/요 + 마침표·느낌표) 앞에 '구리'를 붙인다. 문장의 뜻과 숫자는
건드리지 않는다. 표·HTML·목록처럼 보이는 문장과 물음표 문장은 그대로 둔다.
"""

import re

SENTENCE_BREAK = re.compile(r"((?<=[.!?])\s+)")
ENDING = re.compile(r"(?<=[다요])([.!])$")


def _tone(sentence: str) -> str:
    stripped = sentence.rstrip()
    if re.search(r"[<>|]", stripped) or stripped.startswith(("-", "#", "*")):
        return sentence
    match = ENDING.search(stripped)
    if match is None:
        return sentence
    return (
        stripped[: match.start()] + "구리" + match.group(1) + sentence[len(stripped) :]
    )


def raccoon_tone(text: str) -> str:
    parts = SENTENCE_BREAK.split(text)  # [문장, 구분, 문장, 구분, ...]
    parts[0] = _tone(parts[0])
    if len(parts) > 1:
        parts[-1] = _tone(parts[-1])
    return "".join(parts)
