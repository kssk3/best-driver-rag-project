from src.contracts import PipelineRequest
from src.retrieval.regions import DONG_TO_DISTRICTS, resolve_region, resolve_request

# ---------------------------------------------------------------------------
# resolve_region(): 질문 문자열 → dict (팀 내부 4상태)
# ---------------------------------------------------------------------------


def test_resolve_region_returns_district_for_supported_dong():
    # 연희동(서대문구) → ok. 지원하는 구이므로 구와 동을 함께 돌려준다.
    result = resolve_region("연희동 페트병 언제 버려요?")
    assert result == {"status": "ok", "district": "서대문구", "dong": "연희동"}


def test_resolve_region_returns_district_for_songpa_dong():
    # 잠실동(송파구) → ok. 지원하는 두 번째 구도 같은 규칙으로 처리되는지 확인.
    result = resolve_region("잠실동 폐건전지 언제 버려요?")
    assert result == {"status": "ok", "district": "송파구", "dong": "잠실동"}


def test_resolve_region_prefers_longer_dong_name():
    # 잠실본동(송파구 행정동) 안에 본동(동작구)이 들어 있다.
    # 짧은 이름을 먼저 보면 동작구 → unsupported로 잘못 해석된다.
    result = resolve_region("잠실본동 페트병 언제?")
    assert result == {"status": "ok", "district": "송파구", "dong": "잠실본동"}


def test_resolve_region_uses_administrative_dong_name():
    # 천연동은 서대문구 행정동이자 법정동. 행정동 이름으로도 구를 찾는다.
    result = resolve_region("천연동 종이팩 버리는 법")
    assert result == {"status": "ok", "district": "서대문구", "dong": "천연동"}


def test_resolve_region_accepts_dong_name_with_or_without_je():
    # 공식 이름은 홍제제1동이지만 사람들은 홍제1동이라고 쓴다. 둘 다 서대문구.
    official = resolve_region("홍제제1동 스티로폼 버리는 법")
    common = resolve_region("홍제1동 스티로폼 버리는 법")
    assert official == {"status": "ok", "district": "서대문구", "dong": "홍제제1동"}
    assert common == {"status": "ok", "district": "서대문구", "dong": "홍제1동"}


def test_resolve_region_keeps_je_when_not_followed_by_number():
    # 제기동(동대문구)의 "제"는 숫자 앞이 아니라 그대로 둔다 → "기동"으로 바뀌지 않는다.
    result = resolve_region("제기동 페트병")
    assert result == {"status": "unsupported", "district": "동대문구", "dong": "제기동"}


def test_resolve_region_does_not_guess_shared_dong_name():
    # 신사동: 행정동(강남구·관악구) + 법정동(강남구·은평구) → ambiguous.
    # 첫 번째 구로 임의 확정하지 않는다.
    result = resolve_region("신사동 쓰레기 언제?")
    assert result["status"] == "ambiguous"
    assert result["candidate_districts"] == ["강남구", "관악구", "은평구"]


def test_resolve_region_marks_unsupported_district():
    # 역삼동(강남구) → unsupported. 다른 구 자료로 대신 답하지 않도록 표시한다.
    result = resolve_region("역삼동 쓰레기 언제?")
    assert result == {"status": "unsupported", "district": "강남구", "dong": "역삼동"}


def test_resolve_region_returns_no_dong_when_question_has_no_dong():
    # 동 이름 없음 → no_dong. 구·동 정보 없이 상태만 돌려준다.
    assert resolve_region("페트병 언제 버려요?") == {"status": "no_dong"}


# ---------------------------------------------------------------------------
# resolve_request(): PipelineRequest → ResolvedQuery (파이프라인 resolver 규격)
#   status        : resolved(검색 진행) / needs_clarification(사용자에게 되묻기)
#   region_status : 팀 내부 4상태 (ok / ambiguous / unsupported / no_dong)
# ---------------------------------------------------------------------------


def test_resolve_request_returns_resolved_query_for_supported_dong():
    # 연희동, 고른 구 없음 → resolved + ok. 서대문구로 바로 검색한다.
    request = PipelineRequest(question="연희동 페트병 언제 버려요?")
    result = resolve_request(request)

    assert result.status == "resolved"
    assert result.region_status == "ok"
    assert result.district == "서대문구"


def test_resolve_request_asks_which_district_for_shared_dong():
    # 신사동 → needs_clarification + ambiguous. 후보 구를 넣어 되묻는다.
    result = resolve_request(PipelineRequest(question="신사동 쓰레기 언제?"))

    assert result.status == "needs_clarification"
    assert result.region_status == "ambiguous"
    assert "강남구" in result.clarification_question


