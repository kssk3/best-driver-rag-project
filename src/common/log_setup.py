"""진입점에서 한 번 호출하는 공용 로그 설정.

모듈은 `logging.getLogger(__name__)`으로 로거를 얻고, 출력 방식은 진입점(스크립트,
화면)이 `configure_logging()`으로 정한다. import만으로 루트 로거를 바꾸지 않는다.
파일 이름을 `logging.py`로 두지 않은 것은 표준 라이브러리와 이름이 겹치지 않게 하려는 것이다.
"""

import logging
import re

# OpenAI 형식의 키(sk-로 시작하는 20자 이상). 키 파일에서 키 하나를 고르는
# embeddings.configure_key_file과 달리, 가리기는 놓치는 쪽이 더 위험하므로 앞 글자를
# 제한하지 않는다. repr의 "\nsk-…"나 URL 인코딩된 "%20sk-…"도 가린다.
_SECRET_PATTERN = re.compile(r"sk-[A-Za-z0-9_-]{20,}")
_HANDLER_NAME = "seoul_rag_console"
_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def mask_secrets(text: str) -> str:
    """문자열 안의 API 키를 가린다. 키 앞부분도 남기지 않는다."""
    return _SECRET_PATTERN.sub("sk-***", text)


class _SecretMaskingFormatter(logging.Formatter):
    # 메시지 인자와 예외 traceback까지 합쳐진 최종 문자열을 가려야 빠짐이 없다.
    def format(self, record: logging.LogRecord) -> str:
        return mask_secrets(super().format(record))


def configure_logging(level: int | str = logging.INFO) -> None:
    """루트 로거에 키를 가리는 콘솔 핸들러를 붙인다. 다시 호출하면 수준만 바꾼다.

    level은 "debug"처럼 소문자 이름도 받는다. 가리기는 이 함수가 붙인 핸들러에만
    적용된다. 다른 곳에서 먼저 붙인 핸들러(basicConfig, OPENAI_LOG 등)는 바꾸지 않는다.
    """
    root = logging.getLogger()
    root.setLevel(level.upper() if isinstance(level, str) else level)
    if any(handler.get_name() == _HANDLER_NAME for handler in root.handlers):
        return
    handler = logging.StreamHandler()
    handler.set_name(_HANDLER_NAME)
    handler.setFormatter(_SecretMaskingFormatter(_FORMAT))
    root.addHandler(handler)
