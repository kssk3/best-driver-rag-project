"""장소 목록과 지도.

담당: 이승주
장소 결과의 좌표와 출처로 목록과 지도를 표시한다.
수거 종류를 확인하지 못한 장소는 확인된 종류가 없다고만 보여 주고 단정하지 않는다.
"""

from urllib.parse import quote

import streamlit as st

from src.interface.adapter import Place, PlaceResult
from src.interface.chat import is_safe_url

MAP_SEARCH_URLS = (
    ('카카오맵', 'https://map.kakao.com/link/search/'),
    ('네이버지도', 'https://map.naver.com/p/search/'),
)


# 주소로 지도 검색 링크 생성
def map_search_links(address: str | None) -> list[tuple[str, str]]:
    text = (address or '').strip()
    if not text:
        return []
    return [(label, prefix + quote(text, safe='')) for label, prefix in MAP_SEARCH_URLS]


def has_coordinates(place: Place) -> bool:
    return place.latitude is not None and place.longitude is not None


def split_by_coordinates(places: list[Place]) -> tuple[list[Place], list[Place]]:
    mappable = [place for place in places if has_coordinates(place)]
    unmappable = [place for place in places if not has_coordinates(place)]
    return mappable, unmappable


def render_places(result: PlaceResult) -> None:

    if result.kind == 'fixture':
        st.caption('예시(합성) 장소입니다. 실제 조회가 아닙니다.')

    if result.status == 'error':
        st.error('장소를 조회하지 못했습니다. 잠시 후 다시 시도하세요.')
        return 

    if result.status == 'unavailable':
        st.info('장소 조회가 아직 연결되지 않았습니다. (결과 없음이나 오류가 아닙니다.)')
        return 

    if result.status == 'empty' or not result.places:
        st.info('해당하는 장소가 없습니다.')
        return

    mappable, unmappable = split_by_coordinates(result.places)
    st.caption(
        f'장소 {len(result.places)}곳 · 지도 표시 {len(mappable)}곳 · 좌표 없음 {len(unmappable)}곳'
    )
    if mappable:
        st.map(
            [
                {'latitude': place.latitude, 'longitude': place.longitude} for place in mappable
            ]
        )
    else:
        st.warning('좌표가 있는 장소가 없어 지도를 그릴 수 없습니다.')

    for place in result.places:
        st.markdown(_place_line(place))
    st.caption('기준 위치가 없으므로 거리순 정렬은 하지 않습니다.')


def _place_line(place: Place) -> str:
    types = ', '.join(place.collection_types) or '확인된 수거 종류 없음'

    if is_safe_url(place.source_url):
        source = f'[출처]({place.source_url})'
    else:
        source = '출처 링크 없음'

    line = f'- {place.name} · {place.address or '주소 없음'}'
    line += f' · 수거 종류: {types} · {source}'
    links = map_search_links(place.address)
    
    if links:
        line += ' · 지도에서 보기: ' + ' / '.join(
            f'[{label}]({url})' for label, url in links
        )

    if not has_coordinates(place):
        line += ' · (좌표 없음: 지도에 표시되지 않음)'
    
    return line