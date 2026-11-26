"""명시적으로 켠 RAG 실행에만 요청 전용 LangChain 콜백을 설치한다."""

import logging
import os
import sys
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from functools import lru_cache
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


@lru_cache(maxsize=1)
def _configured_client():
    try:
        from langfuse import Langfuse

        url, public, secret = langfuse_settings()
        return Langfuse(
            public_key=public, secret_key=secret, base_url=url.geturl()
        ), public
    except Exception:
        logging.getLogger(__name__).warning(
            "Langfuse 초기화 실패. HTTPS 주소와 프로젝트 키를 확인하세요. 로컬 실행을 계속합니다."
        )
        return None


@contextmanager
def trace_pipeline(run_id: str, run_kind: str, variant: str):
    configured = _configured_client() if tracing_enabled() else None
    if configured is None:
        yield
        return

    client, public = configured
    stack = ExitStack()
    try:
        from langfuse import propagate_attributes
        from langfuse.langchain import CallbackHandler

        stack.enter_context(
            client.start_as_current_observation(
                as_type="span",
                name="rag-pipeline",
                trace_context={"trace_id": trace_id_for_run(run_id)},
                metadata={"run_id": run_id, "variant": variant},
            )
        )
        stack.enter_context(
            propagate_attributes(environment=run_kind, trace_name=f"RAG {variant}")
        )
        token = _handler.set(CallbackHandler(public_key=public))
        stack.callback(_handler.reset, token)
    except Exception:
        logging.getLogger(__name__).warning("Langfuse 실행 추적을 시작할 수 없습니다.")
        _close_trace(stack)
        yield
        return
    try:
        yield
    finally:
        _close_trace(stack)


def _close_trace(stack: ExitStack):
    try:
        stack.__exit__(*sys.exc_info())
    except Exception:
        logging.getLogger(__name__).warning("Langfuse 실행 추적을 종료할 수 없습니다.")


def flush_traces() -> None:
    configured = _configured_client() if tracing_enabled() else None
    if configured is not None:
        client, _ = configured
        try:
            client.flush()
        except Exception:
            logging.getLogger(__name__).warning(
                "Langfuse 전송 실패. 로컬 실행 기록을 확인하세요."
            )
