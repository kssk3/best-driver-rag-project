"""구와 동 이름 해석.

담당: 이명지
상태: 연습용 매핑표로 질문 속 동 이름을 자치구로 해석한다.
실제 행정동·법정동 매핑표와 공용 반환 규격은 사용하는 담당자와 합의한 뒤 교체한다.
"""

from src.contracts import PipelineRequest, ResolvedQuery

# 동 이름 → 그 동이 있는 구 목록 (연습용. 실제 행정동·법정동 매핑표로 교체 예정)
DONG_TO_DISTRICTS: dict[str, list[str]] = {
    "연희동": ["서대문구"],
    "잠실동": ["송파구"],
    "신사동": ["강남구", "관악구"],
    "역삼동": ["강남구"],
}

SUPPORTED_DISTRICTS: set[str] = {"서대문구", "송파구"}

# 서울 25개 자치구. 질문에 구 이름을 직접 쓴 경우("송파구 페트병 언제?")를 알아본다.
# 지원하지 않는 구도 알아야 "지원하지 않음"으로 안내할 수 있어 서울 전체를 둔다.
SEOUL_DISTRICTS: tuple[str, ...] = (
    "종로구",
    "중구",
    "용산구",
    "성동구",
    "광진구",
    "동대문구",
    "중랑구",
    "성북구",
    "강북구",
    "도봉구",
    "노원구",
    "은평구",
    "서대문구",
    "마포구",
    "양천구",
    "강서구",
    "구로구",
    "금천구",
    "영등포구",
    "동작구",
    "관악구",
    "서초구",
    "강남구",
    "송파구",
    "강동구",
)


def find_district(question: str) -> str | None:
    """질문 속에서 서울 자치구 이름을 찾는다.

    긴 이름부터 확인해 짧은 이름이 긴 이름의 일부로 잘못 걸리지 않게 한다.

    Returns:
        찾은 구 이름. 질문에 구 이름이 없으면 None.
    """
    for district in sorted(SEOUL_DISTRICTS, key=len, reverse=True):
        if district in question:
            return district
    return None


def find_dong(question: str) -> str | None:
    """질문 속에서 매핑표에 있는 동 이름을 찾는다.

    Returns:
        찾은 동 이름. 질문에 매핑표의 동이 없으면 None.
    """
    for dong in DONG_TO_DISTRICTS:
        if dong in question:
            return dong
    return None


def resolve_region(question: str) -> dict:
    """질문 속 동 이름으로 자치구를 해석한다.

    모호하면 임의로 정하지 않는다(기획서 02). status는 내부 신호이며
    최종 응답 status 변환은 답변 생성 쪽에서 한다.

    Returns:
        status가 "ok" / "ambiguous" / "unsupported" / "no_dong" 중 하나인 dict.
    """
    dong = find_dong(question)
    if dong is None:
        return {"status": "no_dong"}

    districts = DONG_TO_DISTRICTS[dong]

    # 구가 여럿이면 하나를 고르지 않고 되묻는다. 지원 범위 검사보다 먼저 함.
    # 여러 구 검사를 먼저 하지 않으면 멋대로 신사동을 강남구로 찍어버림
    # (관악구일 가능성을 멋대로 차단함)
    if len(districts) > 1:
        return {"status": "ambiguous", "dong": dong, "candidate_districts": districts}

    district = districts[0]

    # 지원 범위인가?
    if district not in SUPPORTED_DISTRICTS:
        return {"status": "unsupported", "district": district, "dong": dong}

    return {"status": "ok", "district": district, "dong": dong}


def _ask_unsupported(
    request: PipelineRequest, district: str, dong: str | None
) -> ResolvedQuery:
    """지원 범위 밖의 구를 검색 없이 안내하는 ResolvedQuery를 만든다."""
    # 임시 결정: 지원하지 않는 구는 "되묻기"로 안내함 (답변 담당과 합의 전).
    # 화면·답변 쪽에서 구 이름을 쓸 수 있게 district도 담는다.
    return ResolvedQuery(
        search_query=request.question,
        status="needs_clarification",
        region_status="unsupported",
        district=district,
        dong=dong,
        clarification_question=(
            f"{district}는 아직 지원하지 않아요. "
            "서대문구·송파구의 동이나 구를 알려 주세요."
        ),
    )


