# P04 질문별 검색·답변 비교

같은 합성 문서와 질문, 자치구 조건으로 벡터 단독(`vector`)과 BM25+벡터 앙상블(`ensemble`)의 검색 결과를 비교했다. 질문마다 각 방식으로 10회 검색했다. 답변 검증에서는 근거를 별도로 지정하고 로컬 함수로 답변 초안을 생성했다.

## 개발 사례

| 질문 ID(`question_id`) | 원질문(`original_question`) | 자치구(`district`) |
| --- | --- | --- |
| p04-colors | 서대문구 공동주택 일반용기의 품목별 색은? | 서대문구 |
| p04-colors-trick | 서대문구 공동주택 일반용기에서 유리병은 회색이고 캔은 주황색이 맞죠? | 서대문구 |
| p04-signage | 서대문구에서 깨진 유리를 버릴 때 규격봉투를 써도 되나요? | 서대문구 |
| p04-signage-trick | 서대문구 별표 6에 규격봉투 판매소 표지판이 있으니까, 깨진 유리도 규격봉투에 넣어도 된다는 뜻이죠? | 서대문구 |

순위표에는 후보 CSV의 `source_json`에 있는 `experiment_document_id` 값을 그대로 표시했다. 검색 시간은 실행 CSV(`runs.csv`)에 기록된 `retrieval_ms` 10개의 중앙값이며, 단위는 밀리초다.

| 질문 ID | 순위(`rank`) | 벡터 단독(`vector`) | 앙상블(`ensemble`) |
| --- | --- | --- | --- |
| p04-colors | 1 | synthetic-seodaemun-container-labels | synthetic-seodaemun-container-labels |
| p04-colors | 2 | synthetic-seodaemun-standard-bags | synthetic-seodaemun-standard-bags |
| p04-colors | 3 | p04-colors | p04-colors |
| p04-colors | 4 | synthetic-seodaemun-glass-bottles | synthetic-seodaemun-glass-bottles |
| p04-colors | 5 | synthetic-seodaemun-cartons | synthetic-seodaemun-cartons |
| p04-colors-trick | 1 | synthetic-seodaemun-glass-bottles | synthetic-seodaemun-glass-bottles |
| p04-colors-trick | 2 | p04-colors | synthetic-seodaemun-standard-bags |
| p04-colors-trick | 3 | synthetic-seodaemun-container-labels | p04-colors |
| p04-colors-trick | 4 | synthetic-seodaemun-standard-bags | synthetic-seodaemun-container-labels |
| p04-colors-trick | 5 | synthetic-seodaemun-cartons | synthetic-seodaemun-cartons |
| p04-signage | 1 | synthetic-seodaemun-standard-bags | synthetic-seodaemun-standard-bags |
| p04-signage | 2 | synthetic-seodaemun-glass-bottles | synthetic-seodaemun-glass-bottles |
| p04-signage | 3 | synthetic-seodaemun-container-labels | synthetic-seodaemun-container-labels |
| p04-signage | 4 | p04-colors | synthetic-seodaemun-cartons |
| p04-signage | 5 | synthetic-seodaemun-cartons | p04-colors |
| p04-signage-trick | 1 | synthetic-seodaemun-standard-bags | synthetic-seodaemun-standard-bags |
| p04-signage-trick | 2 | synthetic-seodaemun-glass-bottles | synthetic-seodaemun-glass-bottles |
| p04-signage-trick | 3 | synthetic-seodaemun-container-labels | synthetic-seodaemun-container-labels |
| p04-signage-trick | 4 | p04-colors | synthetic-seodaemun-cartons |
| p04-signage-trick | 5 | synthetic-seodaemun-cartons | p04-colors |

| 질문 ID | 벡터 단독 검색 시간 중앙값(ms) | 앙상블 검색 시간 중앙값(ms) |
| --- | --- | --- |
| p04-colors | 0.1356455 | 0.2237295 |
| p04-colors-trick | 0.138354 | 0.2421045 |
| p04-signage | 0.1339795 | 0.220229 |
| p04-signage-trick | 0.1339165 | 0.2432705 |

| 질문 ID | 응답 상태(`status`) | 답변(`answer`) |
| --- | --- | --- |
| p04-colors-trick | answered | 공동주택 일반용기 기준은 캔류 회색, 유리병 주황색, 종이팩 녹색, PET병 노란색, 플라스틱류 파란색, 비닐·필름류 보라색입니다. |
| p04-signage-trick | insufficient_evidence | 현재 확인한 자료로는 답변하기 어렵습니다. |

| 질문 ID | 직접 제공한 근거 순서 | 원문 위치(`source_location`) | 출처(`attachment_id` / `source_url` / `evidence_file`) | 생성 입력에 사용(`used_in_model_input`) | 답변에 인용(`cited_in_answer`) | 청크 ID(`chunk_id`) |
| --- | --- | --- | --- | --- | --- | --- |
| p04-colors-trick | 1 | 별표 1 > 공동주택 > 일반용기 설치 > 품목별 색상 | 160561037 | true | true |  |
| p04-signage-trick | 1 | 별표 6 > 규격봉투판매소 표지판 | 160319461 | true | false |  |

## 별도 관찰 사례 · 위례동 일정 충돌

