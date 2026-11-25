"""진입점에서 부르는 환경변수 로딩과 필수값 확인.

비밀값(API 키, 인증값)은 실행 설정 JSON(`src/config.py`)이 아니라 환경변수로 전달한다.
import만으로 `.env`를 읽지 않는다. 오류 메시지에는 변수 이름만 넣고 값은 넣지 않는다.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

from src.common.errors import ApplicationError, ErrorCategory

DEFAULT_ENV_FILE = Path(".env")


class EnvironmentFileMissingError(ApplicationError, FileNotFoundError):
    """명시한 `.env` 파일이 없는 경우."""

    code = "common.env_file_missing"
    category = ErrorCategory.CONFIGURATION
    user_message = "실행 환경 설정 파일을 찾을 수 없습니다."


class MissingEnvironmentError(ApplicationError, ValueError):
    """필수 환경변수가 없거나 비어 있는 경우."""

    code = "common.missing_env"
    category = ErrorCategory.CONFIGURATION
    user_message = "실행에 필요한 환경 설정이 없습니다."


def load_environment(path: str | Path | None = None) -> None:
    """`.env`를 읽어 아직 없는 환경변수만 채운다.

    path를 생략하면 현재 작업 폴더의 `.env`를 읽고, 없으면 그대로 둔다(CI·데모 실행).
    path를 명시했는데 파일이 없으면 EnvironmentFileMissingError를 낸다.
    이미 셸에 설정된 값은 덮어쓰지 않는다.
    """
    env_file = DEFAULT_ENV_FILE if path is None else Path(path)
    if not env_file.is_file():
        if path is None:
            return
        raise EnvironmentFileMissingError(f"환경 설정 파일이 없습니다: {env_file}")
    # python-dotenv는 파일이 없어도 조용히 False를 돌려주므로 위에서 먼저 확인한다.
    load_dotenv(env_file, override=False, encoding="utf-8")


def require_env(name: str) -> str:
    """필수 환경변수 값을 돌려준다. 없거나 공백뿐이면 MissingEnvironmentError."""
    value = os.environ.get(name, "").strip()
    if not value:
        raise MissingEnvironmentError(f"환경변수 {name}가 설정되지 않았습니다.")
    return value