def resolve_request(request: PipelineRequest) -> ResolvedQuery:
    """파이프라인 resolver 콜백. 질문 속 동과 사용자가 고른 구로 검색 지역을 정한다.

    resolve_region()의 팀 내부 4상태를 파이프라인 규격(ResolvedQuery)으로 옮긴다.
    - status: 파이프라인 분기용. resolved면 검색, needs_clarification이면
      clarification_question을 사용자에게 그대로 보내고 검색을 건너뛴다.
    - region_status: 왜 그렇게 판단했는지 (ok / ambiguous / unsupported / no_dong).

    해석 입력: 질문 속 동 → (없으면) 화면에서 받은 동(request.dong)
               → (그래도 없으면) 질문 속 구 이름 또는 화면에서 고른 구.
    검사 순서: ambiguous → unsupported → no_dong → 고른 구와 충돌 → ok.
    질문 다듬기는 다른 단계 담당이므로 search_query는 항상 원질문을 쓴다.
    """
    region = resolve_region(request.question)
    selected = request.district  # 사용자가 화면에서 고른 구 (없으면 None)

    # 질문에 동이 없으면 화면에서 따로 받은 동도 같은 규칙(매핑·지원 범위·충돌)으로
    # 해석한다. 검사 없이 복사하면 송파구/연희동처럼 맞지 않는 짝이 검색으로 넘어간다.
    if region["status"] == "no_dong" and request.dong:
        region = resolve_region(request.dong)

    # 신사동처럼 여러 구에 있는 동: 하나로 고르지 않고 후보 구를 보여 주며 되묻는다.
    if region["status"] == "ambiguous":
        return ResolvedQuery(
            search_query=request.question,
            status="needs_clarification",
            region_status="ambiguous",
            candidate_districts=region["candidate_districts"],
            clarification_question=(
                f"{region['dong']}은 "
                f"{', '.join(region['candidate_districts'])}에 있어요. "
                "어느 구인가요?"
            ),
        )

    # 역삼동(강남구)처럼 지원 범위 밖: 다른 구 자료로 대신 답하지 않도록
    # 검색 없이 안내한다.
    if region["status"] == "unsupported":
        return _ask_unsupported(request, region["district"], region["dong"])

    # 동을 끝내 확인하지 못한 경우: 질문 속 구 이름("송파구 페트병 언제?")이나
    # 화면에서 고른 구로 검색한다. 둘 다 없으면 지역을 되묻는다.
    # 동은 확인하지 못했으므로 추측해서 채우지 않는다 (dong=None).
    if region["status"] == "no_dong":
        named = find_district(request.question)

        # 질문 속 구와 고른 구가 다르면 어느 쪽으로도 덮어쓰지 않고 되묻는다.
        if named is not None and selected is not None and named != selected:
            return ResolvedQuery(
                search_query=request.question,
                status="needs_clarification",
                region_status="no_dong",
                clarification_question=(
                    f"{selected}를 선택하셨는데 질문에는 {named}가 있습니다. "
                    "어느 구 기준으로 알려 드릴까요?"
                ),
            )

        district = named or selected
        if district is None:
            return ResolvedQuery(
                search_query=request.question,
                status="needs_clarification",
                region_status="no_dong",
                clarification_question=(
                    "어느 지역 기준으로 알려 드릴까요? "
                    "서대문구·송파구의 동이나 구를 알려 주세요."
                ),
            )
        if district not in SUPPORTED_DISTRICTS:
            return _ask_unsupported(request, district, None)
        return ResolvedQuery(
            search_query=request.question,
            region_status="no_dong",
            district=district,
        )

    # 여기부터는 ok: 질문 속 동이 지원하는 구 하나로 정해진 경우.
    # 고른 구와 다르면 어느 쪽으로도 덮어쓰지 않고 되묻는다.
    # (파이프라인은 고른 구와 다른 구를 resolved로 받으면 오류를 낸다.)
    if selected is not None and selected != region["district"]:
        return ResolvedQuery(
            search_query=request.question,
            status="needs_clarification",
            region_status="ok",
            dong=region["dong"],
            # 사용자가 무엇을 골랐는지도 보여 줘야 어느 쪽인지 답할 수 있다.
            clarification_question=(
                f"{selected}를 선택하셨는데 "
                f"{region['dong']}은 {region['district']}입니다. "
                "어느 구 기준으로 알려 드릴까요?"
            ),
        )

    return ResolvedQuery(
        search_query=request.question,
        district=region["district"],
        dong=region["dong"],
        region_status="ok",
    )
