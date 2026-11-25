"""담당 모듈이 오류 없이 불러와지는지 확인한다. (기능 검증은 아님)"""

import importlib

import pytest

MODULES = [
    "src.validation",
    "src.interface.chat",
    "src.interface.map",
    "src.interface.inspection",
    "src.evaluation.comparison",
]


@pytest.mark.parametrize("module_name", MODULES)
def test_my_modules_import(module_name: str) -> None:
    importlib.import_module(module_name)
