# 평가셋

개발용 `dev.json`과 최종용 `test.json`을 이 폴더에서 별도로 관리한다. 현재 실제 개발/최종 문항 파일은 없다. 실행기 연결을 확인하는 합성 3문항은 `tests/fixtures/handoff_eval.json`에 있으며 최종 평가셋으로 사용하지 않는다. 문항 수, 구성과 채점 기준은 [문제와 평가 기준](../docs/problem.md)을 따른다.

개발문항 초안은 답변 생성과 품질 추적 담당자(강성수), 최종셋 관리는 화면과 관찰 검증 담당자(이승주), 원문 근거 교차 확인은 데이터 수집과 질문 정제 담당자(이정은)가 맡는다.

현재 `load_evaluation_cases`는 공용 `EvaluationCase` 목록을 읽는다. 필수 필드는 `case_id`, `question`이고 선택 필드는 `district`, `dong`, `conditions`, `expected_status`, `reference_answer`, `allowed_chunk_ids`다. JSON 배열 또는 `{"is_synthetic": true, "cases": [...]}` 형태를 지원하며 다른 필드는 거부한다. 실행 방법은 [인계 문서](../docs/seokho-handoff.md#설정-실행-기록과-평가)를 따른다.

최종 채점에 필요한 필수 사실, 원문 위치와 판정 이유의 상세 구조는 현재 실행 입력에 포함되어 있지 않다. 해당 정보는 문항 ID에 연결한 별도 채점 자료로 관리하고, 평가 모듈과 연결할 때 규격을 맞춘다. 실행 입력에 필드를 임의로 추가하지 않는다. 최종셋은 준비하는 시점부터 개발과 튜닝에 사용하지 않는다.

정답표와 허용 근거 목록은 채점에만 사용하고 검색 색인, 생성과 질문 다듬기 입력에 전달하지 않는다. 정답을 뒷받침하는 원문 문서는 정상적으로 색인한다. 청킹을 바꾸면 근거 매핑을 갱신한다.

평가 실행기는 문항별 실제 응답과 원본 기록을 반환한다. 기대 상태와 정답을 자동 채점하거나 Hit@5, Ragas 지표를 계산하는 기능은 아직 연결하지 않았다.

## 이승주의 테스트용 문항 생성 (2026-11-25 15:27) / 참고 기재 / 나중에 아래 내용 삭제

아래 파일은 평가셋이 아니라, 화면·관찰 검증 담당(이승주)이 자가 구현(검증 패널과 문항 점검 도구)을 시험하려고 만든 테스트용 자료입니다. 추후 이 파일은 성수님 형식에 맞춰 고치거나 정리될 예정입니다.

<br />

| 파일                | 내용                                                                                                                                                                                                                                                                                    |
| ------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `test.json`         | 최종 20문항 형식(직접 검색 10, 표현 변형·조건 구분 7, 근거 없음 3)의 공용 `EvaluationCase` 목록. `reference_answer`(모범 정답)는 `test_grading.json`과 같은 값으로 양쪽에 둔다.                                                                                                         |
| `test_grading.json` | 문항 ID에 연결한 채점 자료. 답변 가능 17문항에는 필수 사실(`required_facts`), 원문 위치(`evidence`의 `document_id`, `source_location`)와 판정 이유(`reason`)를, 근거 없음 3문항에는 부재 이유(`absence_reason`)를 둔다. 정답은 `chunk_id`가 아니라 청킹 결과와 같은 원문 위치로 적었다. |
| `chunk_id_map.csv`  | 채점 자료의 원문 위치를 현재 청킹 결과(`preprocessed-v2-row-v1`, 557개)의 `chunk_id`로 푼 표다(답변 가능 17문항, HTML·JSON 형식 각각). 열 이름은 성수님의 `candidates.csv`에 맞췄다(`question_id`, `document_id`, `parent_mst`, `attachment_id`, `source_location`).                    |

<br />

- **점검**
  - `src/evaluation/case_set.py`가 문항 수와 구성, 문항과 채점표의 짝, 필수 사실·원문 위치·판정 이유, 두 파일의 `reference_answer` 일치, 개발 문항과의 겹침을 확인할 수 있습니다. 파일 구조는 임시이며 평가 모델이 정해지면 그에 맞춰 바꿉니다.

  ```bash
  uv run --locked python -m src.evaluation.case_set --cases eval/test.json --grading eval/test_grading.json
  # 개발 문항 파일이 있으면 --dev eval/dev.json 을 더해 겹침도 확인한다.
  ```

<br />

- **`chunk_id_map.csv` 만드는 방법**
  - 청킹을 바꾸면 다시 만듭니다. `scripts.prepare_data`로 청크를 만들고, 채점 자료의 `evidence`(`document_id`, `source_location`)와 청크의 `source_document_id`, `source_location`이 같은 청크를 찾습니다. `source_document_version`의 `v1`은 `prepare_data`를 실행할 때 부여된 값입니다.

<br />

- **이름 주의**
  - `test.json`은 위 평가셋의 최종 문항 파일 이름과 같습니다. 성수님의 파일이 이 폴더에 들어오면 이름 정리가 필요할 수 있습니다.

<br />

- 이 문항으로 검색 시스템을 돌려 보고 질문이나 정답을 고치지 마세요. (단순 테스트용 문항입니다.) 평가와 개선 반복은 개발 문항으로 해야 합니다.
