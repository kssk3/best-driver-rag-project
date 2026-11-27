# 정은 담당 리라이트 규칙과 조건 검수

2026-11-27 작성. 모델 호출·검색 재실행·Langfuse 전송 없이 로컬에서 검증했다.

## 파일별 반영과 유지

| 담당 파일 | 이번 반영 | 이유·한계 |
| --- | --- | --- |
| `prompts/query/rewrite.md` | v3. 생활/사업장/공공/재사용, 숫자·단위, 현재/미래, 실제 판매/제작 허용, 보냉 예외 보존을 명시 | 모델용 규칙. 실제 모델 호출 성능은 미검증 |
| `src/query/rewrite.py` | 프롬프트 버전을 query-rewrite-v3으로 연결 | 기존 허용 출력 검사와 원질문 보존 규칙 유지. 별칭 자체는 증설하지 않음 |
| `src/rewrite_dictionary/prompt_instructions.md` | 같은 의미 보존 기준을 검토용 문안에 추가하고 실행 경로 차이를 명시 | 이 문안은 공식 카탈로그 런타임에서 읽지 않음 |
| `src/query/aliases.py` | 우유팩·두유팩·소주팩→종이팩 유지 | 근거 있는 의미 별칭. 이번에 추가하지 않음 |
| `src/rewrite_dictionary/runtime.py`, `item_catalog.json` | 선택 문장 축약 제거, 사전 유지 | 별칭 후보만 선택·제외 판단하고 원문 조건은 본문에 보존 |
| `scripts/review_rewrite_conditions.py` | 두 경로의 변환과 필수 문자열 누락 후보를 CSV로 기록 | 표준 라이브러리와 기존 리라이트만 실행. 모델·DB·검색 호출 없음 |
| `tests/unit/query/test_condition_review.py` | 용도·시점·실제 판매·예외·용량 삭제를 잡는 검사 | 자동 검사가 사람의 의미 검수를 대신하지 않음 |

## 검수표 사용

- `rewrite_condition_cases.json`: 12개 질문과 보존 문자열. 기존 공식 5문항은 관찰용이며 튜닝·새 성능 검증에 쓰지 않는다. 나머지는 조건 점검용 초안이다.
- `rewrite_condition_review.csv`: 선택 문장 축약 수정 전 코드로 만든 24행. `catalog-rules`는 규칙 기반 실제 변환, `prompt-rule-expected`는 normalize_question으로 계산한 모델 출력의 허용 기준이다. 모델을 호출한 결과가 아니다.
- 필수 문자열, 원질문 본문 보존 여부를 먼저 확인한다. `문자열 보존`은 의미 적합·근거 적합·검색 성공을 뜻하지 않는다.
- 사람이 원문을 열어 문서·행·열과 예외를 확인한 뒤 `source_checked`, `reviewer`, `reviewed_at`, `decision`, `note`를 기록하고 `human_status`를 바꾼다. 현재 전 행은 미검수다.
- 검수 상태를 바꾼 CSV는 같은 이름으로 다시 생성하지 않는다. 도구는 기존 출력 덮어쓰기를 거절한다.

저장소 루트의 VS Code 터미널에서 새 비교 파일을 생성할 때:

```zsh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m scripts.review_rewrite_conditions --output docs/jungeun/rewrite_condition_review_next.csv
```

JSON의 `reference_case_id`는 근거를 찾기 위한 참조다. 변형 질문에 기존 모범 답안을 그대로 적용한다는 뜻이 아니다. 근거가 없는 실제 판매 질문은 허용 규정만으로 답변 가능으로 바꾸면 안 된다.

## 선택 문장 축약 수정 완료

사용자 요청으로 카탈로그 경로의 `project_selected_items` 호출을 제거했다. 기존 언어 정규화는 유지하고 `active_item_matches`로 별칭 후보만 선택한다. 제외·비교 대상도 질문 본문에서 지우지 않는다. 지역 인자를 받는 공개 인터페이스는 유지한다.

- 입력: `서대문구에서 우유팩이랑 유리병 중 우유팩만 버려요.`
- 수정 후: `서대문구에서 우유팩이랑 유리병 중 우유팩만 버려요. (종이팩)`
- `우유팩 말고 족발뼈만`은 원문을 유지하고 `(돼지뼈)`만 붙인다.
- 선택을 확정할 수 없거나 나머지 품목에 대한 추가 질문이 있으면 기존처럼 전체 품목을 대상으로 한다.
- 공식명이 본문에 이미 있으면 중복해서 붙이지 않는다. 재변환해도 동일한지 기존 테스트를 확인한다.

`rewrite_condition_review.csv`는 수정 전 기록으로 보존했다. 수정 후 자동 점검은 `rewrite_condition_review_after_selection.csv`다. 사람의 출처 검수 상태는 여전히 미검수다. 이 결과는 검색 성능 평가가 아니다.

## 공식 결과와 다음 우선순위

공식 C OFF와 ON은 12/17로 동일. 변경된 검색어 5개에서도 적중·허용 청크 순위·응답 상태가 같았다. d07은 답변과 인용이 같아도 모델 채점이 달랐으므로 점수만으로 규칙을 늘리지 않는다.

1. 담당 안: 검수표의 조건과 사람 원문 검수를 확정한다. 붙여쓰기와 의미 별칭을 다른 rule_group으로 비교한다.
2. 협업 우선: d05는 별칭 추가보다 표 행의 검색용 표현을 먼저 검증한다. 전달된 PR #49 탐색 사례는 원질문·리라이트 OFF에서 표 표현 변경 후 허용 청크 1위와 답변을 관찰했다. 최종 실패를 본 뒤 같은 문제에 변경을 묶어 적용한 결과이므로 개별 변경 효과·일반화 증거로 쓰지 않는다.
3. 이번에는 색인·검색·생성 프롬프트·공식 평가 원본을 변경하지 않는다. 다음 성능 검증은 사람이 근거를 확인한 별도 개발 문항에서 하고, 검색어 불변 대조군과 반복 변동을 함께 본다.

## 근거

- [공식 병합 PR #48](https://github.com/kssk3/best-driver-rag-project/pull/48)
- [고정 평가셋](https://github.com/kssk3/best-driver-rag-project/blob/f2ace36cedc6baa041726d4f9d0968bec4d4ed95/eval/test.json)
- [근거 위치·필수 사실](https://github.com/kssk3/best-driver-rag-project/blob/f2ace36cedc6baa041726d4f9d0968bec4d4ed95/eval/test-grading.json)
- [공식 OFF 실행](https://github.com/kssk3/best-driver-rag-project/blob/f2ace36cedc6baa041726d4f9d0968bec4d4ed95/results/final-abc-2026-11-26/runs.csv)
- [공식 ON 실행](https://github.com/kssk3/best-driver-rag-project/blob/f2ace36cedc6baa041726d4f9d0968bec4d4ed95/results/final-c-rewrite-2026-11-26/runs.csv)
- [평가 정오표](https://github.com/kssk3/best-driver-rag-project/blob/f2ace36cedc6baa041726d4f9d0968bec4d4ed95/eval/errata/README.md)
- [전달된 d05 탐색 실행](https://github.com/kssk3/best-driver-rag-project/blob/eb7971011aec32803205c76d176cd8eeafaaac49/results/posthoc-final-abc-v2-2026-11-27/runs.csv#L16)
