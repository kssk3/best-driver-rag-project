"""품목 별칭과 공식 품목명 연결. 담당: 이정은."""

# 사용자 표현과 공식 품목명 연결
ITEM_ALIASES = {
    "우유팩": "종이팩",
    "두유팩": "종이팩",
    "소주팩": "종이팩",
}


def normalize_item(item: str) -> str:
    """품목명 하나를 공식 표기로 변환."""
    return ITEM_ALIASES.get(item, item)
