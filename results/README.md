# 실행 원본과 비교 결과

실행별로 질문, 검색 후보, 생성기에 전달된 청크, 답변과 인용, 소요 시간, 오류, 실행 설정과 자료 버전을 보관한다. 팀 A의 개발 문항 2개로 얻은 기준 데이터는 아래 CSV에서 확인할 수 있다. 최종 20문항에 대한 구성별 비교는 후속 작업이다.

`scripts.demo`는 합성 색인과 `summary.json`을, `scripts.evaluate`는 `evaluation.json`을 생성한다. 데모 경로는 각 실행 폴더의 `runs/<run_id>.json`에 개별 기록도 남긴다. 평가의 `--factory` 경로에서 개별 파일을 남기려면 연결 함수가 `create_runtime` 등으로 기록기를 붙여야 한다. 기록기가 없어도 정상 반환된 `RunRecord`는 `evaluation.json`에 포함된다. 평가 명령에 `--output-dir`를 지정할 때는 새 폴더를 사용하며, 기록기는 같은 실행 ID 파일을 덮어쓰지 않는다. 자세한 경로와 명령은 [인계 문서](../docs/handoff.md)를 따른다.

양석호가 인계한 실행 기록을 바탕으로 이명지는 검색 순위, 이정은은 프롬프트 변경 전후, 강성수는 답변·인용을 확인한다. 이승주는 청킹 변경의 영향과 화면에 표시되는 근거를 비교한다. [현재 역할표](../ROADMAP.md#업무-분담과-인계)

## 전처리 자료 검색·답변 실험 결과

[전처리 자료 질문별 결과표](testData.md)에서 저장소에 포함된 CSV 원본을 열 수 있다. 재현하려면 [검색 비교 명령](../README.md#dev-반영-후-답변과-지역-해석-검증)을 실행하고 `results/local/` 아래에 새 출력 폴더를 지정한다. 출력 폴더 안의 `vector/`, `ensemble/`, `answers/`에는 각각 `runs.csv`와 `candidates.csv`가 생긴다. 같은 실행의 두 파일은 `run_id`로 연결한다. `candidate_count`가 빈칸이면 후보 목록을 받지 못했고, `0`이면 검색을 마쳤지만 찾은 후보가 없다는 뜻이다.

`vector/`와 `ensemble/`에는 검색 순위와 소요 시간이 기록된다. `answers/`에는 함정 질문 3개에 근거를 직접 제공해 얻은 답변이 기록된다. 이 CSV들은 검색 비교 명령을 실행할 때 생성된다. 공통 런타임은 실행별 기록을 JSON으로 저장한다.

답변 작업 브랜치의 색상표 실험에서는 검색 결과 JSON과 그 결과를 사용한 답변 실행 JSON이 따로 생긴다. 답변 기록의 `model_input_chunk_ids`를 검색 순위와 대조하고 `response.citations`에서 실제 인용을 확인한다. 저장된 후보를 다시 사용한 답변 실행의 유형은 `fixed_evidence`다. [실행 명령과 판정 기준](../eval/README.md#색상표-개발-문항-실행)

최초 실패, 재시도와 변경 후 추가 실험은 별도로 남긴다. `RunRecord.duration_ms`는 기록 파일 저장 전까지의 파이프라인 시간이며 리라이트 시간을 포함한다. 현재 토큰 사용량, API 비용과 Ragas 사후 평가 시간은 자동 수집하지 않는다. 합성 데모는 `run_kind="demo"`로 기록하며 실제 검색/생성 결과와 구분한다.

이 폴더 전체를 Git에서 제외하지 않는다. 제출용 기록은 비밀값과 공유 가능 여부를 검토해 포함하며, 큰 기록은 관리 위치, 버전과 접근 방법을 남긴다. 로컬 실험용 `local/`은 제외한다. [평가 기준](../docs/problem.md)을 기준으로 비교하며 결과를 검색 색인에 넣지 않는다.

## 평가할 때마다 저장하는 CSV

`python -m scripts.evaluate`를 `--demo` 또는 `--factory`로 실행하면 `--output-dir`에 `cases.csv`, `runs.csv`, `candidates.csv`와 `evaluation.json`을 저장한다. 실행할 때마다 새 폴더를 지정한다. 아래 명령은 팀 A 검색기로 두 개발 문항을 각각 평가하고, 폴더 이름에 실행 시각(UTC)을 넣는다. 먼저 [조례 색인 준비 방법](../eval/README.md#색상표-개발-문항-실행)에 따라 색인을 준비하고 로컬 `.env`에 `OPENAI_API_KEY`를 설정한다.

```sh
uv run --locked --env-file .env python -m scripts.evaluate \
  --cases eval/dev.json --settings configs/team-a-answer-eval-settings.json \
  --factory src.evaluation.answer_experiments.answer_evaluation_runtimes:create_a_runtime \
  --output-dir "results/local/team-a-$(date -u +%Y%m%dT%H%M%SZ)"
```

외부 API 없이 확인하려면 `uv run --locked python -m scripts.demo`를 실행한다. 합성 데모도 `summary.json`과 함께 같은 세 종류의 CSV를 만든다. 아래 링크는 2026년 11월 25일 팀 A 실행에서 보관한 실제 파일이다.

| 파일 | 한 행이 나타내는 단위 | 확인할 내용 |
| --- | --- | --- |
| [cases.csv](../eval/snapshots/2026-11-25T064832Z/cases.csv) | 평가 문항 하나 | 질문, 조건, 모범 답안, 허용 근거의 청크 ID. 이 기준 파일에는 별도로 관리한 채점 메모도 포함돼 있다. |
| [runs.csv](team-a/2026-11-25T064832Z/runs.csv) | 한 설정에서 실행한 문항 하나 | 원질문과 검색 질의, 실제 답변, 허용 근거·생성 입력·인용의 검색 순위, 시작 시각(UTC·한국 시각), 소요 시간과 버전 |
| [candidates.csv](team-a/2026-11-25T064832Z/candidates.csv) | 한 실행에서 검색한 청크 하나 | 원문, URL과 문서 내 위치, 검색 순위와 점수, 생성 입력과 최종 인용에서의 위치 |

문항과 실행은 `dataset_id`와 `case_id`로 연결하고, 실행과 검색 후보는 `run_id`로 연결한다. 자동 저장에서는 문항 내용을 정규화한 뒤 해시로 `dataset_id`를 만든다. 같은 문항으로 반복하면 폴더와 실행 시각이 달라도 데이터셋 ID가 같다. 위 기준 파일은 생성 시각을 데이터셋 ID로 사용했다. 기준 파일과 새 실행을 비교할 때는 `case_id`를 맞춘 뒤 질문·조건·정답 근거가 같은지 확인한다.

순위와 위치는 1부터 센다. 같은 청크가 여러 번 쓰이면 `candidates.csv`에는 처음 쓰인 위치가, `runs.csv`의 순위 목록에는 쓰인 순서대로 모든 항목이 남는다. 아래 예시에서 검색 2위 청크는 생성기에 첫 번째로 전달됐고 최종 답변에서는 인용되지 않았다.

```csv
run_id,rank,model_input_position,citation_position
example-run,2,1,
```

같은 문항으로 다시 평가하려면 [보관한 문항 JSON](../eval/snapshots/2026-11-25T064832Z/cases.json)을 `--cases`에 지정한다. [실행 원본 JSON](team-a/2026-11-25T064832Z/evaluation.json)에는 각 단계의 상태와 소요 시간이 남아 있다. 청킹 버전이 달라졌다면 문서와 원문 위치부터 대조한 뒤 새 청크 ID를 연결한다.