def test_resolve_request_tells_unsupported_district():
    # 역삼동 → needs_clarification + unsupported. 강남구는 지원하지 않는다고 안내.
    # (팀 임시 결정: 검색하지 않고 되묻기로 안내. 강성수님과 최종 합의 전)
    result = resolve_request(PipelineRequest(question="역삼동 쓰레기 언제?"))

    assert result.status == "needs_clarification"
    assert result.region_status == "unsupported"
    assert "강남구" in result.clarification_question


def test_resolve_request_asks_region_when_no_dong_and_no_selection():
    # 동 없음 + 고른 구 없음 → needs_clarification + no_dong. 지역을 되묻는다.
    # 파이프라인은 되묻기 문장이 비어 있으면 오류를 내므로 문장이 있어야 한다.
    result = resolve_request(PipelineRequest(question="페트병 언제 버려요?"))

    assert result.status == "needs_clarification"
    assert result.region_status == "no_dong"
    assert result.clarification_question


def test_resolve_request_uses_selected_district_when_no_dong():
    # 동 없음 + 고른 구 서대문구 → resolved + no_dong. 고른 구로 검색한다.
    # 동은 확인하지 못했으므로 dong은 None으로 둔다 (임의로 채우지 않음).
    request = PipelineRequest(question="페트병 언제 버려요?", district="서대문구")
    result = resolve_request(request)

    assert result.status == "resolved"
    assert result.region_status == "no_dong"
    assert result.district == "서대문구"
    assert result.dong is None


def test_resolve_request_does_not_override_selected_district():
    # 고른 구 송파구 + 질문 속 연희동(서대문구) → 충돌. 어느 쪽으로도 확정하지 않는다.
    # 파이프라인은 고른 구와 다른 구를 resolved로 받으면 오류를 내므로 되묻는다.
    # region_status 값(conflict 추가 여부)은 팀 결정 전이라 확인하지 않는다.
    request = PipelineRequest(question="연희동 페트병 언제 버려요?", district="송파구")
    result = resolve_request(request)

    assert result.status == "needs_clarification"
    assert "송파구" in result.clarification_question
    assert "서대문구" in result.clarification_question


# ---------------------------------------------------------------------------
# PR 리뷰 반영: 질문 속 구 이름, 화면에서 따로 받은 동(request.dong)
# ---------------------------------------------------------------------------


def test_resolve_request_uses_district_named_in_question():
    # "송파구 페트병" → resolved, 송파구. 구를 이미 말했으니 다시 묻지 않는다.
    result = resolve_request(PipelineRequest(question="송파구 페트병 언제 버려요?"))

    assert result.status == "resolved"
    assert result.region_status == "no_dong"
    assert result.district == "송파구"
    assert result.dong is None


def test_resolve_request_tells_unsupported_district_named_in_question():
    # "강남구 페트병" → 지원 범위 밖. 다른 구 자료로 답하지 않고 안내한다.
    result = resolve_request(PipelineRequest(question="강남구 페트병 언제 버려요?"))

    assert result.status == "needs_clarification"
    assert result.region_status == "unsupported"
    assert "강남구" in result.clarification_question


def test_resolve_request_asks_when_named_district_differs_from_selected():
    # 질문은 송파구, 화면은 서대문구 → 충돌. 어느 쪽으로도 확정하지 않는다.
    request = PipelineRequest(
        question="송파구 페트병 언제 버려요?", district="서대문구"
    )
    result = resolve_request(request)

    assert result.status == "needs_clarification"
    assert "송파구" in result.clarification_question
    assert "서대문구" in result.clarification_question


def test_resolve_request_resolves_structured_dong_input():
    # 질문에 동이 없어도 화면에서 받은 동(연희동)을 매핑표로 해석한다.
    request = PipelineRequest(question="페트병 언제 버려요?", dong="연희동")
    result = resolve_request(request)

    assert result.status == "resolved"
    assert result.region_status == "ok"
    assert result.district == "서대문구"
    assert result.dong == "연희동"


def test_resolve_request_checks_structured_dong_against_selected_district():
    # 화면에서 송파구 + 연희동(서대문구) → 맞지 않는 짝. 검색하지 않고 되묻는다.
    request = PipelineRequest(
        question="페트병 언제 버려요?", district="송파구", dong="연희동"
    )
    result = resolve_request(request)

    assert result.status == "needs_clarification"
    assert "송파구" in result.clarification_question
    assert "서대문구" in result.clarification_question


# ---------------------------------------------------------------------------
# 되묻기에서 고른 구를 확정하면(district_confirmed) 같은 되묻기를 되풀이하지 않는다
# ---------------------------------------------------------------------------


