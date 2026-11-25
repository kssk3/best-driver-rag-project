"""P09 프롬프트 전달과 검색 질의 복귀를 합성 모델로 확인."""

import json
from unittest.mock import Mock

import pytest

from src.config import RuntimeSettings
from src.contracts import GenerationResult, PipelineOptions, PipelineRequest
from src.query.aliases import ITEM_ALIASES
from src.query.prompt_runtime import create_prompt_rewrite_runtime
from src.query.rewrite import QUERY_REWRITE_PROMPT_VERSION, normalize_question
from src.retrieval.regions import resolve_request

T01_QUESTION = (
    "서대문구 아파트 일반용기 색이 정해져 있으면 우리 동네 수거함도 모두 그 색인 거죠?"
)
T02_QUESTION = (
    "다른 구에서 10L 봉투를 사업장생활계폐기물용으로도 쓰던데, "
    "송파구 10L도 용도가 같죠?"
)
T03_QUESTION = (
    "단독주택이니까 우유팩이랑 소주팩은 종이류랑 같이 묶어서 내놓으면 되는 거죠? "
    "따로 모을 필요는 없잖아요."
)


@pytest.fixture
def make_runtime(tmp_path):
    def build(invoke=None, *, rewrite_enabled=True):
        retriever = Mock(return_value=[])
        generator = Mock(
            return_value=GenerationResult(
                status="insufficient_evidence",
                answer="합성 검사",
            )
        )
        settings = RuntimeSettings(
            runs_path=tmp_path,
            pipeline=PipelineOptions(
                rewrite_enabled=rewrite_enabled,
                versions={"data": "synthetic-v1"},
            ),
        )
        runtime = create_prompt_rewrite_runtime(
            settings,
            resolver=resolve_request,
            retriever=retriever,
            generator=generator,
            invoke=invoke,
        )
        assert settings.pipeline.versions == {"data": "synthetic-v1"}
        return runtime, retriever, generator

    return build


@pytest.mark.parametrize(
    ("question", "resolved_district", "selected_district", "expected_query"),
    [
        pytest.param(T01_QUESTION, "서대문구", None, T01_QUESTION, id="T01"),
        pytest.param(T02_QUESTION, "송파구", None, T02_QUESTION, id="T02"),
        pytest.param(
            T03_QUESTION,
            "서대문구",
            "서대문구",
            f"{T03_QUESTION} (종이팩)",
            id="T03",
        ),
    ],
)
def test_prompt_rewrite_passes_search_query_and_preserves_request(
    make_runtime,
    tmp_path,
    question,
    resolved_district,
    selected_district,
    expected_query,
):
    invoke = Mock(return_value=f" {expected_query}\n")
    runtime, retriever, generator = make_runtime(invoke)
    request = PipelineRequest(question=question, district=selected_district)

    record = runtime.run(request)

    invoke.assert_called_once()
    prompt, data = invoke.call_args.args
    assert QUERY_REWRITE_PROMPT_VERSION in prompt.splitlines()[0]
    assert question not in prompt
    assert json.loads(data) == {
        "question": question,
        "district": resolved_district,
        "dong": None,
        "item_aliases": ITEM_ALIASES,
    }
    assert record.request == request
    assert record.options.versions == {
        "data": "synthetic-v1",
        "rewrite": QUERY_REWRITE_PROMPT_VERSION,
    }
    assert normalize_question(question) == expected_query
    assert record.search_query == expected_query
    assert retriever.call_args.args[0].search_query == expected_query
    assert retriever.call_args.args[0].district == resolved_district
    generated_request, _ = generator.call_args.args
    assert generated_request.question == question
    assert generated_request.district == resolved_district
    saved = json.loads((tmp_path / f"{record.run_id}.json").read_text(encoding="utf-8"))
    assert saved["options"]["versions"]["rewrite"] == QUERY_REWRITE_PROMPT_VERSION


def test_missing_district_asks_before_prompt_rewrite(make_runtime):
    invoke = Mock()
    runtime, retriever, generator = make_runtime(invoke)

    record = runtime.run(PipelineRequest(question=T03_QUESTION))

    assert record.response.status == "needs_clarification"
    invoke.assert_not_called()
    retriever.assert_not_called()
    generator.assert_not_called()


def test_prompt_rewrite_off_uses_original_without_model_or_version(make_runtime):
    runtime, retriever, _ = make_runtime(rewrite_enabled=False)
    request = PipelineRequest(question=T01_QUESTION)

    record = runtime.run(request)

    assert record.search_query == request.question
    assert retriever.call_args.args[0].search_query == request.question
    assert record.options.versions == {"data": "synthetic-v1"}
    assert (
        next(stage for stage in record.stages if stage.name == "rewrite").status
        == "skipped"
    )


