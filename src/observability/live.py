"""명시적으로 켠 RAG 실행에만 요청 전용 LangChain 콜백을 설치한다."""

import os
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

from src.observability.tracing import langfuse_settings, trace_id_for_run

if TYPE_CHECKING:
    from langfuse.langchain import CallbackHandler

_handler: ContextVar["CallbackHandler | None"] = ContextVar(
    "rag_langfuse_handler", default=None
)


def current_handler():
    return _handler.get()


def tracing_enabled() -> bool:
    return os.environ.get("RAG_LANGFUSE_TRACE") == "1"


@contextmanager
def trace_pipeline(run_id: str, run_kind: str, variant: str):
    if not tracing_enabled():
        yield
        return
    from langfuse import Langfuse, propagate_attributes
    from langfuse.langchain import CallbackHandler

    url, public, secret = langfuse_settings()
    client = Langfuse(public_key=public, secret_key=secret, base_url=url.geturl())
    trace_id = trace_id_for_run(run_id)
    with (
        client.start_as_current_observation(
            as_type="span",
            name="rag-pipeline",
            trace_context={"trace_id": trace_id},
            metadata={"run_id": run_id, "variant": variant},
        ),
        propagate_attributes(environment=run_kind, trace_name=f"RAG {variant}"),
    ):
        token = _handler.set(CallbackHandler(public_key=public))
        try:
            yield
        finally:
            _handler.reset(token)


def flush_traces() -> None:
    if tracing_enabled():
        from langfuse import get_client

        _, public, _ = langfuse_settings()
        get_client(public_key=public).flush()
