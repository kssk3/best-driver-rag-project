"""진입점용 공용 로그 설정의 동작 규격을 확인한다."""

import logging
import subprocess
import sys

import pytest

from src.common.log_setup import configure_logging, mask_secrets

# 실제 키가 아닌 합성 값. 프로젝트 키(sk-proj-…)처럼 중간에 하이픈이 있다.
FAKE_KEY = "sk-proj-" + "A" * 24 + "-" + "B" * 8


@pytest.fixture(autouse=True)
def _restore_root_logger():
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


def test_repeated_configuration_adds_one_handler_and_applies_latest_level():
    before = len(logging.getLogger().handlers)

    configure_logging("info")
    configure_logging("debug")

    assert len(logging.getLogger().handlers) == before + 1
    assert logging.getLogger().level == logging.DEBUG


def test_api_key_in_message_arguments_and_traceback_is_not_printed(capsys):
    configure_logging()
    logger = logging.getLogger("tests.log_setup")

    logger.warning("키 %s 로 호출", FAKE_KEY)
    try:
        raise RuntimeError(f"인증 실패: {FAKE_KEY}")
    except RuntimeError:
        logger.exception("모델 호출 실패")

    output = capsys.readouterr().err
    assert "키 sk-*** 로 호출" in output
    assert "모델 호출 실패" in output
    assert "RuntimeError: 인증 실패: sk-***" in output
    assert FAKE_KEY not in output


@pytest.mark.parametrize(
    "text",
    [repr("line1\n" + FAKE_KEY), "Bearer%20" + FAKE_KEY, "API_KEY_" + FAKE_KEY],
    ids=["escaped-newline", "url-encoded", "joined-name"],
)
def test_key_right_after_other_characters_is_masked(text):
    assert FAKE_KEY not in mask_secrets(text)


def test_import_does_not_configure_root_logger():
    script = (
        "import logging; before = list(logging.getLogger().handlers); "
        "import src.common.log_setup; "
        "print(logging.getLogger().handlers == before)"
    )

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )

    assert result.stdout.strip() == "True"
