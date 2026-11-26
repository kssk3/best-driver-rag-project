"""최종셋 사후 재실행(개선 시도): 표 행 변환 색인과 BM25·재정렬 입력 정리를 적용해 평가를 돌린다.

사용: uv run --locked --env-file .env python -m scripts.exp_posthoc_final <scripts.evaluate와 같은 인자>
`scripts.exp_embed_input`이 만든 `index-variant.json`을 설정의 `index_path`로 지정해야 한다.
기본 색인을 가리키면 BM25·재정렬 입력만 바뀐 실행이 전체 실험처럼 표시되므로 시작 전에 막는다.
공식 결과(results/final-*)를 바꾸지 않으며 결과 폴더와 보고서에서 사후 실험으로 구분한다.
"""

import argparse
import json
import sys
from pathlib import Path

from scripts import evaluate
from scripts.exp_embed_input import VARIANT_ID_MARKER, set_normalized_search_text
from src.infrastructure.stores import load_index

ROOT = Path(__file__).resolve().parent.parent


def require_variant_index(settings_path: Path) -> None:
    """설정의 색인이 변환 색인(색인 ID에 변환 표식이 있는 것)이 아니면 중단한다."""
    index_path = json.loads(settings_path.read_text(encoding="utf-8"))["index_path"]
    index_id = load_index(ROOT / index_path).metadata.index_id
    if VARIANT_ID_MARKER not in index_id:
        sys.exit(
            f"설정의 색인이 변환 색인이 아닙니다({index_id}). "
            "scripts.exp_embed_input이 만든 index-variant.json을 index_path로 지정하세요."
        )


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--settings", type=Path)
    known, _ = parser.parse_known_args()
    if known.settings is None:
        sys.exit("--settings가 필요합니다(변환 색인을 가리키는 설정 파일).")
    require_variant_index(known.settings)
    set_normalized_search_text(True)
    evaluate.main()


if __name__ == "__main__":
    main()
