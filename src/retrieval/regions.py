"""구와 동 이름 해석.

담당: 이명지
상태: 서울 행정동·법정동 매핑표(data/reference/seoul_dong_map.csv)로
질문 속 동 이름을 자치구로 해석한다. 매핑표의 출처·기준일은 data/reference/README.md.
"""

import csv
import re
from pathlib import Path

from src.contracts import PipelineRequest, ResolvedQuery

# 프로젝트 루트 기준 경로. regions.py → retrieval/ → src/ → 루트
DONG_MAP_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "reference" / "seoul_dong_map.csv"
)


def load_dong_map(path: Path) -> dict[str, list[str]]:
    """매핑표 CSV를 읽어 '동 이름 → 그 동이 있는 구 목록'을 만든다.

    사람들은 행정동(잠실본동)과 법정동(잠실동)을 섞어 쓰므로 두 이름을 모두 키로 넣는다.
    같은 이름이 여러 구에 있으면(신사동: 강남구·관악구·은평구) 구 목록이 여러 개가 된다.
    공식 행정동 이름의 "제N동"(홍제제1동)은 사람들이 "N동"(홍제1동)으로 쓰는 경향이 있으므로
    "제"를 뺀 이름도 같은 구로 추가한다. 원래 이름도 그대로 남겨 둘 다 찾는다.
    구 목록은 정렬해서 실행할 때마다 순서가 같게 한다.
    """
    dong_to_districts: dict[str, set[str]] = {}
    with path.open(encoding="utf-8", newline="") as file:
        for row in csv.DictReader(file):
            for name in (row["admin_dong"], row["legal_dong"]):
                dong_to_districts.setdefault(name, set()).add(row["district"])
                # "제" 뒤에 숫자가 올 때만 뺀다. 제기동 같은 이름은 바뀌지 않는다.
                short_name = re.sub(r"제(\d)", r"\1", name)
                if short_name != name:
                    dong_to_districts.setdefault(short_name, set()).add(row["district"])
    return {name: sorted(districts) for name, districts in dong_to_districts.items()}


# 동 이름 → 그 동이 있는 구 목록 (서울 행정동·법정동 전체)
DONG_TO_DISTRICTS: dict[str, list[str]] = load_dong_map(DONG_MAP_PATH)

