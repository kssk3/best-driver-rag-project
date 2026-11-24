"""장소 목록·지도 테스트. 합성 예시(fixtures)만 사용한다."""

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src.interface.adapter import to_place_result
from src.interface.map import split_by_coordinates

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
    assert any("지도 표시 2곳" in c.value and "좌표 없음 1곳" in c.value for c in app.caption)
    assert any("확인된 수거 종류 없음" in m.value for m in app.markdown)
    assert any("좌표 없음: 지도에 표시되지 않음" in m.value for m in app.markdown)
    assert len(app.get("deck_gl_json_chart")) == 1


def test_empty_places_is_not_an_error() -> None:
    app = pick_places("empty")
    assert not app.exception
    assert any("해당하는 장소가 없습니다" in i.value for i in app.info)
    assert not app.error
    assert len(app.get("deck_gl_json_chart")) == 0


def test_unavailable_is_neither_empty_nor_error() -> None:
    app = pick_places("unavailable")
    assert not app.exception
    assert any("아직 연결되지 않았습니다" in i.value for i in app.info)
    assert not any("해당하는 장소가 없습니다" in i.value for i in app.info)
    assert not app.error


def test_place_lookup_error_is_shown_as_error() -> None:
    app = pick_places("error")
    assert not app.exception
    assert any("조회하지 못했습니다" in e.value for e in app.error)
    assert not any("해당하는 장소가 없습니다" in i.value for i in app.info)