def test_resolve_request_uses_selected_district_when_user_confirms_it_over_named_district():
    # 질문은 송파구, 화면은 서대문구인데 사용자가 서대문구를 확정했다.
    request = PipelineRequest(
        question="송파구 페트병 언제 버려요?",
        district="서대문구",
        district_confirmed=True,
    )
    result = resolve_request(request)

    assert result.status == "resolved"
    assert result.region_status == "no_dong"
    assert result.district == "서대문구"
    assert result.dong is None


def test_resolve_request_drops_conflicting_question_dong_when_user_confirms_selected_district():
    # 질문 속 연희동(서대문구)과 고른 송파구가 충돌, 사용자가 송파구를 확정했다.
    # 맞지 않는 동은 버리고 구만 쓴다. region_status의 no_dong은 "동으로 지역을 정하지 못했다"는 뜻이다.
    request = PipelineRequest(
        question="연희동 페트병 언제 버려요?",
        district="송파구",
        district_confirmed=True,
    )
    result = resolve_request(request)

    assert result.status == "resolved"
    assert result.region_status == "no_dong"
    assert result.district == "송파구"
    assert result.dong is None


def test_resolve_request_ignores_confirmation_without_the_flag():
    # conditions에 구를 넣는 것만으로는 확정이 아니다(생성기에 넘기는 일반 조건과 같은 모양이기 때문).
    request = PipelineRequest(
        question="송파구 페트병 언제 버려요?",
        district="서대문구",
        conditions={"district": "서대문구"},
    )
    result = resolve_request(request)

    assert result.status == "needs_clarification"
    assert "송파구" in result.clarification_question
    assert "서대문구" in result.clarification_question


def test_resolve_request_does_not_confirm_without_a_selected_or_with_an_unsupported_district():
    no_district = resolve_request(
        PipelineRequest(question="송파구 페트병 언제 버려요?", district_confirmed=True)
    )
    unsupported = resolve_request(
        PipelineRequest(
            question="송파구 페트병 언제 버려요?",
            district="강남구",
            district_confirmed=True,
        )
    )

    assert (
        no_district.district == "송파구"
    )  # 확정할 구가 없으면 질문 속 구를 그대로 쓴다
    assert unsupported.status == "needs_clarification"


def test_resolve_request_keeps_asking_when_confirmation_would_drop_the_callers_dong():
    # 화면에서 받은 동(request.dong)은 파이프라인이 생성 요청에 되돌려 넣으므로 버릴 수 없다.
    # 확정으로 덮으면 검색은 송파구, 생성기는 연희동을 받는 모순이 생긴다.
    request = PipelineRequest(
        question="페트병 언제 버려요?",
        district="송파구",
        dong="연희동",
        district_confirmed=True,
    )
    result = resolve_request(request)

    assert result.status == "needs_clarification"
    assert "송파구" in result.clarification_question
    assert "서대문구" in result.clarification_question


def test_resolve_request_does_not_let_confirmation_cover_unsupported_district_or_dong():
    # 질문에 지원 밖의 구가 있으면(동 없이) 확정해도 서대문구 근거로 답하지 않고 안내한다.
    named = resolve_request(
        PipelineRequest(
            question="강남구 쓰레기 언제?", district="서대문구", district_confirmed=True
        )
    )
    # 지원 밖의 동(역삼동 → 강남구)도 마찬가지다.
    dong = resolve_request(
        PipelineRequest(
            question="역삼동 쓰레기 언제?", district="서대문구", district_confirmed=True
        )
    )

    assert named.region_status == "unsupported"
    assert "강남구" in named.clarification_question
    assert dong.region_status == "unsupported"


def test_resolve_request_resolves_shared_dong_when_confirmed_district_is_a_candidate(
    monkeypatch,
):
    # 여러 구에 있는 동(ambiguous)을 되묻고 사용자가 후보 구를 확정하면 그 구와 그 동으로 해석한다.
    monkeypatch.setitem(DONG_TO_DISTRICTS, "공통동", ["서대문구", "송파구"])
    question = "공통동 쓰레기 언제?"

    asked = resolve_request(PipelineRequest(question=question))
    resolved = resolve_request(
        PipelineRequest(question=question, district="송파구", district_confirmed=True)
    )
    not_candidate = resolve_request(
        PipelineRequest(question=question, district="강남구", district_confirmed=True)
    )

    assert asked.region_status == "ambiguous"
    assert resolved.status == "resolved"
    assert (resolved.district, resolved.dong, resolved.region_status) == (
        "송파구",
        "공통동",
        "ok",
    )
    assert (
        not_candidate.region_status == "ambiguous"
    )  # 후보에 없는 구는 확정으로 인정하지 않는다