def test_prompt_rewrite_can_flatten_line_breaks(make_runtime):
    question = "서대문구에서 우유팩은\r\n어떻게 버려요?"
    query = "서대문구에서 우유팩은 어떻게 버려요? (종이팩)"
    runtime, retriever, _ = make_runtime(Mock(return_value=query))

    record = runtime.run(PipelineRequest(question=question))

    assert record.request.question == question
    assert retriever.call_args.args[0].search_query == query


@pytest.mark.parametrize(
    ("question", "district", "output"),
    [
        pytest.param(
            T02_QUESTION,
            "송파구",
            T02_QUESTION.replace("송파구", "서대문구"),
            id="target-district",
        ),
        pytest.param(
            T02_QUESTION,
            "송파구",
            T02_QUESTION.removeprefix("다른 구에서 "),
            id="comparison",
        ),
        pytest.param(
            T03_QUESTION,
            "서대문구",
            f"{T03_QUESTION.replace('단독주택이니까', '서대문구에서')} (종이팩)",
            id="housing-condition",
        ),
        pytest.param(
            T03_QUESTION,
            "서대문구",
            T03_QUESTION.replace("모을 필요는 없잖아요", "모아야 하잖아요")
            + " (종이팩)",
            id="negation",
        ),
        pytest.param(
            T03_QUESTION,
            "서대문구",
            f"{T03_QUESTION} (종이팩) (종이팩)",
            id="duplicate-alias",
        ),
    ],
)
def test_prompt_rewrite_rejects_changes_outside_v1_rules(
    make_runtime,
    question,
    district,
    output,
):
    runtime, retriever, _ = make_runtime(Mock(return_value=output))

    record = runtime.run(PipelineRequest(question=question, district=district))

    assert record.search_query == question
    assert retriever.call_args.args[0].search_query == question
    stage = next(stage for stage in record.stages if stage.name == "rewrite")
    assert stage.status == "error"
    assert "등록 별칭 규칙" in stage.error
    assert output not in stage.error


@pytest.mark.parametrize(
    ("question", "output", "expected_query"),
    [
        pytest.param(
            "서대문구 우유팩  버리는 법",
            "서대문구 우유팩 버리는 법 (종이팩)",
            "서대문구 우유팩 버리는 법 (종이팩)",
            id="collapsed-spaces",
        ),
        pytest.param(
            "서대문구 우유팩",
            "서대문구 우유팩(종이팩)",
            "서대문구 우유팩 (종이팩)",
            id="no-space-before-alias",
        ),
        pytest.param(
            "서대문구 우유팩",
            "서대문구\u00a0우유팩 \t(종이팩)",
            "서대문구 우유팩 (종이팩)",
            id="space-kind",
        ),
    ],
)
def test_prompt_rewrite_accepts_spacing_and_returns_canonical_query(
    make_runtime, question, output, expected_query
):
    runtime, retriever, _ = make_runtime(Mock(return_value=output))

    record = runtime.run(PipelineRequest(question=question))

    stage = next(stage for stage in record.stages if stage.name == "rewrite")
    assert stage.status == "ok"
    assert record.request.question == question
    assert record.search_query == expected_query
    assert retriever.call_args.args[0].search_query == expected_query


@pytest.mark.parametrize(
    ("question", "output"),
    [
        pytest.param(
            "서대문구 우유팩 버리는 법",
            "서대문구 우유 팩 버리는 법 (종이팩)",
            id="space-inside-word",
        ),
        pytest.param(
            "서대문구 우유팩 버리는 법",
            "서대문구 우유팩버리는 법 (종이팩)",
            id="words-joined",
        ),
        pytest.param(
            "서대문구 공동주택 (아파트) 우유팩 버리는 법",
            "서대문구 공동주택(아파트) 우유팩 버리는 법 (종이팩)",
            id="parenthesis-in-original-question",
        ),
    ],
)
def test_prompt_rewrite_rejects_word_boundary_change(make_runtime, question, output):
    runtime, retriever, _ = make_runtime(Mock(return_value=output))

    record = runtime.run(PipelineRequest(question=question))

    stage = next(stage for stage in record.stages if stage.name == "rewrite")
    assert stage.status == "error"
    assert record.search_query == question
    assert retriever.call_args.args[0].search_query == question


@pytest.mark.parametrize(
    "invoke",
    [
        pytest.param(Mock(return_value=" \n "), id="blank"),
        pytest.param(Mock(return_value="첫 줄\n둘째 줄"), id="multiple-lines"),
        pytest.param(Mock(return_value=None), id="non-text"),
        pytest.param(Mock(side_effect=TimeoutError("모델 요청 내용")), id="timeout"),
    ],
)
def test_prompt_rewrite_failure_returns_original_search_query(make_runtime, invoke):
    runtime, retriever, _ = make_runtime(invoke)
    request = PipelineRequest(question=T01_QUESTION)

    record = runtime.run(request)

    assert record.request == request
    assert record.search_query == request.question
    assert retriever.call_args.args[0].search_query == request.question
    stage = next(stage for stage in record.stages if stage.name == "rewrite")
    assert stage.status == "error"
    assert record.warnings
    assert "모델 요청 내용" not in stage.error
