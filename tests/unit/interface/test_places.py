"""장소 목록·지도 테스트. 합성 예시(fixtures)만 사용한다."""

import json
from pathlib import Path
from urllib.parse import quote

import pytest
from streamlit.testing.v1 import AppTest

from src.interface.adapter import to_place_result
from src.interface.map import (
    MAP_SEARCH_URLS,
    kakao_search_url,
    map_search_links,
    split_by_coordinates,
)

FIXTURE_PATH = Path(__file__).parent.parent.parent / "fixtures" / "interface" / "sample_places.json"
APP_PATH = Path(__file__).parent.parent.parent.parent / "app.py"


def load_places() -> dict:
    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return {key: value for key, value in data.items() if not key.startswith("_")}


PLACES = load_places()


def pick_places(name: str) -> AppTest:
    app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
    app.selectbox[2].select(name)
    return app.run()


@pytest.mark.parametrize("name", PLACES)
def test_place_status_is_preserved(name: str) -> None:
    result = to_place_result(PLACES[name], kind="fixture")
    assert result.status == name


def test_unknown_place_status_raises() -> None:
    with pytest.raises(ValueError):
        to_place_result({"status": "ok"}, kind="fixture")


@pytest.mark.parametrize(
    "latitude, longitude",
    [(999, 126.9), (37.5, 999), ("abc", 126.9), (None, 126.9), (True, 126.9)],
)
def test_invalid_or_out_of_range_coordinates_count_as_missing(
    latitude: object, longitude: object
) -> None:
    raw = {
        "status": "found",
        "places": [
            {
                "place_id": "fx",
                "name": "가상",
                "latitude": latitude,
                "longitude": longitude,
            }
        ],
    }
    place = to_place_result(raw, kind="fixture").places[0]
    assert place.latitude is None or place.longitude is None


def test_numeric_string_coordinates_are_accepted() -> None:
    raw = {
        "status": "found",
        "places": [
            {"place_id": "fx", "name": "가상", "latitude": "37.5", "longitude": "126.9"}
        ],
    }
    place = to_place_result(raw, kind="fixture").places[0]
    assert (place.latitude, place.longitude) == (37.5, 126.9)


def test_split_by_coordinates() -> None:
    places = to_place_result(PLACES["found"], kind="fixture").places
    mappable, unmappable = split_by_coordinates(places)
    assert len(mappable) == 2
    assert len(unmappable) == 1


def test_found_places_show_counts_map_and_no_confirmed_types() -> None:
    app = pick_places("found")
    assert not app.exception
    assert any(c.value == "장소 3곳" for c in app.caption)
    assert any("확인된 수거 종류 없음" in m.value for m in app.markdown)
    # 좌표 지도(st.map)는 쓰지 않는다. 좌표가 없다는 경고도 띄우지 않는다.
    assert len(app.get("deck_gl_json_chart")) == 0
    assert not any("지도를 그릴 수 없습니다" in w.value for w in app.warning)


def test_empty_places_is_not_an_error() -> None:
    app = pick_places("empty")
    assert not app.exception
    assert any("해당하는 장소가 없습니다" in i.value for i in app.info)
    assert not app.error
    assert len(app.get("deck_gl_json_chart")) == 0


def test_unavailable_is_neither_empty_nor_error() -> None:
    app = pick_places("unavailable")
    assert not app.exception
    assert any("조회 서비스 준비 중입니다" in i.value for i in app.info)
    assert not any("해당하는 장소가 없습니다" in i.value for i in app.info)
    assert not app.error


def test_place_lookup_error_is_shown_as_error() -> None:
    app = pick_places("error")
    assert not app.exception
    assert any("조회하지 못했습니다" in e.value for e in app.error)
    assert not any("해당하는 장소가 없습니다" in i.value for i in app.info)


def test_map_search_links_use_encoded_address() -> None:
    address = "서울특별시 서대문구 연희동 1-1"
    links = map_search_links(address)
    assert [label for label, _ in links] == [label for label, _ in MAP_SEARCH_URLS]
    for (_, prefix), (_, url) in zip(MAP_SEARCH_URLS, links):
        assert url == prefix + quote(address, safe="")


@pytest.mark.parametrize("address", [None, "", "   "])
def test_no_links_without_address(address: str | None) -> None:
    assert map_search_links(address) == []


def test_special_characters_cannot_change_the_link_structure() -> None:
    # 주소의 / ? & # 가 링크의 경로·검색어 구분으로 읽히면 안 된다.
    links = map_search_links("a/b?c=1&d#e (3층)")
    for (_, prefix), (_, url) in zip(MAP_SEARCH_URLS, links):
        tail = url[len(prefix):]
        assert url.startswith(prefix)
        assert not any(char in tail for char in "/?&#=() ")


def test_found_places_show_search_links() -> None:
    app = pick_places("found")
    assert not app.exception
    lines = [m.value for m in app.markdown if MAP_SEARCH_URLS[0][1] in m.value]
    assert len(lines) == 3  # 예시 장소 3곳 모두 주소가 있다
    assert all("지도에서 보기" in line for line in lines)


def test_kakao_search_url_uses_kakao_prefix_only() -> None:
    url = kakao_search_url("서울특별시 서대문구 연희동 1-1")
    assert url == MAP_SEARCH_URLS[0][1] + quote("서울특별시 서대문구 연희동 1-1", safe="")
    assert kakao_search_url(None) is None
    assert kakao_search_url("  ") is None


def test_found_places_embed_kakao_map_for_selected_place() -> None:
    app = pick_places("found")
    assert not app.exception
    frames = app.get("iframe")
    assert len(frames) == 1
    assert frames[0].proto.src.startswith("https://map.kakao.com/")


def test_no_embedded_map_when_no_places_are_shown() -> None:
    for name in ("empty", "unavailable", "error"):
        app = pick_places(name)
        assert not app.exception
        assert app.get("iframe") == []
