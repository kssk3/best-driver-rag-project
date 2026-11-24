from src.contracts import PipelineRequest
from src.retrieval.regions import resolve_region, resolve_request

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


def test_resolve_region_does_not_guess_shared_dong_name():
    # 신사동(강남구·관악구) → ambiguous. 첫 번째 구로 임의 확정하지 않는다.
    result = resolve_region("신사동 쓰레기 언제?")
    assert result["status"] == "ambiguous"
    assert result["candidate_districts"] == ["강남구", "관악구"]


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
    request = PipelineRequest(question="송파구 페트병 언제 버려요?", district="서대문구")
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
