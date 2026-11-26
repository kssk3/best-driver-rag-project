"""화면 테스트가 개발자 PC의 환경 변수와 외부 서버에 영향받지 않게 한다."""

import pytest


@pytest.fixture(autouse=True)
def _isolate_app_env(monkeypatch) -> None:
    for name in (
        "RAG_CHAT_SETTINGS",
        "LANGFUSE_BASE_URL",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
