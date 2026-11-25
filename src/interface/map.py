"""장소 목록과 지도.

담당: 이승주
장소 결과의 주소와 출처로 목록을 보여 주고, 주소 검색 링크와 카카오맵 화면으로 위치를 안내한다.
좌표 지도는 지금 쓰지 않는다(파일 맨 아래 참고).
수거 종류를 확인하지 못한 장소는 확인된 종류가 없다고만 보여 주고 단정하지 않는다.
"""

from urllib.parse import quote

import streamlit as st

from src.interface.adapter import Place, PlaceResult
from src.interface.chat import is_safe_url

MAP_SEARCH_URLS = (
    ("카카오맵", "https://map.kakao.com/link/search/"),
    ("네이버지도", "https://map.naver.com/p/search/"),
)


# 주소로 지도 검색 링크 생성
def map_search_links(address: str | None) -> list[tuple[str, str]]:
    text = (address or "").strip()
    if not text:
        return []
    return [(label, prefix + quote(text, safe="")) for label, prefix in MAP_SEARCH_URLS]


# 주소의 카카오맵 검색 주소. 주소가 비어 있으면 None
def kakao_search_url(address: str | None) -> str | None:
    for label, url in map_search_links(address):
        if label == "카카오맵":
            return url
    return None


def render_places(result: PlaceResult) -> None:

    if result.kind == "fixture":
        st.caption("예시(합성) 장소입니다. 실제 조회가 아닙니다.")

    if result.status == "error":
        st.error("장소를 조회하지 못했습니다. 잠시 후 다시 시도하세요.")
        return

    if result.status == "unavailable":
        st.info("해당 지역은 조회 서비스 준비 중입니다.")
        return

    if result.status == "empty" or not result.places:
        st.info("해당하는 장소가 없습니다.")
        return

    st.caption(f"장소 {len(result.places)}곳")

    for place in result.places:
        st.markdown(_place_line(place))

    searchable = [place for place in result.places if map_search_links(place.address)]
    if searchable:
        chosen = st.selectbox(
            "지도에서 볼 장소",
            searchable,
            format_func=lambda place: f"{place.name} · {place.address}",
        )
        st.iframe(kakao_search_url(chosen.address), height=500)

    st.caption("기준 위치가 없으므로 거리순 정렬은 하지 않습니다.")


def _place_line(place: Place) -> str:
    types = ", ".join(place.collection_types) or "확인된 수거 종류 없음"

    if is_safe_url(place.source_url):
        source = f"[출처]({place.source_url})"
    else:
        source = "출처 링크 없음"

    line = f"- {place.name} · {place.address or '주소 없음'}"
    line += f" · 수거 종류: {types} · {source}"
    links = map_search_links(place.address)
    if links:
        line += " · 지도에서 보기: " + " / ".join(
            f"[{label}]({url})" for label, url in links
        )
    return line


# ---------------------------------------------------------------------------
# 아래는 지금 쓰지 않는 코드 (좌표로 지도 점을 찍는 방식)
# 나중에 좌표가 채워지면(지오코딩 또는 명지님 제공) render_places의 목록 뒤에서
# _render_coordinate_map(result.places)를 다시 호출하면 됩니다.
# 관련 테스트: tests/unit/interface/test_places.py의 test_split_by_coordinates
# ---------------------------------------------------------------------------
def has_coordinates(place: Place) -> bool:
    return place.latitude is not None and place.longitude is not None


def split_by_coordinates(places: list[Place]) -> tuple[list[Place], list[Place]]:
    mappable = [place for place in places if has_coordinates(place)]
    unmappable = [place for place in places if not has_coordinates(place)]
    return mappable, unmappable


def _render_coordinate_map(places: list[Place]) -> None:
    mappable, unmappable = split_by_coordinates(places)
    st.caption(f"지도 표시 {len(mappable)}곳 · 좌표 없음 {len(unmappable)}곳")
    if mappable:
        st.map(
            [
                {"latitude": place.latitude, "longitude": place.longitude}
                for place in mappable
            ]
        )
