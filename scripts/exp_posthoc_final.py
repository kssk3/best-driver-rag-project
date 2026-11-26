"""최종셋 사후 재실행(개선 시도): 표 행 변환 색인과 BM25·재정렬 입력 정리를 적용해 평가를 돌린다.

사용: uv run --locked --env-file .env python -m scripts.exp_posthoc_final <scripts.evaluate와 같은 인자>
`scripts.exp_embed_input`이 만든 `index-variant.json`을 설정의 `index_path`로 지정한다.
공식 결과(results/final-*)를 바꾸지 않으며 결과 폴더와 보고서에서 사후 실험으로 구분한다.
"""

from scripts import evaluate
from scripts.exp_embed_input import set_normalized_search_text


def main() -> None:
    set_normalized_search_text(True)
    evaluate.main()


if __name__ == "__main__":
    main()
