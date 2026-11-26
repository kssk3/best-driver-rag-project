import pytest


@pytest.fixture(autouse=True)
def _no_langfuse_network(monkeypatch):
    """화면 테스트가 실제 Langfuse 서버로 나가지 않게 주소와 키를 지운다."""
    for name in ("LANGFUSE_BASE_URL", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
        monkeypatch.delenv(name, raising=False)
