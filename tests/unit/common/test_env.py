"""진입점용 환경변수 로딩과 필수값 확인의 동작 규격을 확인한다."""

import os

import pytest

from src.common.env import load_environment, require_env
from src.common.errors import ApplicationError, ErrorCategory

NAME = "SEOUL_RAG_TEST_SETTING"
OTHER = "SEOUL_RAG_TEST_OTHER"


@pytest.fixture(autouse=True)
def _clean_test_variables():
    # .env 로딩은 os.environ을 직접 바꾸므로 테스트가 만든 값을 끝에서 지운다.
    for name in (NAME, OTHER):
        os.environ.pop(name, None)
    yield
    for name in (NAME, OTHER):
        os.environ.pop(name, None)


def test_env_file_values_load_without_overriding_existing_variables(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(f"{NAME}=from-file\n{OTHER}=other-from-file\n", "utf-8")
    os.environ[NAME] = "from-shell"

    load_environment(env_file)

    assert os.environ[NAME] == "from-shell"
    assert os.environ[OTHER] == "other-from-file"


def test_default_env_file_in_working_directory_is_loaded(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(f"{NAME}=from-default\n", "utf-8")
    monkeypatch.chdir(tmp_path)

    load_environment()

    assert os.environ[NAME] == "from-default"


def test_missing_default_env_file_is_allowed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    load_environment()

    assert NAME not in os.environ


def test_missing_explicit_env_file_is_configuration_error(tmp_path):
    with pytest.raises(ApplicationError) as caught:
        load_environment(tmp_path / "missing.env")

    assert caught.value.category is ErrorCategory.CONFIGURATION


def test_required_variable_returns_its_value():
    os.environ[NAME] = "value"

    assert require_env(NAME) == "value"


@pytest.mark.parametrize("value", [None, "", "   "], ids=["unset", "empty", "blank"])
def test_missing_required_variable_names_the_variable(value):
    if value is not None:
        os.environ[NAME] = value

    with pytest.raises(ApplicationError) as caught:
        require_env(NAME)

    assert caught.value.code == "common.missing_env"
    assert caught.value.category is ErrorCategory.CONFIGURATION
    assert NAME in str(caught.value)
