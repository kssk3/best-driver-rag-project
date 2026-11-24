"""명시적으로 로드할 때만 테스트의 기본 파일 인코딩을 CP949로 모사.

실제 Windows 실행을 대신하지 않는다. 애플리케이션 코드와 UTF-8을
명시한 호출은 변경하지 않고 지정한 ingestion 테스트 호출만 검사한다.
"""

import os
import sys
from pathlib import Path

import pytest

_ORIGINAL_READ = Path.read_text
_ORIGINAL_WRITE = Path.write_text
_TEST_SCOPE = Path(
    os.environ.get(
        "INGESTION_TEST_SCOPE",
        str(Path(__file__).resolve().parents[3] / "tests/unit/ingestion"),
    )
).resolve()


def _read(
    self: Path,
    encoding: str | None = None,
    errors: str | None = None,
    newline: str | None = None,
) -> str:
    caller = Path(sys._getframe(1).f_code.co_filename).resolve()
    if encoding is None and caller.is_relative_to(_TEST_SCOPE):
        encoding = "cp949"
    return _ORIGINAL_READ(self, encoding=encoding, errors=errors, newline=newline)


def _write(
    self: Path,
    data: str,
    encoding: str | None = None,
    errors: str | None = None,
    newline: str | None = None,
) -> int:
    caller = Path(sys._getframe(1).f_code.co_filename).resolve()
    if encoding is None and caller.is_relative_to(_TEST_SCOPE):
        encoding = "cp949"
    return _ORIGINAL_WRITE(
        self, data, encoding=encoding, errors=errors, newline=newline
    )


def pytest_sessionstart(session: pytest.Session) -> None:
    Path.read_text = _read
    Path.write_text = _write


def pytest_unconfigure(config: pytest.Config) -> None:
    Path.read_text = _ORIGINAL_READ
    Path.write_text = _ORIGINAL_WRITE