# find_dong이 확인할 순서: 긴 이름 먼저 (질문마다 정렬하지 않도록 한 번만 만든다).
# 길이가 같으면 이름순으로 정해 실행할 때마다 순서가 같게 한다.
DONG_NAMES_LONGEST_FIRST: list[str] = sorted(
    # 길이를 -len 음수로 바꿔서 긴 것 이앞으로(내림차순)
    # 길이가 같으면 이름 가나다순
    DONG_TO_DISTRICTS,
    key=lambda name: (-len(name), name),
)

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

    긴 이름부터 확인한다. 짧은 동 이름이 긴 동 이름 안에 들어 있는 경우가 있어서
    ("본동"(동작구) ⊂ "잠실본동"(송파구)) 짧은 이름을 먼저 보면 엉뚱한 구로 해석된다.

    Returns:
        찾은 동 이름. 질문에 매핑표의 동이 없으면 None.
    """
    for dong in DONG_NAMES_LONGEST_FIRST:
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


def _confirmed_selected_district(request: PipelineRequest) -> bool:
    """사용자가 되묻기에 답해 고른 구(request.district)로 확정했는가.

    파이프라인은 해석된 구가 요청의 구와 다르면 오류를 내므로 확정한 구는 요청의 구와 같다.
    지원하지 않는 구는 확정으로 인정하지 않는다.
    """
    return request.district_confirmed and request.district in SUPPORTED_DISTRICTS


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
    되묻기를 받은 사용자가 고른 구를 확정하면(request.district_confirmed) 같은 되묻기를 되풀이하지 않는다.
    - 질문 속 구·동이 고른 구와 충돌: 고른 구로 해석한다. 맞지 않는 동은 버리고 구만 쓴다.
      동은 채택하지 않으므로 no_dong 분기와 같게 dong=None으로 구만 쓰고 region_status는 no_dong이다.
      확정했다는 사실은 요청의 district_confirmed에 남는다.
    - 여러 구에 있는 동(ambiguous): 질문에 후보 구 중 하나가 적혀 있으면 그 구로 모호함이 풀린 것으로 본다.
      확정한 구가 후보 구에 있으면 그 구와 그 동으로 해석한다.
      되묻기에서 지원 밖 후보 구를 고르면 같은 되묻기를 되풀이하지 않고 지원 밖(unsupported)으로 안내한다.
    - 지원하지 않는 구가 질문에 있으면(동과 함께 적혀도) 또는 동이 지원 밖이면 확정으로 덮지 않고 안내한다.
    - 후속 요청에서 구와 동을 함께 확정했고 그 동이 그 구에 있으면 원질문의 동보다 그 조합을 먼저 쓴다.
    - 화면에서 받은 동(request.dong)이 있으면 확정으로 버릴 수 없다. 파이프라인이 생성 요청을 만들 때
      resolved.dong이 없으면 request.dong을 되돌려 넣기 때문이다.
    질문 다듬기는 다른 단계 담당이므로 search_query는 항상 원질문을 쓴다.
    """
    region = resolve_region(request.question)
    selected = request.district  # 사용자가 화면에서 고른 구 (없으면 None)
    confirmed = _confirmed_selected_district(request)

    if confirmed:
        # 지원하지 않는 구가 질문에 있으면 동이 함께 있어도 확정으로 덮지 않고 안내한다.
        named_in_question = find_district(request.question)
        if named_in_question and named_in_question not in SUPPORTED_DISTRICTS:
            return _ask_unsupported(request, named_in_question, None)
        # 사용자가 후속 요청에서 구와 동을 함께 확정했고 서로 맞으면 그 조합이 원질문의 동보다 먼저다.
        if request.dong:
            fixed = resolve_region(request.dong)
            if fixed["status"] == "ok" and fixed["district"] == selected:
                return ResolvedQuery(
                    search_query=request.question,
                    region_status="ok",
                    district=selected,
                    dong=fixed["dong"],
                )

    # 질문에 동이 없으면 화면에서 따로 받은 동도 같은 규칙(매핑·지원 범위·충돌)으로
    # 해석한다. 검사 없이 복사하면 송파구/연희동처럼 맞지 않는 짝이 검색으로 넘어간다.
    if region["status"] == "no_dong" and request.dong:
        region = resolve_region(request.dong)

    # 질문에 후보 구 중 하나가 적혀 있으면("강남구 삼성동") 모호함이 풀린 것이다. 되묻지 않고 그 구로
    # 해석해 아래 ok·지원 밖 판정을 그대로 따른다. 후보에 없는 구는 모호함을 풀지 못한다.
    if region["status"] == "ambiguous":
        written = find_district(request.question)
        if written in region["candidate_districts"]:
            region = {
                "status": "ok" if written in SUPPORTED_DISTRICTS else "unsupported",
                "district": written,
                "dong": region["dong"],
            }

    # 신사동처럼 여러 구에 있는 동: 하나로 고르지 않고 후보 구를 보여 주며 되묻는다.
    if region["status"] == "ambiguous":
        # 되묻기에서 지원 밖 후보 구를 골랐다. 지원 밖 구는 확정으로 인정하지 않으므로 이 안내가
        # 없으면 같은 되묻기가 끝없이 반복된다. 다른 구 자료로 답하지 않고 지원 밖으로 안내한다.
        picked = request.district
        if (
            request.district_confirmed
            and picked is not None
            and picked in region["candidate_districts"]
            and picked not in SUPPORTED_DISTRICTS
        ):
            return _ask_unsupported(request, picked, region["dong"])
        # 사용자가 되묻기에 후보 구 하나를 골라 확정했다. 그 구에 있는 그 동으로 해석한다.
        if confirmed and selected in region["candidate_districts"]:
            return ResolvedQuery(
                search_query=request.question,
                region_status="ok",
                district=selected,
                dong=region["dong"],
            )
        # 후보 구가 모두 지원 밖이면(신사동: 강남구·관악구·은평구) 되묻지 않고 바로 안내한다.
        # 되물어도 서대문구·송파구는 후보에 없어 같은 되묻기만 끝없이 반복된다.
        if region["status"] == "ambiguous" and not (
            set(region["candidate_districts"]) & SUPPORTED_DISTRICTS
        ):
            return ResolvedQuery(
                search_query=request.question,
                status="needs_clarification",
                region_status="unsupported",
                dong=region["dong"],
                clarification_question=(
                    f"{region['dong']}은 {', '.join(region['candidate_districts'])}에 있어요. "
                    "모두 아직 지원하지 않아요. 서대문구·송파구의 동이나 구를 알려 주세요."
                ),
            )

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

        # 질문 속 구가 지원 밖이면 되묻지 않고 바로 안내한다. 되물어도 어느 구를 고르든
        # 아래 확정 경로가 같은 안내로 거절하므로, 고를 수 있는 선택지가 없는 질문이 된다.
        if named is not None and named not in SUPPORTED_DISTRICTS:
            return _ask_unsupported(request, named, None)

        # 질문 속 구와 고른 구가 다르면 어느 쪽으로도 덮어쓰지 않고 되묻는다.
        if (
            named is not None
            and selected is not None
            and named != selected
            and not confirmed
        ):
            return ResolvedQuery(
                search_query=request.question,
                status="needs_clarification",
                region_status="no_dong",
                clarification_question=(
                    f"{selected}를 선택하셨는데 질문에는 {named}가 있습니다. "
                    "어느 구 기준으로 알려 드릴까요?"
                ),
            )

        district = selected if confirmed else named or selected
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
        # 화면에서 받은 동(request.dong)은 버릴 수 없으므로(파이프라인이 되돌려 넣는다) 확정으로 덮지 않는다.
        if confirmed and request.dong is None:
            # 사용자가 충돌을 알고 고른 구로 확정했다. 맞지 않는 동은 채택하지 않고(dong=None) 구만 쓴다.
            # no_dong 분기와 같은 모양이다("동은 확인하지 못했으므로 채우지 않는다").
            return ResolvedQuery(
                search_query=request.question,
                region_status="no_dong",
                district=selected,
            )
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
