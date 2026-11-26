import json
from pathlib import Path

from src.retrieval.spots import extract_items, infer_collection_types, parse_places

FIXTURE = Path(__file__).parent.parent / "fixtures" / "getspot_yeonhui_sample.json"


def load_sample() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_extract_items_reads_nested_list():
    # 응답은 response → body → items → item 안에 있다.
    assert len(extract_items(load_sample())) == 5


def test_extract_items_handles_empty_result():
    # 결과 없음(NODATA)이면 items가 빈 문자열로 올 수 있다 → 빈 목록.
    raw = {"response": {"header": {"resultCode": "03"}, "body": {"items": ""}}}
    assert extract_items(raw) == []


def test_extract_items_wraps_single_item_dict():
    # 결과가 하나뿐이면 item이 목록이 아니라 dict 하나로 올 수 있다 → 목록으로 맞춘다.
    spot = {"spotNm": "의류 수거함"}
    raw = {"response": {"body": {"items": {"item": spot}}}}

    assert extract_items(raw) == [spot]


def test_infer_collection_types_from_spot_name():
    # 표기가 달라도(·, 공백) 같은 품목을 찾는다.
    assert sorted(infer_collection_types("폐형광등·폐건전지 수거함")) == [
        "폐건전지",
        "폐형광등",
    ]
    assert sorted(infer_collection_types("폐형광등 폐건전지 수거함")) == [
        "폐건전지",
        "폐형광등",
    ]


def test_infer_collection_types_returns_empty_for_unknown_name():
    # 품목을 알 수 없는 장소명은 빈 목록 (받는다고 단정하지 않는다).
    assert infer_collection_types("재활용정거장") == []


def test_infer_collection_types_excludes_sales_place():
    # 판매소는 파는 곳이지 받는 곳이 아니다 → 수거 품목에서 제외 (PR 리뷰 반영).
    assert infer_collection_types("종량제봉투 판매소") == []


def test_infer_collection_types_excludes_rfid_food_waste_bin():
    # 음식물 RFID 종량기는 등록 세대만 쓸 수 있어 일반 안내에서 뺀다.
    assert infer_collection_types("음식물류폐기물 종량기 RFID") == []


def test_infer_collection_types_recognizes_added_keywords():
    # 실제 응답에서 품목이 분명한데 빠져 있던 장소명.
    assert infer_collection_types("캔 무인회수기") == ["캔"]
    assert infer_collection_types("폐식용유 수거함") == ["폐식용유"]
    assert infer_collection_types("폐휴대폰 배출처") == ["폐휴대폰"]


def test_parse_places_drops_other_city_with_same_dong_name():
    # 인천 연희동은 빼고 서대문구 장소만 남긴다.
    places = parse_places(load_sample(), "서대문구")

    assert len(places) == 4
    assert all("서대문구" in place.address for place in places)


def test_parse_places_keeps_unknown_coordinates_as_none():
    # getSpot 응답에 좌표가 없으므로 추측하지 않고 None으로 둔다.
    place = parse_places(load_sample(), "서대문구")[0]

    assert place.name == "폐형광등·폐건전지 수거함"
    assert place.latitude is None and place.longitude is None
    assert sorted(place.collection_types) == ["폐건전지", "폐형광등"]


def test_parse_places_handles_null_fields():
    # 공공 API는 빈 값을 null로 줄 수 있다 → 에러 없이 빈 문자열로 처리 (PR 리뷰 반영).
    item = {
        "spotNm": None,
        "addrBase": "서울특별시 서대문구 연희동 9-9",
        "addrDtl": None,
    }
    null_city = {"spotNm": "의류 수거함", "addrBase": None, "addrDtl": None}
    raw = {"response": {"body": {"items": {"item": [item, null_city]}}}}

    places = parse_places(raw, "서대문구")

    assert len(places) == 1  # 주소가 null이면 구를 확인할 수 없어 제외
    assert places[0].name == ""
    assert places[0].address == "서울특별시 서대문구 연희동 9-9"
    assert places[0].collection_types == []


def test_parse_places_keeps_detail_address():
    # 좌표가 없으니 상세 위치가 있으면 주소에 남긴다 (PR 리뷰 반영).
    # 상세 위치가 비어 있으면 끝에 공백을 붙이지 않는다.
    places = parse_places(load_sample(), "서대문구")

    assert places[0].address == "서울특별시 서대문구 연희동 1-1 연희동 주민센터"
    assert places[1].address == "서울시 서대문구 연희로 10"


def test_parse_places_keeps_same_place_id_regardless_of_order():
    # 장소 순서가 바뀌어도 같은 장소는 같은 place_id (PR 리뷰 반영).
    raw = load_sample()
    reversed_raw = load_sample()
    reversed_raw["response"]["body"]["items"]["item"].reverse()

    ids = {p.name: p.place_id for p in parse_places(raw, "서대문구")}
    reversed_ids = {p.name: p.place_id for p in parse_places(reversed_raw, "서대문구")}

    assert ids == reversed_ids


def test_parse_places_drops_exact_duplicates():
    # 이름·주소·상세가 완전히 같은 항목은 한 번만 남긴다 (실제 응답에서 확인한 중복).
    spot = {
        "spotNm": "종량제봉투 판매소",
        "addrBase": "서울특별시 송파구 석촌호수로 61",
    }
    other = {"spotNm": "의류수거함", "addrBase": "서울특별시 송파구 석촌호수로 61"}
    raw = {"response": {"body": {"items": {"item": [spot, dict(spot), other]}}}}

    places = parse_places(raw, "송파구")

    # 같은 주소라도 이름이 다르면 다른 장소로 남는다.
    assert [p.name for p in places] == ["종량제봉투 판매소", "의류수거함"]
    assert len({p.place_id for p in places}) == 2
