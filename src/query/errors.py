"""질문 정제의 호출·출력·설정 오류. 담당: 이정은."""

from src.common.errors import ApplicationError, ErrorCategory


class RewriteCallError(ApplicationError, RuntimeError):
    """질문 정제 모델 호출 실패."""

    code = "query.rewrite_call_failed"
    category = ErrorCategory.EXTERNAL_SERVICE
    user_message = "질문 다듬기를 완료하지 못했습니다."


class RewriteOutputTypeError(ApplicationError, TypeError):
    """모델 출력이 문자열이 아닌 경우."""

    code = "query.rewrite_invalid_type"
    category = ErrorCategory.CONTRACT_VIOLATION
    user_message = "질문 다듬기 결과를 사용할 수 없습니다."


class RewriteOutputError(ApplicationError, ValueError):
    """모델 출력의 형식이나 원질문 보존 규칙 위반."""

    code = "query.rewrite_invalid_format"
    category = ErrorCategory.CONTRACT_VIOLATION
    user_message = "질문 다듬기 결과를 사용할 수 없습니다."


class RewriteConfigurationError(ApplicationError, ValueError):
    """질문 정제를 켰지만 모델 호출 함수가 없는 경우."""

    code = "query.rewrite_not_configured"
    category = ErrorCategory.CONFIGURATION
    user_message = "질문 다듬기 설정을 확인해 주세요."
