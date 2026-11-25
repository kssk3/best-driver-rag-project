"""품목 별칭을 사용한 질문 정제와 변환 기록. 담당: 이정은."""

import json
from collections.abc import Callable
from pathlib import Path

from src.contracts import ResolvedQuery
from src.query.aliases import ITEM_ALIASES

QUERY_REWRITE_PROMPT_VERSION = "p09-v1"
_QUERY_REWRITE_PROMPT = Path(__file__).resolve().parents[2] / "prompts/query/rewrite.md"


def normalize_question(question: str) -> str:
    """새 품목명을 붙일 때 질문 앞뒤 공백 정리."""
    result = question

    # 같은 공식 품목명은 한 번만 추가
    for alias, canonical in ITEM_ALIASES.items():
        if alias in question and canonical not in result:
            result = f"{result.strip()} ({canonical})"

    return result


def rewrite_search_query(query: ResolvedQuery) -> str:
    """지역 보완 결과에서 검색 문장만 정제."""
    return normalize_question(query.search_query)


def make_prompt_rewriter(
    invoke: Callable[[str, str], str],
) -> Callable[[ResolvedQuery], str]:
    """프롬프트와 입력 JSON으로 검색 질의를 만드는 콜백 생성."""
    prompt = _QUERY_REWRITE_PROMPT.read_text(encoding="utf-8")

    def rewrite(query: ResolvedQuery) -> str:
        question = " ".join(query.search_query.split())
        expected_query = normalize_question(question)
        payload = json.dumps(
            {
                "question": query.search_query,
                "district": query.district,
                "dong": query.dong,
                "item_aliases": ITEM_ALIASES,
            },
            ensure_ascii=False,
        )
        try:
            output = invoke(prompt, payload)
        except Exception as error:
            # 공용 실행 기록에는 모델 응답이나 요청 본문 대신 오류 종류를 남긴다.
            raise RuntimeError(
                f"질문 다듬기 호출 실패 ({type(error).__name__})"
            ) from None

        if not isinstance(output, str):
            raise TypeError("질문 다듬기 출력은 문자열이어야 합니다.")
        result = output.strip()
        if not result or len(result.splitlines()) != 1:
            raise ValueError("질문 다듬기 출력은 비어 있지 않은 한 줄이어야 합니다.")
        result = " ".join(result.split())
        # 새로 붙이는 공식명에서만 괄호 앞 공백 차이를 허용한다.
        result_suffix = result[len(question) :].replace(" (", "(")
        expected_suffix = expected_query[len(question) :].replace(" (", "(")
        if not result.startswith(question) or result_suffix != expected_suffix:
            raise ValueError(
                "질문 다듬기 출력이 원질문과 등록 별칭 규칙을 벗어났습니다."
            )
        return expected_query

    return rewrite


def rewrite_question(
    question: str, *, normalizer: Callable[[str], str] | None = None
) -> dict[str, str]:
    """원질문·변환문·상태 반환. 공식명이 이미 있으면 unchanged."""
    if normalizer is None:
        normalizer = normalize_question
    try:
        rewritten = normalizer(question)
    except Exception as error:
        # 실패 시 원질문 사용과 오류 종류 기록
        return {
            "original_question": question,
            "rewritten_question": question,
            "status": "failed",
            "error_type": type(error).__name__,
        }

    return {
        "original_question": question,
        "rewritten_question": rewritten,
        "status": "changed" if rewritten != question else "unchanged",
    }


def append_rewrite_log(
    path: Path, result: dict[str, str], *, newline: str = "\n"
) -> None:
    """변환 결과 한 건을 지정한 줄끝으로 UTF-8 JSONL에 추가."""
    line = json.dumps(result, ensure_ascii=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline=newline) as file:
        file.write(line)
