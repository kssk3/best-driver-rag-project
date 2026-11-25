"""도메인 에러가 상속하는 공통 기반.

각 도메인은 자기 폴더에서 `ApplicationError`를 상속해 `code`와 `category`를 정한다.
기존 예외는 `class X(ApplicationError, ValueError)`처럼 다중 상속으로 옮기면
기존 `raise X("...")`와 `except ValueError`를 그대로 쓸 수 있다.
사용법과 코드 규칙은 docs/ERRORS.md에 둔다.
"""

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar

DEFAULT_USER_MESSAGE = "요청을 처리하는 중 오류가 발생했습니다."
UNEXPECTED_ERROR_CODE = "common.unexpected_error"

# `<도메인>.<이유>` 형식. 각 구간은 소문자로 시작하는 snake_case다.
_CODE_PATTERN = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+")


class ErrorCategory(StrEnum):
    """실행 중 예외의 공통 분류. 평가의 실패 분류(docs/problem.md)와는 별개다."""

    INVALID_INPUT = "invalid_input"
    CONFIGURATION = "configuration"
    EXTERNAL_SERVICE = "external_service"
    CONTRACT_VIOLATION = "contract_violation"
    INTERNAL = "internal"


def _validate_code(code: object) -> str:
    if not isinstance(code, str) or not _CODE_PATTERN.fullmatch(code):
        raise ValueError(
            f"에러 코드는 '<도메인>.<이유>' 형식의 소문자 snake_case여야 합니다: {code!r}"
        )
    return code


class ApplicationError(Exception):
    """프로젝트 예외의 공통 기반.

    code와 category는 클래스 속성으로 정한다. 같은 클래스에서 이유를 더 나눌 때만
    인스턴스의 `code=`로 덮어쓴다. user_message에는 원래 예외 메시지를 넣지 않는다.
    """

    code: ClassVar[str] = "common.application_error"
    category: ClassVar[ErrorCategory] = ErrorCategory.INTERNAL
    user_message: ClassVar[str] = DEFAULT_USER_MESSAGE

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        # 잘못된 코드나 분류는 사용 시점이 아니라 클래스를 정의할 때 드러낸다.
        _validate_code(cls.code)
        if not isinstance(cls.category, ErrorCategory):
            raise TypeError(
                f"{cls.__name__}.category는 ErrorCategory여야 합니다: {cls.category!r}"
            )
        if not isinstance(cls.user_message, str) or not cls.user_message.strip():
            raise TypeError(
                f"{cls.__name__}.user_message는 비어 있지 않은 고정 문구여야 합니다."
            )
        # ValueError 같은 예외가 앞에 오면 그 __init__이 먼저 실행돼 code=를 받지 못한다.
        # 예외가 아닌 mixin은 검사하지 않는다. mixin이 __init__을 정의하면
        # *args, **kwargs를 super().__init__에 넘겨야 code=가 전달된다(docs/ERRORS.md).
        for base in cls.__mro__[1:]:
            if base is ApplicationError:
                break
            if issubclass(base, BaseException) and not issubclass(
                base, ApplicationError
            ):
                # 메시지에는 실제로 앞으로 옮겨야 할 ApplicationError 계열 부모를 쓴다.
                family = next(
                    item
                    for item in cls.__mro__[1:]
                    if issubclass(item, ApplicationError)
                )
                raise TypeError(
                    f"{cls.__name__}: {family.__name__}를 {base.__name__}보다 "
                    "앞에 두고 상속해야 합니다."
                )

    def __init__(self, message: str = "", *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            # 인스턴스 속성이 클래스 속성을 가린다. 클래스 기본값은 바뀌지 않는다.
            self.code = _validate_code(code)  # type: ignore[misc]


@dataclass(frozen=True)
class ErrorInfo:
    """예외를 사용자용 메시지와 내부 상세로 나눈 결과.

    user_message는 화면에 보여도 되는 문구이고, detail은 실행 기록용 내부 정보다.
    """

    code: str
    category: ErrorCategory
    user_message: str
    detail: str


def _detail(error: BaseException) -> str:
    message = str(error)
    name = type(error).__name__
    return f"{name}: {message}" if message else name


def describe_error(error: BaseException) -> ErrorInfo:
    """예외 하나를 공통 형식으로 설명한다. ApplicationError가 아니면 internal로 본다."""
    if isinstance(error, ApplicationError):
        return ErrorInfo(
            code=error.code,
            category=error.category,
            user_message=error.user_message,
            detail=_detail(error),
        )
    return ErrorInfo(
        code=UNEXPECTED_ERROR_CODE,
        category=ErrorCategory.INTERNAL,
        user_message=DEFAULT_USER_MESSAGE,
        detail=_detail(error),
    )
