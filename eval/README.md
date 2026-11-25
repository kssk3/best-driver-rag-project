## 이승주의 테스트용 문항 생성 (2026-11-25 15:27)

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
