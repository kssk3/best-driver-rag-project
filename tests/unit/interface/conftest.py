"""화면 테스트가 개발자 PC의 환경 변수에 영향받지 않게 한다."""

import pytest


@pytest.fixture(autouse=True)
def _isolate_app_env(monkeypatch) -> None:
    monkeypatch.delenv("RAG_CHAT_SETTINGS", raising=False)
    monkeypatch.delenv("RAG_SCORES_CSV", raising=False)
