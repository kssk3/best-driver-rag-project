# 실행 원본과 비교 결과

실행별 디렉터리에 설정과 자료 버전, 요청과 후보, 실제 생성 입력 ID, 답변과 인용, 시간과 오류를 보존한다. 공통 파이프라인과 `RunRecorder`의 로컬 JSON 기록을 구현했으며, 합성 데모/CLI 결과는 `local/`에 생성한다. 실제 팀 구성의 품질 평가 결과와 제출용 비교 보고서는 아직 없다.

`scripts.demo`는 합성 색인과 `summary.json`을, `scripts.evaluate`는 `evaluation.json`을 생성한다. 데모 경로는 각 실행 폴더의 `runs/<run_id>.json`에 개별 기록도 남긴다. 평가의 `--factory` 경로에서 개별 파일을 남기려면 연결 함수가 `create_runtime` 등으로 기록기를 붙여야 한다. 기록기가 없어도 정상 반환된 `RunRecord`는 `evaluation.json`에 포함된다. 평가 명령에 `--output-dir`를 지정할 때는 새 폴더를 사용하며, 기록기는 같은 실행 ID 파일을 덮어쓰지 않는다. 자세한 경로와 명령은 [인계 문서](../docs/handoff.md)를 따른다.

양석호가 인계한 실행 기록을 바탕으로 이명지는 검색 순위, 이정은은 프롬프트 변경 전후, 강성수는 답변·인용을 확인한다. 이승주는 청킹 변경의 영향과 화면에 표시되는 근거를 비교한다. [현재 역할표](../ROADMAP.md#업무-분담과-인계)

## 전처리 자료 검색·답변 실험 결과

[전처리 자료 질문별 결과표](testData.md)에서 저장소에 포함된 CSV 원본을 열 수 있다. 재현하려면 [검색 비교 명령](../README.md#dev-반영-후-답변과-지역-해석-검증)을 실행하고 `results/local/` 아래에 새 출력 폴더를 지정한다. 출력 폴더 안의 `vector/`, `ensemble/`, `answers/`에는 각각 `runs.csv`와 `candidates.csv`가 생긴다. 같은 실행의 두 파일은 `run_id`로 연결한다. `candidate_count`가 빈칸이면 후보 목록을 받지 못했고, `0`이면 검색을 마쳤지만 찾은 후보가 없다는 뜻이다.

`vector/`와 `ensemble/`에는 검색 순위와 소요 시간이 기록된다. `answers/`에는 함정 질문 3개에 근거를 직접 제공해 얻은 답변이 기록된다. 이 CSV들은 검색 비교 명령을 실행할 때 생성된다. 공통 런타임은 실행별 기록을 JSON으로 저장한다.

답변 작업 브랜치의 색상표 실험에서는 검색 결과 JSON과 그 결과를 사용한 답변 실행 JSON이 따로 생긴다. 답변 기록의 `model_input_chunk_ids`를 검색 순위와 대조하고 `response.citations`에서 실제 인용을 확인한다. 저장된 후보를 다시 사용한 답변 실행의 유형은 `fixed_evidence`다. [실행 명령과 판정 기준](../eval/README.md#색상표-개발-문항-실행)

최초 실패, 재시도와 변경 후 추가 실험은 별도로 남긴다. `RunRecord.duration_ms`는 기록 파일 저장 전까지의 파이프라인 시간이며 리라이트 시간을 포함한다. 현재 토큰 사용량, API 비용과 Ragas 사후 평가 시간은 자동 수집하지 않는다. 합성 데모는 `run_kind="demo"`로 기록하며 실제 검색/생성 결과와 구분한다.

이 폴더 전체를 Git에서 제외하지 않는다. 제출용 기록은 비밀값과 공유 가능 여부를 검토해 포함하며, 큰 기록은 관리 위치, 버전과 접근 방법을 남긴다. 로컬 실험용 `local/`은 제외한다. [평가 기준](../docs/problem.md)을 기준으로 비교하며 결과를 검색 색인에 넣지 않는다.

## Automatic evaluation CSVs

Running `python -m scripts.evaluate` with `--demo` or `--factory` writes `cases.csv`, `runs.csv`, `candidates.csv` and `evaluation.json` into the specified `--output-dir`. Use a new directory for each run. For example, this command uses the Team A settings and a UTC timestamp in the folder name.

```sh
uv run --locked --env-file .env python -m scripts.evaluate \
  --cases eval/dev.json --settings configs/team-a-answer-eval-settings.json \
  --factory src.evaluation.answer_experiments.answer_evaluation_runtimes:create_a_runtime \
  --output-dir "results/local/team-a-$(date -u +%Y%m%dT%H%M%SZ)"
```

The all-in-one synthetic demo, `python -m scripts.demo`, writes the same three CSV files alongside its `summary.json`. The links below open the previously prepared Team A snapshot and illustrate each table.

| File | One row represents | Use |
| --- | --- | --- |
| [cases.csv](../eval/snapshots/2026-11-25T064832Z/cases.csv) | One evaluation question | Read the question, conditions, reference answer and allowed chunk IDs. The linked snapshot also includes separately maintained scoring notes. |
| [runs.csv](team-a/2026-11-25T064832Z/runs.csv) | One question in one run configuration | Compare the original and search queries, actual answer, retrieval and citation ranks, timestamps, duration and versions. |
| [candidates.csv](team-a/2026-11-25T064832Z/candidates.csv) | One retrieved chunk in a run | Inspect the source text, URL, document location, rank, score, and positions in the generator input and final citations. |

Join cases and runs on `dataset_id` and `case_id`, then join candidates on `run_id`. Automatic exports derive `dataset_id` from the normalized evaluation cases, so repeated runs with the same cases can be compared across folders. The linked historical snapshot used a timestamp as its dataset ID. Match its case IDs and verify the case content when comparing it with an automatic export.

Positions start at 1. If a factory uses the same chunk more than once, the candidate row gives its first position. The ordered rank arrays in `runs.csv` include every occurrence. In the illustrative row below, the second search result was first in the generator input and was omitted from the final citations.

```csv
run_id,rank,model_input_position,citation_position
example-run,2,1,
```

Read the [frozen cases JSON](../eval/snapshots/2026-11-25T064832Z/cases.json) with the evaluation CLI. Retain its [evaluation JSON](team-a/2026-11-25T064832Z/evaluation.json) for full run records and stage timings. For comparisons across chunking versions, match sources by document and original location before mapping the new chunk IDs.
