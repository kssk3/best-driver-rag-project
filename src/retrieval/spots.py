"""장소 저장과 조회.

담당: 이명지
상태: getSpot 응답을 공용 장소 형식(PlaceResult)으로 정리하는 단계.
DB 저장과 품목별 조회는 다음 단계에서 추가한다.

getSpot 응답에서 확인한 사실 (2026-11-24 실제 호출):
- 항목 필드는 spotNm(장소명), addrBase(주소), addrDtl(상세)뿐이다. 좌표와 품목 필드가 없다.
- addr(동 이름) 검색 결과에 다른 시의 같은 이름 동(예: 인천 연희동)이 섞인다.

흐름:
사용자 질문 "연희동 폐건전지 어디에 버리나요?" -> 답변 + 근처 수거함 목록을 보여주기
getSpot API는 그 장소 정보를 주는 역할.

getSpot API (날것)  →  [spots.py: 정리]  →  PlaceResult (팀 공용 형식)  →  승주 님 화면
"""

from src.contracts import PlaceResult

GETSPOT_SOURCE_URL = "https://www.data.go.kr/data/15156866/openapi.do"

# 장소명에서 찾을 품목 키워드. 같은 품목이 여러 표기로 와서(폐형광등·폐건전지 / 폐형광등 폐건전지)
# 장소명 전체가 아니라 키워드 포함 여부로 판단한다.
# 2026-11-25 실제 응답 샘플(연희동·잠실동)의 장소명 전체를 확인해 정했다.
COLLECTION_KEYWORDS: tuple[str, ...] = (
    "폐건전지",
    "폐형광등",
    "의류",
    "폐의약품",
    "투명페트병",
    "종이팩",
    "아이스팩",
    "소형가전",
    "폐가전",
    "캔",
    "폐식용유",
    "폐휴대폰",
)

# 장소명에 이 표시가 있으면 받는 품목을 추론하지 않는다.
# - 판매소: 종량제봉투를 파는 곳이지 무언가를 받는 곳이 아니다.
# - RFID: 음식물 종량기는 등록 세대의 RFID 카드가 있어야 쓸 수 있어 일반 안내에서 뺀다.
NON_COLLECTION_MARKERS: tuple[str, ...] = ("판매소", "RFID")


def extract_items(raw: dict) -> list[dict]:
    """getSpot 응답 JSON에서 장소 항목 목록을 꺼낸다.

    결과가 없으면 items가 비어 있거나 항목이 하나뿐이면 list가 아닐 수 있어 모두 list로 맞춘다.
    """
    items = raw.get("response", {}).get("body", {}).get("items") or {}
    item = items.get("item", []) if isinstance(items, dict) else items
    if isinstance(item, dict):
        return [item]
    return list(item)


def infer_collection_types(spot_name: str) -> list[str]:
    """장소명에서 받는 품목을 추론한다.

    예: "폐형광등·폐건전지 수거함" → ["폐건전지", "폐형광등"]
    품목 키워드가 없거나 수거 장소가 아니면(ex. 판매소, RFID) 빈 목록
    (모르는 품목을 받는다고 단정하지 않는다).
    """
    if any(marker in spot_name for marker in NON_COLLECTION_MARKERS):
        return []

    # COLLECTION_KEYWORDS 중 spot_name 안에 들어 있는 것만 모아서 돌려주기
    found = []
    for keyword in COLLECTION_KEYWORDS:
        if keyword in spot_name:
            found.append(keyword)
    return found


def parse_places(raw: dict, district: str) -> list[PlaceResult]:
    """getSpot 응답을 district(예: "서대문구")에 있는 장소만 PlaceResult로 바꾼다.

    좌표는 응답에 없으므로 None으로 둔다 (추측해서 채우지 않는다).
    좌표가 없어 상세 위치(addrDtl)가 찾아가는 단서이므로, 있으면 주소 뒤에 붙인다.
    이름·주소·상세가 모두 같은 항목은 한 번만 남긴다.
    """
    places: list[PlaceResult] = []
    seen_ids: set[str] = set()

    for item in extract_items(raw):
        # 1. 빈 값(null) 정리
        # 공공 API는 빈 값을 null로 줄 수 있다. .get(키, "")는 키가 없을 때만 ""를 쓰고
        # 값이 None이면 None을 돌려주므로, `or ""`로 None도 빈 문자열로 맞춘다.
        base_address = item.get("addrBase") or ""

        # 2. 다른 시(인천 연희동 등)를 거르기.
        # 상세 위치에 다른 구 이름이 섞여도 헷갈리지 않도록
        # 구 판단은 기본 주소(addrBase)로만 한다.
        # 주소에 "서대문구"가 없으면 버림
        if district not in base_address:
            continue

        # 3. 주소 만들기
        detail = (item.get("addrDtl") or "").strip()
        # 기본 주소 + 상세 위치 (주민센터)
        address = f"{base_address} {detail}" if detail else base_address
        spot_name = item.get("spotNm") or ""

        # 4. 번호(ID) 만들기
        # getspot: 이름|주소|상세
        # 순번은 검색·필터 조건마다 바뀌므로 장소 정보로 ID를 만든다 (같은 장소 = 같은 ID).
        place_id = f"getspot:{spot_name}|{base_address}|{detail}"

        # 5. 중복 거르기
        # 실제 응답에 이름·주소·상세가 완전히 같은 항목이 여러 번 온다
        # (2026-11-25 샘플 확인: 연희동 15곳, 잠실동 52곳이 2~4번씩 반복).
        # 서로 다른 장소인지 구분할 정보가 없어 한 번만 남긴다.
        if place_id in seen_ids:
            continue
        seen_ids.add(place_id)

        # PlaceResult로 만들어서 목록에 추가
        places.append(
            PlaceResult(
                name=spot_name,
                address=address,
                source_url=GETSPOT_SOURCE_URL,
                collection_types=infer_collection_types(spot_name),
                place_id=place_id,
            )
        )
    return places
