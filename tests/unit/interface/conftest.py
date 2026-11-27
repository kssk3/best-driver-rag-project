"""화면 테스트가 개발자 PC의 환경 변수와 외부 서버에 영향받지 않게 한다."""

import pytest


@pytest.fixture(autouse=True)
def _isolate_app_env(monkeypatch) -> None:
    # 설정이 없으면 화면 위에 설정 안내 오류가 보인다. 기본은 설정이 있는 상태로 둔다.
    # 파이프라인을 직접 돌리는 테스트는 팩토리를 가짜로 바꾼다.
    monkeypatch.setenv("RAG_CHAT_SETTINGS", "configs/team-c-rewrite-chat.json")
    for name in (
        "LANGFUSE_BASE_URL",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
