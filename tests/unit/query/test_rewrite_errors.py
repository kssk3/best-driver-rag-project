"""질문 정제 실패의 공통 코드와 기존 예외 호환성을 확인."""

from unittest.mock import Mock

import pytest

from src.common.errors import ErrorCategory, describe_error
from src.config import RuntimeSettings
from src.contracts import (
    GenerationResult,
    PipelineOptions,
    PipelineRequest,
    ResolvedQuery,
)
from src.query.errors import (
    RewriteCallError,
    RewriteConfigurationError,
    RewriteOutputError,
    RewriteOutputTypeError,
)
from src.query.prompt_runtime import create_prompt_rewrite_runtime
from src.query.rewrite import make_prompt_rewriter


@pytest.mark.parametrize(
    ("output", "exception", "error_type", "builtin", "code", "category", "message"),
    [
        (
            None,
            TimeoutError("비공개 모델 요청"),
            RewriteCallError,
            RuntimeError,
            "query.rewrite_call_failed",
            ErrorCategory.EXTERNAL_SERVICE,
            "질문 다듬기 호출 실패 (TimeoutError)",
        ),
        (
            None,
            None,
            RewriteOutputTypeError,
            TypeError,
            "query.rewrite_invalid_type",
            ErrorCategory.CONTRACT_VIOLATION,
            "질문 다듬기 출력은 문자열이어야 합니다.",
        ),
        (
            "  ",
            None,
            RewriteOutputError,
            ValueError,
            "query.rewrite_invalid_format",
            ErrorCategory.CONTRACT_VIOLATION,
            "질문 다듬기 출력은 비어 있지 않은 한 줄이어야 합니다.",
        ),
        (
            "첫 줄\n둘째 줄",
            None,
            RewriteOutputError,
            ValueError,
            "query.rewrite_invalid_format",
            ErrorCategory.CONTRACT_VIOLATION,
            "질문 다듬기 출력은 비어 있지 않은 한 줄이어야 합니다.",
        ),
        (
            "전혀 다른 질문",
            None,
            RewriteOutputError,
            ValueError,
            "query.rewrite_rule_violation",
            ErrorCategory.CONTRACT_VIOLATION,
            "질문 다듬기 출력이 원질문과 등록 별칭 규칙을 벗어났습니다.",
        ),
    ],
)
def test_rewrite_failure_has_common_code_and_keeps_message(
    output, exception, error_type, builtin, code, category, message
):
    invoke = Mock(return_value=output, side_effect=exception)
    rewrite = make_prompt_rewriter(invoke)

    with pytest.raises(error_type) as caught:
        rewrite(ResolvedQuery(search_query="서대문구 우유팩 버리는 법"))

    error = caught.value
    assert isinstance(error, builtin)
    assert str(error) == message
    info = describe_error(error)
    assert info.code == code
    assert info.category is category
    assert "비공개 모델 요청" not in info.detail
    assert "전혀 다른 질문" not in info.detail
    assert message not in info.user_message
    assert RewriteOutputError.code == "query.rewrite_invalid_format"


def test_missing_invoke_fails_before_pipeline_creation():
    resolver, retriever, generator = Mock(), Mock(), Mock()
    settings = RuntimeSettings(pipeline=PipelineOptions(rewrite_enabled=True))

    with pytest.raises(RewriteConfigurationError) as caught:
        create_prompt_rewrite_runtime(
            settings, resolver=resolver, retriever=retriever, generator=generator
        )

    assert isinstance(caught.value, ValueError)
    assert str(caught.value) == "P09를 켜려면 질문 다듬기 모델 호출을 지정해야 합니다."
    info = describe_error(caught.value)
    assert info.code == "query.rewrite_not_configured"
    assert info.category is ErrorCategory.CONFIGURATION
    resolver.assert_not_called()
    retriever.assert_not_called()
    generator.assert_not_called()


def test_common_error_falls_back_to_resolved_query(tmp_path):
    resolved_text = "서대문구 우유팩 버리는 법"
    resolver = Mock(
        return_value=ResolvedQuery(search_query=resolved_text, district="서대문구")
    )
    retriever = Mock(return_value=[])
    generator = Mock(
        return_value=GenerationResult(
            status="insufficient_evidence", answer="합성 검사"
        )
    )
    runtime = create_prompt_rewrite_runtime(
        RuntimeSettings(
            runs_path=tmp_path, pipeline=PipelineOptions(rewrite_enabled=True)
        ),
        resolver=resolver,
        retriever=retriever,
        generator=generator,
        invoke=Mock(side_effect=TimeoutError("비공개 모델 요청")),
    )

    record = runtime.run(PipelineRequest(question="우유팩 버리는 법"))

    assert record.search_query == resolved_text
    assert retriever.call_args.args[0].search_query == resolved_text
    stage = next(stage for stage in record.stages if stage.name == "rewrite")
    assert stage.status == "error"
    assert "RewriteCallError" in stage.error
    assert "비공개 모델 요청" not in stage.error
    assert record.response.status == "insufficient_evidence"
