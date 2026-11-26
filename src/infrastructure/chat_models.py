"""공용 채팅 모델 생성과 호출 오류 분류.

SDK 기본값은 기록 없이 2번 재시도하고 600초까지 기다린다. 평가에서 시도와 응답 시간을
그대로 집계하도록 기본 재시도는 0, timeout은 30초로 둔다. 재시도가 필요하면
호출하는 쪽에서 시도마다 기록을 남기며 명시적으로 수행한다.
생성만으로 외부 요청을 보내지 않는다.
"""

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import BaseMessage
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI
from openai import APITimeoutError, OpenAIError
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.common.env import require_env
from src.common.errors import ApplicationError, ErrorCategory
from src.common.log_setup import mask_secrets
from src.observability.live import current_handler


class ModelCallError(ApplicationError, RuntimeError):
    """모델 제공자 호출 실패. 시간 초과는 code를 llm_timeout으로 나눈다."""

    code = "infrastructure.llm_call_failed"
    category = ErrorCategory.EXTERNAL_SERVICE
    user_message = "답변 모델을 호출하지 못했습니다."


class ModelOutputError(ApplicationError, TypeError):
    """모델 응답에 답변 텍스트가 없거나 공백뿐인 경우."""

    code = "infrastructure.llm_invalid_output"
    category = ErrorCategory.CONTRACT_VIOLATION
    user_message = "답변 모델의 응답을 사용할 수 없습니다."


class ChatModelSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str
    # inf는 timeout이 없는 것과 같으므로 막는다.
    timeout_seconds: float = Field(default=30, gt=0, allow_inf_nan=False)
    max_retries: int = Field(default=0, ge=0)

    @field_validator("model")
    @classmethod
    def _model_is_named(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("사용할 모델 이름을 지정하세요.")
        return value.strip()


def create_chat_model(settings: ChatModelSettings) -> ChatOpenAI:
    """설정한 timeout과 재시도로 OpenAI 채팅 모델을 만든다.

    키가 없으면 SDK의 OpenAIError 대신 MissingEnvironmentError(common.missing_env)를 낸다.
    키 값은 SDK가 환경변수에서 직접 읽으며 여기서 다루거나 기록하지 않는다.
    """
    require_env("OPENAI_API_KEY")
    return ChatOpenAI(
        model=settings.model,
        timeout=settings.timeout_seconds,
        max_retries=settings.max_retries,
    )


def invoke_chat(
    chat: Runnable[LanguageModelInput, BaseMessage], messages: LanguageModelInput
) -> str:
    """모델을 한 번 호출해 답변 텍스트를 앞뒤 공백까지 그대로 str로 돌려준다.

    Raises:
        ModelCallError: 제공자 호출 실패. 시간 초과는 llm_timeout 코드다.
        ModelOutputError: 응답에 답변 텍스트가 없거나 공백뿐인 경우.
    OpenAI 오류가 아닌 예외는 외부 장애로 바꾸지 않고 그대로 올린다. 코드 버그 외에
    langchain-openai가 형식이 다른 응답 본문에 내는 ValueError 등도 여기에 해당한다.
    """
    try:
        handler = current_handler()
        if handler is None:
            reply = chat.invoke(messages)
        else:
            reply = chat.invoke(messages, config={"callbacks": [handler]})
    except APITimeoutError as error:
        raise ModelCallError(
            f"모델 응답 시간 초과: {type(error).__name__}",
            code="infrastructure.llm_timeout",
        ) from error
    except OpenAIError as error:
        # 제공자 메시지는 원인 파악에 필요하지만 실행 기록에 남으므로 키 형식은 가린다.
        raise ModelCallError(
            f"모델 호출 실패: {type(error).__name__}: {mask_secrets(str(error))}"
        ) from error
    # Responses API(gpt-6 + tools, codex 등)는 content를 블록 목록으로 준다.
    # reply.text는 문자열이면 그대로, 블록 목록이면 문자열 항목과 text 블록만 이어 붙인
    # 값이다. tool 호출만 있는 응답은 content가 ""이므로, 형식과 관계없이 같은 기준으로
    # 거부한다. reply.text는 호출도 되는 str 하위 클래스라 일반 str로 바꿔 돌려준다.
    text = str(reply.text)
    if not text.strip():
        raise ModelOutputError("모델이 텍스트 응답을 반환하지 않았습니다.")
    return text