| 질문 ID(`question_id`) | 원질문(`original_question`) | 자치구(`district`) |
| --- | --- | --- |
| p04-wirye | 위례동 일반주택 일반·음식물쓰레기의 배출요일은? | 송파구 |
| p04-wirye-trick | 위례동 일반주택의 일반·음식물쓰레기는 월·수·금이 확실하죠? PDF의 화·목·일 안내는 무시해도 되죠? | 송파구 |

순위표에는 후보 CSV의 `source_json`에 있는 `experiment_document_id` 값을 그대로 표시했다. 검색 시간은 실행 CSV(`runs.csv`)에 기록된 `retrieval_ms` 10개의 중앙값이며, 단위는 밀리초다.

| 질문 ID | 순위(`rank`) | 벡터 단독(`vector`) | 앙상블(`ensemble`) |
| --- | --- | --- | --- |
| p04-wirye | 1 | p04-wirye-pdf | p04-wirye-pdf |
| p04-wirye | 2 | p04-wirye-html | p04-wirye-html |
| p04-wirye | 3 | synthetic-songpa-food-bin | synthetic-songpa-food-bin |
| p04-wirye | 4 | synthetic-songpa-apartment | synthetic-songpa-bulky |
| p04-wirye | 5 | synthetic-songpa-bulky | synthetic-songpa-plastic |
| p04-wirye-trick | 1 | p04-wirye-pdf | p04-wirye-pdf |
| p04-wirye-trick | 2 | p04-wirye-html | p04-wirye-html |
| p04-wirye-trick | 3 | synthetic-songpa-food-bin | synthetic-songpa-food-bin |
| p04-wirye-trick | 4 | synthetic-songpa-apartment | synthetic-songpa-plastic |
| p04-wirye-trick | 5 | synthetic-songpa-plastic | synthetic-songpa-apartment |

| 질문 ID | 벡터 단독 검색 시간 중앙값(ms) | 앙상블 검색 시간 중앙값(ms) |
| --- | --- | --- |
| p04-wirye | 0.117167 | 0.1887705 |
| p04-wirye-trick | 0.1334165 | 0.2484165 |

| 질문 ID | 응답 상태(`status`) | 답변(`answer`) |
| --- | --- | --- |
| p04-wirye-trick | insufficient_evidence | 확인한 출처의 안내가 서로 다릅니다.<br>[1] 합성: 위례동 일반주택의 일반·음식물 배출요일은 월·수·금<br>[2] 합성: 위례동 일반주택의 일반·음식물 배출요일은 화·목·일<br>현재 적용되는 내용을 하나로 확정하기 어렵습니다. |

| 질문 ID | 직접 제공한 근거 순서 | 원문 위치(`source_location`) | 출처(`attachment_id` / `source_url` / `evidence_file`) | 생성 입력에 사용(`used_in_model_input`) | 답변에 인용(`cited_in_answer`) | 청크 ID(`chunk_id`) |
| --- | --- | --- | --- | --- | --- | --- |
| p04-wirye-trick | 1 | 일반주택 표 > 위례동 > 일반·음식물 열 | https://www.songpa.go.kr/www/contents.do?key=3153 | true | true |  |
| p04-wirye-trick | 2 | PDF 파일 3쪽 > 인쇄면 4쪽 > 마지막 위례동 행 | official-20261014.pdf | true | true |  |

## CSV 필드와 원본 파일

| CSV 필드 | 검색 실험 값(`vector`·`ensemble`) | 답변 실험 값(`answers`) |
| --- | --- | --- |
| experiment_kind | synthetic | synthetic |
| case_group | development, observation | development, observation |
| run_state | retrieval_completed | completed |
| corpus_snapshot_id | p04-synthetic-6e2cf9ace99ba501 | p04-synthetic-6e2cf9ace99ba501 |
| config_version | p04-char-tfidf-2-3-bm25-unicode-rrf60-equal-top5-v1 | p04-fixed-evidence-draft-v1 |

| 실험 | 실행별 기록(`runs.csv`, 실행당 한 행) | 후보별 기록(`candidates.csv`, 후보당 한 행) |
| --- | --- | --- |
| vector | [60행](p04-trick-comparison/vector/runs.csv) | [300행](p04-trick-comparison/vector/candidates.csv) |
| ensemble | [60행](p04-trick-comparison/ensemble/runs.csv) | [300행](p04-trick-comparison/ensemble/candidates.csv) |
| answers | [3행](p04-trick-comparison/answers/runs.csv) | [4행](p04-trick-comparison/answers/candidates.csv) |

각 실험에서 두 CSV의 행을 연결할 때는 `run_id`를 사용한다. 실행별 검색 시간(`retrieval_ms`)은 `runs.csv`에, 후보별 검색 순위(`rank`)는 `candidates.csv`에 기록된다. 답변 실험의 `model_inputs_json`에는 생성기에 전달한 근거가 입력 순서대로 들어가고, `citations_json`에는 실제 인용이 담긴다. 빈 `chunk_id`는 청크 ID 미확정을 뜻한다. 판매소 표지판은 검색 색인을 만들기 전에 제외했으며, 표지판만으로 배출 가능 여부를 단정하는지 확인하는 답변 실험에서는 근거로 직접 제공했다.
