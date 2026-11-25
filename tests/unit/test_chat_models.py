"""공용 채팅 모델 생성과 호출 오류 분류의 동작 규격을 확인한다. 외부 호출은 하지 않는다."""

import httpx
import openai
import pytest
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from src.common.errors import ApplicationError, ErrorCategory
from src.infrastructure.chat_models import (
    ChatModelSettings,
    create_chat_model,
    invoke_chat,
)

_REQUEST = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
# 실제 키가 아닌 합성 값. 프로젝트 키(sk-proj-…)처럼 중간에 하이픈이 있다.
FAKE_KEY = "sk-proj-" + "A" * 24 + "-" + "B" * 8


class _FakeChat:
    """invoke만 흉내 내는 대역. 정해 둔 응답을 돌려주거나 예외를 낸다."""

    def __init__(self, outcome: object) -> None:
        self.outcome = outcome

    def invoke(self, messages: object) -> object:
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


def test_settings_default_to_no_hidden_retries_and_bounded_timeout():
    settings = ChatModelSettings(model="test-model")

    assert settings.max_retries == 0
    assert settings.timeout_seconds == 30


@pytest.mark.parametrize(
    "fields",
    [
        {"model": " "},
        {"model": "m", "timeout_seconds": 0},
        {"model": "m", "timeout_seconds": float("inf")},
        {"model": "m", "max_retries": -1},
    ],
    ids=["blank-model", "zero-timeout", "infinite-timeout", "negative-retries"],
)
def test_invalid_settings_are_rejected(fields):
    with pytest.raises(ValidationError):
        ChatModelSettings(**fields)


def test_model_name_is_trimmed():
    assert ChatModelSettings(model=" test-model ").model == "test-model"


def test_missing_api_key_is_configuration_error_before_sdk(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(ApplicationError) as caught:
        create_chat_model(ChatModelSettings(model="test-model"))

    assert caught.value.code == "common.missing_env"


def test_created_model_uses_configured_timeout_and_retries(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test" + "A" * 24)

    chat = create_chat_model(
        ChatModelSettings(model="test-model", timeout_seconds=12, max_retries=1)
    )

    assert chat.model_name == "test-model"
    assert chat.request_timeout == 12
    assert chat.max_retries == 1


def test_text_reply_is_returned():
    assert (
        invoke_chat(_FakeChat(AIMessage(content="답변")), [("human", "질문")]) == "답변"
    )


def test_responses_api_text_blocks_are_returned_as_text():
    # Responses API(gpt-6 + tools 등)에서는 content가 블록 목록으로 온다.
    reply = AIMessage(
        content=[
            {"type": "reasoning", "summary": []},
            {"type": "text", "text": "답"},
            {"type": "text", "text": "변"},
        ]
    )

    assert invoke_chat(_FakeChat(reply), [("human", "질문")]) == "답변"


def test_provider_error_message_does_not_expose_api_key():
    error = openai.AuthenticationError(
        f"Incorrect API key provided: {FAKE_KEY}",
        response=httpx.Response(401, request=_REQUEST),
        body=None,
    )

    with pytest.raises(ApplicationError) as caught:
        invoke_chat(_FakeChat(error), [("human", "질문")])

    assert FAKE_KEY not in str(caught.value)


@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        (openai.APITimeoutError(request=_REQUEST), "infrastructure.llm_timeout"),
        (openai.APIConnectionError(request=_REQUEST), "infrastructure.llm_call_failed"),
        (
            openai.RateLimitError(
                "rate limited",
                response=httpx.Response(429, request=_REQUEST),
                body=None,
            ),
            "infrastructure.llm_call_failed",
        ),
    ],
    ids=["timeout", "connection", "rate-limit"],
)
def test_provider_failure_becomes_external_service_error(error, expected_code):
    with pytest.raises(ApplicationError) as caught:
        invoke_chat(_FakeChat(error), [("human", "질문")])

    assert caught.value.code == expected_code
    assert caught.value.category is ErrorCategory.EXTERNAL_SERVICE
    assert caught.value.__cause__ is error


def test_non_text_reply_is_contract_violation():
    reply = AIMessage(content=[{"type": "image_url", "image_url": {"url": "x"}}])

    with pytest.raises(ApplicationError) as caught:
        invoke_chat(_FakeChat(reply), [("human", "질문")])

    assert caught.value.code == "infrastructure.llm_invalid_output"
    assert caught.value.category is ErrorCategory.CONTRACT_VIOLATION


def test_programming_errors_are_not_reclassified_as_provider_failures():
    with pytest.raises(TypeError):
        invoke_chat(_FakeChat(TypeError("bug")), [("human", "질문")])
