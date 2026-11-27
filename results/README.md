# 실행 원본과 비교 결과

실행별로 질문, 검색 후보, 생성기에 전달된 청크, 답변과 인용, 소요 시간, 오류, 실행 설정과 자료 버전을 보관한다. 팀 A의 개발 문항 2개로 얻은 기준 데이터는 아래 CSV에서 확인할 수 있다. 최종 20문항의 구성별 비교는 [final-abc-2026-11-26](final-abc-2026-11-26/)(A/B/C 60건)과 [final-c-rewrite-2026-11-26](final-c-rewrite-2026-11-26/)(C+질문 다듬기 20건)에 있고 해석은 [보고서](../report.md) 7장에 있다. 개발셋 10문항 시험 실행은 [dev10-abc-2026-11-26](dev10-abc-2026-11-26/)이다.

`scripts.demo`는 합성 색인과 `summary.json`을, `scripts.evaluate`는 `evaluation.json`을 생성한다. 데모 경로는 각 실행 폴더의 `runs/<run_id>.json`에 개별 기록도 남긴다. 평가의 `--factory` 경로에서 개별 파일을 남기려면 연결 함수가 `create_runtime` 등으로 기록기를 붙여야 한다. 기록기가 없어도 정상 반환된 `RunRecord`는 `evaluation.json`에 포함된다. 평가 명령에 `--output-dir`를 지정할 때는 새 폴더를 사용하며, 기록기는 같은 실행 ID 파일을 덮어쓰지 않는다. 자세한 경로와 명령은 [인계 문서](../docs/handoff.md)를 따른다.

양석호가 인계한 실행 기록을 바탕으로 이명지는 검색 순위, 이정은은 프롬프트 변경 전후, 강성수는 답변·인용을 확인한다. 이승주는 청킹 변경의 영향과 화면에 표시되는 근거를 비교한다. [현재 역할표](../ROADMAP.md#업무-분담과-인계)

## 전처리 자료 검색·답변 실험 결과

[전처리 자료 질문별 결과표](testData.md)에서 저장소에 포함된 CSV 원본을 열 수 있다. 재현하려면 [검색 비교 명령](../README.md#dev-반영-후-답변과-지역-해석-검증)을 실행하고 `results/local/` 아래에 새 출력 폴더를 지정한다. 출력 폴더 안의 `vector/`, `ensemble/`, `answers/`에는 각각 `runs.csv`와 `candidates.csv`가 생긴다. 같은 실행의 두 파일은 `run_id`로 연결한다. `candidate_count`가 빈칸이면 후보 목록을 받지 못했고, `0`이면 검색을 마쳤지만 찾은 후보가 없다는 뜻이다.

`vector/`와 `ensemble/`에는 검색 순위와 소요 시간이 기록된다. `answers/`에는 함정 질문 3개에 근거를 직접 제공해 얻은 답변이 기록된다. 이 CSV들은 검색 비교 명령을 실행할 때 생성된다. 공통 런타임은 실행별 기록을 JSON으로 저장한다.

답변 작업 브랜치의 색상표 실험에서는 검색 결과 JSON과 그 결과를 사용한 답변 실행 JSON이 따로 생긴다. 답변 기록의 `model_input_chunk_ids`를 검색 순위와 대조하고 `response.citations`에서 실제 인용을 확인한다. 저장된 후보를 다시 사용한 답변 실행의 유형은 `fixed_evidence`다. [실행 명령과 판정 기준](../eval/README.md#색상표-개발-문항-실행)

최초 실패, 재시도와 변경 후 추가 실험은 별도로 남긴다. `RunRecord.duration_ms`는 기록 파일 저장 전까지의 파이프라인 시간이며 리라이트 시간을 포함한다. 실행 JSON에는 실행 전체의 토큰 사용량·API 비용 합계가 없다. Ragas 사후 평가 시간은 아래의 별도 채점 명령이 기록한다. 합성 데모는 `run_kind="demo"`로 기록하며 실제 검색/생성 결과와 구분한다.

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

| 파일                                                        | 한 행이 나타내는 단위        | 확인할 내용                                                                                                     |
| ----------------------------------------------------------- | ---------------------------- | --------------------------------------------------------------------------------------------------------------- |
| [cases.csv](../eval/snapshots/2026-11-25T064832Z/cases.csv) | 평가 문항 하나               | 질문, 조건, 모범 답안, 허용 근거의 청크 ID. 이 기준 파일에는 별도로 관리한 채점 메모도 포함돼 있다.             |
| [runs.csv](team-a/2026-11-25T064832Z/runs.csv)              | 한 설정에서 실행한 문항 하나 | 원질문과 검색 질의, 실제 답변, 허용 근거·생성 입력·인용의 검색 순위, 시작 시각(UTC·한국 시각), 소요 시간과 버전 |
| [candidates.csv](team-a/2026-11-25T064832Z/candidates.csv)  | 한 실행에서 검색한 청크 하나 | 원문, URL과 문서 내 위치, 검색 순위와 점수, 생성 입력과 최종 인용에서의 위치                                    |

문항과 실행은 `dataset_id`와 `case_id`로 연결하고, 실행과 검색 후보는 `run_id`로 연결한다. 자동 저장에서는 문항 내용을 정규화한 뒤 해시로 `dataset_id`를 만든다. 같은 문항으로 반복하면 폴더와 실행 시각이 달라도 데이터셋 ID가 같다. 위 기준 파일은 생성 시각을 데이터셋 ID로 사용했다. 기준 파일과 새 실행을 비교할 때는 `case_id`를 맞춘 뒤 질문·조건·정답 근거가 같은지 확인한다.

순위와 위치는 1부터 센다. 같은 청크가 여러 번 쓰이면 `candidates.csv`에는 처음 쓰인 위치가, `runs.csv`의 순위 목록에는 쓰인 순서대로 모든 항목이 남는다. 아래 예시에서 검색 2위 청크는 생성기에 첫 번째로 전달됐고 최종 답변에서는 인용되지 않았다.

```csv
run_id,rank,model_input_position,citation_position
example-run,2,1,
```

같은 문항으로 다시 평가하려면 [보관한 문항 JSON](../eval/snapshots/2026-11-25T064832Z/cases.json)을 `--cases`에 지정한다. [실행 원본 JSON](team-a/2026-11-25T064832Z/evaluation.json)에는 각 단계의 상태와 소요 시간이 남아 있다. 청킹 버전이 달라졌다면 문서와 원문 위치부터 대조한 뒤 새 청크 ID를 연결한다.

### 11월 25일 기준 실행과 새 실행 비교

문항을 비교할 때는 `question`, `conditions_json`, `reference_answer`, `allowed_chunk_ids_json`을 확인한다. 같은 문항과 검색 구성에서 실행별 `allowed_source_ranks_json`(허용 근거의 검색 순위), `model_input_ranks_json`(실제 생성 입력), `citation_ranks_json`(최종 인용)을 나란히 보면 검색 단계와 답변 단계의 변화를 구분할 수 있다. 예를 들어 기준 송파구 실행에서는 세 열이 각각 `[3]`, `[1,2,3,4,5]`, `[3,1]`이다. 실행 시각은 `started_at_utc` 또는 `started_at_kst`에서 확인한다.

자동 `runs.csv`의 `error_code`와 `failed_stage`는 문서 답변이 최종 실패했을 때 원인과 단계를 보여 준다. 예를 들어 모델이 깨진 JSON을 반환하면 `generation.invalid_draft`와 `generate`가 기록된다. 답변에 성공한 경우 둘 다 비어 있다. 과거 기록에 코드가 없으면 코드 칸은 비워 두며, 실행 기록 자체가 없으면 단계도 비어 있다. 답변은 성공했으나 질문 다듬기나 장소 조회가 실패한 경우는 원본 JSON의 개별 단계에서 확인한다.

기준 CSV의 `scoring_*`, `required_facts_json`, `checked_at`은 당시의 채점 자료이고, `git_base`, `factory_sha256`, `cases_json_sha256`은 당시 실행 입력의 출처다. 현재 채점 메모는 [개발 채점 자료](../eval/dev-scoring-notes.json)에서 `case_id`로 찾는다. 기준 실행의 프롬프트 해시는 `prompt_sha256`, 자동 저장한 실행에서는 `versions_json`의 `prompt` 값이다.

자동 `runs.csv`에서는 `configuration`으로 평가 구성을 구분하고 `run_kind`와 `retrieval_status`로 실행 유형과 검색 단계 상태를 확인한다. 자동 `candidates.csv`에는 `dataset_id`와 `configuration`도 있다. 11월 25일 기준 후보에서 같은 정보를 찾을 때는 `run_id`로 당시 `runs.csv`를 연결해 데이터셋과 검색 옵션을 확인한다.

기준 실행도 새 실행과 같은 열과 데이터셋 ID 규칙으로 읽으려면 저장소 루트에서 아래 명령을 실행한다. 보관된 문항·실행 JSON에서 CSV 세 개를 새 로컬 폴더에 만든다. 이 변환은 모델 호출 없이 실행되며, 기준 CSV 전용 열은 원래 파일에서 확인할 수 있다.

```sh
uv run --locked python - <<'PY'
import json
from pathlib import Path
from tempfile import mkdtemp

from src.evaluation.csv_export import write_evaluation_csv
from src.evaluation.runner import load_evaluation_cases

snapshot = "2026-11-25T064832Z"
cases = load_evaluation_cases(Path("eval/snapshots") / snapshot / "cases.json")
archive = Path("results/team-a") / snapshot / "evaluation.json"
records = json.loads(archive.read_text(encoding="utf-8"))
local = Path("results/local")
local.mkdir(parents=True, exist_ok=True)
output = Path(mkdtemp(prefix="team-a-baseline-", dir=local))
write_evaluation_csv(output, cases, records)
print(output)
PY
```

## 저장 답변의 Faithfulness 사후 평가

아래 명령은 새 디렉터리의 `scores.csv`에 시도×지표별 한 행을 쓴다. 기본 실행은 입력만 검증하고 점수를 비운다. `evaluation.json` 옆에 원래 실행의 `runs.csv`를 함께 둔다. 이 파일의 데이터셋 ID를 `cases.csv`와 대조하고 실행 ID와 문항 ID의 연결을 확인한다. 질문과 조건이 같아도 다른 데이터셋의 모범 답안에 점수가 귀속되는 것을 막기 위해서다. 이어서 `cases.csv`에서 문항 ID로 행을 찾아 실행 기록의 원래 질문·구·동·조건과 대조한다. 조건은 JSON 객체로 비교한다. 값이 다르면 해당 시도에 `input_error`와 원인을 남기고 다음 문항을 처리한다. 채점 입력은 기록된 질문·답변과 `model_input_chunk_ids` 순서로 후보 본문을 역참조한 목록이다. 이 ID는 생성 어댑터 경계의 기록이다. 모델 서버 수신 여부는 별도 확인이 필요하다.

```sh
stamp=2026-11-25T064832Z
uv run --locked python -m scripts.score_answers \
  --evaluation "results/team-a/$stamp/evaluation.json" \
  --cases-csv "eval/snapshots/$stamp/cases.csv" \
  --output-dir results/local/faithfulness-check
```

시간대가 없는 실행 시작 시각은 해당 실행의 `runs.csv`에 명시적인 UTC 시각이 있을 때만 복원한다. 시각을 확인할 수 없으면 채점 전에 입력 오류를 기록한다.

한 번의 채점에서 같은 `run_id`로 유효한 입력이 반복되면 첫 시도만 처리하고 뒤의 행에는 `duplicate_run_id`를 기록한다. 각 호출에 새 `evaluation_id`가 부여된다. `attempt_index`는 원본 배열의 1부터 시작하는 위치라서 반환된 실행 기록이 없는 행도 추적할 수 있다. `run_kind`로 고정 근거와 실제 검색 실행을 구분한다. 고정 근거 점수는 별도로 해석한다. `versions_json`은 생성 시점의 구성 버전이며 채점기 버전과 모델은 별도 열에 남는다. `scored_at_utc`는 평가 시도 종료 시각, `duration_ms`는 해당 시도 시간이다. `scored`의 0.0은 유효한 점수다. `no_score`(NaN·누락 등), `input_error`(근거 ID 등), `scorer_error`, `skipped`의 원인은 `reason`으로 확인한다.

채점기 오류는 점수를 비운다. 예를 들어 `judge_statements_http_429`는 진술 추출 중 받은 HTTP 429, `judge_verdicts_invalid_response`는 근거 대조 응답을 해석할 수 없었다는 뜻이다. `connection`과 `timeout`은 서버 수신 여부를 확정하지 않는다. 기존 결과에 남은 `judge_failed`만으로는 이 유형들을 구분할 수 없다.

### 실검색 A/B/C 점수 비교

같은 문항에 A/B/C가 각각 답하면 세 답변을 같은 Faithfulness 채점기로 평가한다. 각 점수는 그 답변의 `run_id`에 연결된다. 예를 들어 구성 이름이 `configured`이고 실제 검색 방식이 B이면, 그 점수는 B에 속한다. 점수표에서 다음 열을 확인한다.

| 열                                                   | 의미                                                                                  |
| ---------------------------------------------------- | ------------------------------------------------------------------------------------- |
| `reported_configuration`                             | 평가 시도에 적힌 구성 이름. 실행 기록을 저장하지 못했을 때도 시도를 추적하는 데 쓴다. |
| `configuration`                                      | 같은 실행의 `runs.csv`에 기록된 구성 이름. 평가 시도에 이름이 있으면 대조한다.        |
| `variant`, `rewrite_enabled`                         | 실행 시 명시한 검색 방식과 질문 다듬기 사용 여부. 실행 표에도 값이 있으면 대조한다.   |
| `comparison_eligible`, `comparison_exclusion_reason` | 기본 A/B/C 평균에 넣을 수 있는지와 제외 사유.                                         |

**기본 A/B/C 평균에는 `comparison_eligible=true`인 행만 넣는다.** 구성 이름을 대조할 수 있고, 검색 방식이 명시됐으며, 질문 다듬기를 끈 실제 검색 실행(`rag`)에서 `retrieve` 단계가 성공하고 숫자 점수를 얻어야 한다. 유효한 `0.0`은 건수와 평균에 포함한다.

- C에서 질문 다듬기를 켠 실행은 로드맵의 별도 실험이다. 개별 점수와 `rewrite_enabled=true`를 보존하며 기본 C 평균에서는 제외한다. 고정 근거·데모 실행, 검색 단계를 건너뛴 실행도 진단용 점수를 보존한다.
- 두 기록의 구성 이름, 검색 방식, 질문 다듬기 설정 또는 실행 유형이 충돌하면 해당 행은 채점 전 `input_error`가 된다. 검색 단계가 중복되거나 기록된 단계 상태가 실행 표와 다를 때도 마찬가지다. 답변을 채점하려는데 실행 표에는 실패로 기록돼 있으면 `run_status_mismatch`가 남는다. 다음 정상 행은 계속 처리한다.
- 11월 25일 팀 A 보관본에는 `runs.csv`의 `configuration` 열이 없다. 두 답변은 채점할 수 있지만 숫자 점수를 얻어도 `missing_run_configuration`으로 비교에서 제외한다. 원본에서 생략한 검색 방식이나 질문 다듬기 설정도 기본값으로 채워 집계하지 않는다. 이전 형식의 점수표를 비교하려면 보관본에서 새 점수표를 만든다.
- 저장된 실행 없음, 검증 전용 실행, 근거 ID 누락, 채점기 실패, NaN은 점수와 평균의 분모에서 빠진다. 해당 시도의 `reason`에서 원인을 확인한다.

아래 예시는 한 번의 평가에서 나온 `scores.csv`를 읽는다. 숫자 점수가 하나도 없는 방식에는 평균 대신 ‘—’를 표시한다. 방식별 건수나 문항이 다르면 어떤 문항이 빠졌는지 확인한 뒤 같은 문항과 채점 조건으로 비교한다.

```sh
python - results/local/faithfulness-smoke/scores.csv <<'PYTHON'
import csv
import sys
from statistics import mean

scores = {variant: [] for variant in ("A", "B", "C")}
with open(sys.argv[1], newline="", encoding="utf-8") as stream:
    for row in csv.DictReader(stream):
        if row["comparison_eligible"] == "true":
            scores[row["variant"]].append(float(row["score"]))

for variant, values in scores.items():
    average = f"{mean(values):.3f}" if values else "—"
    print(f"{variant}  {len(values)}건  평균 {average}")
PYTHON
```

### 승인 후 실제 모델로 한 문항 채점

승인 후 한 문항의 모델 스모크를 실행하려면 위 명령에서 새 출력 폴더를 지정하고 `--case-id p04-colors-trick --judge`를 추가한다. 팀 고정 판단 모델인 `gpt-6-luna`에 접근할 수 있는 `OPENAI_API_KEY`가 필요하다. 저장된 질문·답변에서 진술을 추출하고, 진술이 있으면 생성 입력 근거로 지지 여부를 판정한다(답변 한 건당 최대 2회, 자동 재시도 0회). 팀 공통 옵션은 HTTP 리다이렉트를 따라가지 않는다. 예를 들어 근거 대조 중 308을 받으면 해당 답변은 빈 점수와 `judge_verdicts_http_308`로 기록한다. 검색·임베딩·답변 재생성은 호출하지 않는다. 필수 사실 충족은 스냅샷의 채점 메모와, 표시한 인용의 타당성은 인용한 원문과 각각 대조한다. [Ragas Faithfulness](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/faithfulness/)

### Answer Relevancy와 ID 기준 정밀도·재현율 사후 계산

저장된 실행 폴더(`runs.csv`, `candidates.csv`, `cases.csv`)에서 두 가지를 더 계산한다. 정의는 [문제와 평가 기준](../docs/problem.md)의 `answer_relevancy`, `context_precision_id_at_5`, `context_recall_id_at_5`다.

```sh
uv run --locked --env-file .env python -m scripts.score_relevancy results/<실행 폴더>
uv run --locked python -m src.evaluation.comparison results/<실행 폴더>
```

`score_relevancy`는 판정 모델과 임베딩을 호출하므로 비용이 든다. 2026-11-27 이전에 만든 `relevancy.csv`는 `run_id`를 `runs.csv`의 (case_id, configuration, rewrite_enabled)로 정확히 대응시켜 나중에 채워 넣었고(조합이 실행마다 하나뿐임을 확인), 채점 시각은 기록이 남아 있지 않아 `timestamp` 열이 없다. 시각을 지어내지 않으므로 이 파일들은 `upload_extra_scores`에 그대로 쓸 수 없고, 업로드하려면 새로 채점해야 한다. 실행 폴더에 `relevancy.csv`를 쓰며(`run_id`와 점수를 얻은 UTC 시각 `timestamp` 열 포함, 출력 파일은 호출 전에 먼저 만들어 실패해도 빈 파일을 남기지 않는다, 이미 있으면 호출 전에 중단하므로 보관된 결과 폴더에는 `--output`으로 새 경로를 지정한다), 되묻기와 정보 부족 안내도 채점하며 정보 부족 안내는 0.0으로 나오므로 `status` 열로 구분해 평균을 낸다. 한 행이 실패하면 `score`를 비우고 `error`에 오류 종류만 남긴다. `comparison`은 모델 호출 없이 구성별 평균과 표본 수를 출력하고, 허용 근거가 없는 문항은 평균과 표본 수에서 뺀다. 최종 20문항 결과와 해석은 [비교 보고서 7.6절](../report.md)에 있다.

### 진술별 Faithfulness 판정 확인

새 출력 폴더에서 `scripts.score_answers --judge`를 실행하면 `scores.csv`와 같은 위치에 `judgment-details.jsonl`이 생긴다. 실제 채점에 들어간 각 실행의 `model_input_chunk_ids`는 생성기에 넘긴 순서다. `statements`는 추출된 진술 목록이고 `verdicts`는 판단 모델이 돌려준 진술·지지 여부(1/0)·사유다. 두 목록은 각각 반환된 순서와 문구를 보존한다. 사유는 전체 근거에 대한 모델의 설명이다. 단계가 결과를 돌려주기 전에 실패하면 그 목록은 `null`, 반환한 항목이 없으면 `[]`로 기록한다. 기존 점수만 있는 평가에서는 당시 판정 사유를 복원할 수 없다.

팀 EC2로 상세를 전송할 때는 프로젝트 루트의 `.env`에 `LANGFUSE_BASE_URL`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`를 설정한다. 아래에서 `judged`는 다음 채점으로 새로 만든 결과 폴더 경로로 바꾼다.

```sh
uv run --locked --env-file .env python -m scripts.upload_scores \
  --scores judged/scores.csv --judgments judged/judgment-details.jsonl \
  --report judged/upload-1.csv --upload
```

팀 프로젝트에서 해당 trace를 연다. 실시간 추적을 켰다면 **rag-pipeline → faithfulness → Output**, 추적 없이 저장한 실행이라면 **archived-run → faithfulness → Output**에서 판정을 확인한다. `scorer_error`와 `no_score`는 확보한 상세만 올리고 숫자 점수는 건너뛴다. 재전송할 때 같은 두 입력 파일과 새 보고서명을 사용한다. `--judgments`를 생략하면 기존 메타데이터 전송 방식을 사용한다.

### 질문 실행 중 LangChain 추적

합성 질문도 UI에서 **실행(합성 데모)**를 고르면 `results/local/runs/<run_id>.json`에 질문·검색 후보·답변·인용이 저장된다. **예시 응답**은 미리 만든 샘플을 표시한다. 여러 문항을 `scripts.evaluate --cases`로 실행하면 지정한 출력 폴더에 `evaluation.json`, `cases.csv`, `runs.csv`, `candidates.csv`가 생긴다. 분석용 결과 파일로 다시 평가하려면 각 문항을 [평가 입력 형식](../eval/README.md)에 맞춰 준비한다.

질문 실행의 자동 추적은 기본값이 꺼짐이다. 팀 프로젝트에 모델 입출력(프롬프트와 근거 포함)을 보낼 실행에서만 `RAG_LANGFUSE_TRACE=1`을 설정한다. 예를 들어 기존 `uv run --locked --env-file .env python -m scripts.evaluate …` 명령 앞에 이 변수를 붙인다. 공용 채팅 어댑터가 요청별 콜백을 사용하므로 답변 생성과 C 재정렬을 같은 trace에서 확인할 수 있다. CLI는 로컬 결과를 쓴 뒤 추적 버퍼를 전송한다. 주소나 키 설정이 잘못되면 초기화 경고를 한 번 남기고 로컬 평가를 계속한다. 설정을 고친 후 새 프로세스에서 실행한다. `--demo`는 채팅 모델을 호출하지 않으므로 실행 trace에는 모델 토큰·비용이 없다. 실행 추적을 켜도 저장된 Faithfulness 점수는 아래 업로드 명령으로 따로 보낸다. 나중에 같은 `run_id`의 저장 답변을 채점해 올리면 실행과 판정을 같은 trace에서 조회할 수 있다.

모델 응답이 사용량을 제공하면 각 채팅 호출의 **Generation**에서 입력·출력 토큰을 확인할 수 있다. Langfuse는 기록된 모델 이름과 적용 시점에 맞는 단가로 비용을 계산한다. 저장 파일만 업로드한 과거 실행, 질의 임베딩, 별도 Ragas 채점 호출의 토큰은 이 콜백의 집계 범위 밖이다. [Langfuse 토큰·비용 안내](https://langfuse.com/docs/observability/features/token-and-cost-tracking)

### 승인 후 Langfuse 업로드

운영 중인 EC2에 접속할 때는 [팀 Langfuse 설정](../docs/TEAM-SETUP.md#팀-langfuse-설정)을 따른다. 아래 예시는 점수만 전송할 때 사용한다.

점수가 저장된 후 별도 명령으로 실행한다. 기본은 네트워크 없는 점검이다. `--report`에는 매 시도마다 새 파일을 지정한다. 정상 상태로 기록된 미채점 행은 건너뛴다. 알 수 없는 상태나 상태와 점수가 모순되는 행은 실패로 기록한다. 예전에 만든 CSV에 같은 평가·실행·지표로 유효한 점수가 여러 개 있으면 첫 행만 전송 대상으로 삼는다. 뒤의 행은 `duplicate_score_identity`로 기록한다. 같은 CSV 전체를 새 보고서로 다시 전송하는 동작은 지원한다.

```sh
uv run --locked python -m scripts.upload_scores \
  --scores results/local/faithfulness-smoke/scores.csv \
  --report results/local/faithfulness-smoke/preview.csv
```

실서버 스모크는 앞 절에서 승인받아 채점한 한 문항의 CSV로 진행한다. 대상 프로젝트의 HTTPS `LANGFUSE_BASE_URL`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`를 환경변수로 설정하고 위 명령에 `--upload`를 붙인다. 보고서 이름은 `upload-1.csv`로 바꾼다. 업로더는 대상 프로젝트에서 해당 trace의 논리 루트를 조회한다. 루트가 하나면 판정 상세를 그 아래에 붙이고, 점수만 올릴 때는 점수만 POST한다. 실시간 추적 기록이 없는 보관본은 실행 시작 시각을 담은 루트를 만든다. 상세 업로드에서는 판정 span도 한 건 보낸다. span은 실행 시점을 표시하는 길이 0의 기록이다. 본문은 파생 ID·고정 이름·시각·실행 유형·점수로 구성한다. 인증은 HTTPS Basic 헤더를 사용한다. [Langfuse OTLP 규격](https://github.com/langfuse/langfuse/blob/main/fern/apis/server/definition/opentelemetry.yml) · [점수 API 스키마](https://github.com/langfuse/langfuse/blob/main/fern/apis/server/definition/scores.yml)

보고서의 `trace_status`와 `score_status`에서 각 단계의 접수 상태를 확인한다. 실패하면 종료 코드 1을 반환한다. 재시도할 때 같은 입력 파일과 새 보고서명을 사용한다.

- 업로드 CLI는 `scores.csv` 옆의 `langfuse-spans.sqlite3`에 프로젝트별 실행·판정 span ID와 접수 상태를 저장한다. 채점 결과 폴더를 옮길 때 이 파일도 보존한다. 이전에 접수한 루트가 논리 루트 조회에 아직 보이지 않으면 점수를 보류한다. 서버에서 확인한 루트와 접수된 상세 span은 재사용하므로 점수만 실패한 행은 원래 점수 ID·이름·`scored_at_utc`로 점수만 재전송한다. 업로드 시각은 `upload_attempted_at_utc`에서 확인한다.
- 새 실행의 `langfuse_project`는 인증된 서버가 반환한 `project:<ID>`다. 같은 프로젝트의 API 키를 교체해도 같은 ID를 사용한다. 이전 기록과 프로젝트 조회 실패 시의 기록에는 주소·공개 키 해시가 남는다. 현재 키나 같은 폴더의 접수 기록 DB로 확인할 수 없는 과거 해시는 귀속 미확인으로 처리한다. 이때 서버에 루트가 없으면 자동 생성과 강제 복구를 보류한다. 같은 프로젝트에서 루트가 아직 보이지 않거나 조회가 불완전하거나 루트가 여러 개면 해당 행은 `trace_unconfirmed`로 남고 전송을 보류한다. 이 열이 없는 예전 보관본을 실시간 추적했다면 대시보드에서 실행 루트가 보인 뒤 업로드한다. [Langfuse 논리 루트 규칙](https://langfuse.com/docs/api-and-data-platform/features/public-api#logical-root-observations)
- 타임아웃 등으로 span 접수가 불명확하면 다음 시도에서 서버를 조회한다. 해당 span이 보이면 점수 전송으로 넘어간다. 조회 오류나 아직 보이지 않는 span은 `trace_unconfirmed`로 남긴다. 서버 수집 큐가 비었고 이전 업로드 프로세스가 끝났음을 확인한 뒤, 같은 명령에 `--retry-missing-spans`를 추가하면 다시 조회해 누락된 span만 보낸다.
- 실서버에서는 보고서의 `trace_id`와 `score_id`로 표시된 값과 채점 날짜를 확인한다. [Langfuse 수집 및 점수 교체 규칙](https://langfuse.com/faq/all/tracing-data-updates)

#### 비교 패널에서 검색 방식 확인

팀 EC2의 `events_only` 모드에서는 `GET /api/public/v3/scores?name=faithfulness&environment=rag&fields=subject`로 점수를 읽는다. `subject.kind`가 `trace`인 점수는 `subject.id`가 trace ID다. `GET /api/public/v2/observations`에 `traceId`, `isRootObservation=true`, `fields=core,basic,metadata`를 지정해 같은 실행의 루트를 찾는다. 목록은 마지막 커서까지 확인한다. [Langfuse Public API](https://langfuse.com/docs/api-and-data-platform/features/public-api)

검색 방식은 루트의 `metadata.variant`에서 읽는다. 실시간 실행은 `rag-pipeline`, 보관본 업로드는 새 `archived-run`에 기록한다. 보관본에는 공통 채점기가 만든 `scores.csv`의 명시적 A/B/C만 복사한다. 열이 없거나 값이 비었거나 다른 값이면 미확인으로 둔다. 이미 접수된 루트는 재사용하므로 같은 점수를 다시 올려도 과거의 빈 값이 채워지지 않는다. 서버 루트와 채점 CSV 양쪽에 A/B/C 값이 있고 서로 다르면 해당 행은 `root_variant_mismatch`로 기록한다. 점수와 상세는 전송하지 않으므로 원본 실행의 `run_id`와 `options.variant`를 대조한 뒤 재시도한다.

공식 비교는 `scores.csv`에서 동일 데이터셋·문항과 `comparison_eligible=true`를 확인한 실행을 기준으로 한다. 루트가 여러 개이거나 검색 방식을 확인할 수 없는 점수는 따로 표시한다. 원본 `run_id`로 귀속을 확인하기 전에는 그룹별 평균에서 제외한다.

#### 실시간 전송이 끝내 실패한 실행 한 건 복구

실행을 보낸 프로세스가 끝났고 서버 수집 큐에도 대기 중인 전송이 없음을 확인한다. `scores.csv`에서 대상 `run_id`를 복사해 아래 `RUN_ID` 자리에 넣는다. 일반 업로드는 같은 프로젝트에서 실시간 루트가 보이지 않으면 계속 보류한다.

```sh
uv run --locked --env-file .env python -m scripts.upload_scores \
  --scores judged/scores.csv --judgments judged/judgment-details.jsonl \
  --recover-missing-root RUN_ID --report judged/recovery-1.csv --upload
```

이 명령은 지정한 실행의 행만 처리한다. 서버에 루트가 하나면 기존 루트에 연결하고, 정상 조회 결과가 0개면 저장된 실행 시각으로 `archived-run`을 만든다. 조회 오류·불완전한 조회·복수 루트는 `trace_unconfirmed`로 남는다. 점수만 복구할 때는 `--judgments`를 생략한다. 복구한 보관본에는 저장된 점수와 선택한 판정 상세가 표시된다. 유실된 실시간 모델 호출의 토큰·비용은 복원할 수 없다.

재시도할 때는 같은 입력 파일·실행 ID·상태 DB를 사용하고 `--report`에 새 파일명을 지정한다. 점수만 실패했다면 기존 루트와 판정 상세는 재전송하지 않는다. 복구 중 보낸 **span 자체의 접수**도 불명확하면 위의 `--retry-missing-spans` 절차를 따른다.

### 기존 실행에 팀 실험 점수 연결

이미 계산한 답변 관련성과 ID 기반 검색 지표는 `scripts.upload_extra_scores`로 연결한다. 모델 호출이나 Evaluators 템플릿 설정은 필요 없다. 조회할 실행마다 같은 실험에서 내보낸 `cases.csv`, `runs.csv`, `candidates.csv`와 원래 점수 JSON을 준비한다. 팀 공통 실행은 `run_id`로 trace ID를 계산하며, 다른 도구에서 발급한 ID는 실행 원본의 `trace_id` 열로 연결한다.

입력 JSON은 행 배열이다. 각 행은 `traceId`, `name`, `value`(0~1 숫자), `timestamp`(원래 채점 시각, UTC)를 담는다. `answer_relevancy` 행의 `comment`에는 사용한 채점 방법과 척도를 적는다. 보류 안내를 평가한 경우 원본 응답 상태도 전송 설명에 추가된다. `dataType`은 생략하거나 `NUMERIC`으로 지정한다. `environment`를 지정하면 실행 원본과 일치해야 한다. 전달받은 파일의 구조가 다르면 원본을 보존하고 복사본에서 필드를 매핑한다. 원래 평가 결과나 시각이 없으면 임의로 채우지 않는다.

각 실행에서 `context_precision_id_at_5`와 `context_recall_id_at_5`는 원본의 상위 5개와 허용 ID로 계산해 대조한다. 허용 근거가 없으면 두 행을 생략한다. 정상 검색에서 후보가 0개이고 허용 근거가 있으면 재현율은 0이고 정밀도 행은 생략한다. 답변 관련성은 이미 산출한 값을 사용하므로 채점 방법과 보류 답변을 평균에 포함할지는 실험별로 확인한다.

```bash
uv run --locked python -m scripts.upload_extra_scores \
  --preview results/local/langfuse-extra-scores-preview.json \
  --archive results/local/실험원본 --expected-traces 4
```

추가 점수를 쓰는 모든 팀원은 `.env`의 `RAG_SCORE_LEDGER_DSN`에 **같은 팀용 PostgreSQL 데이터베이스와 스키마**를 지정한다. 담당자가 발급한 직접 연결 또는 세션 풀링 주소를 사용한다. 프로젝트 잠금이 전송이 끝날 때까지 같은 DB 세션에 유지되어야 하므로 트랜잭션 풀링 주소는 사용할 수 없다. 전송 계정은 해당 스키마에서 최초 테이블 생성과 이후 조회·삽입·갱신이 가능해야 한다. 첫 실행이 `rag_extra_score_ledger`를 만든다. 연결 문자열에는 비밀번호가 포함될 수 있으므로 저장소에 올리지 않는다. 로컬 검증과 `--check`에는 이 설정이 필요 없다.

같은 프로젝트의 업로드는 DB 잠금으로 직렬화한다. POST 직전에 점수 ID, 원래 값·설명·시각을 보존한다. 이미 접수한 점수가 조회에 아직 보이지 않으면 대기 건수로 표시한다. 응답 유실 후에는 동일 입력만 재시도할 수 있다. 서버에 미반영된 시도와 충돌하면 전체 배치의 새 전송을 중단한다. 팀에서 전송기를 교체할 때는 이전 버전이 보낸 점수의 수집을 먼저 확인한다. 이 공용 기록을 경유한 업로드끼리 충돌을 방지할 수 있다.

기본 실행은 오프라인 검증이다. 같은 명령에서 `uv run --locked --env-file .env`를 사용하고 끝에 `--check`를 붙이면 팀 프로젝트를 읽기만 한다. 원본과 귀속을 확인한 뒤 `--upload`로 누락 점수만 전송한다. 충돌이나 누락된 실행이 있으면 전송 전에 중단한다. 접수 후 같은 입력으로 `--check`를 실행해 서버 일치 건수와 미등록 0개를 확인한다. 부분 접수 후에는 기존 파일의 시각과 내용을 유지해 재시도한다. 합성 실험 4건의 결과는 최종 평가 80건과 따로 집계한다.

#### 접수 후에도 조회되지 않는 추가 점수 한 건 복구

1. 같은 파일로 `--check`를 실행한다. 미등록 행에 표시된 점수 ID·지표명·trace ID를 확인한다. 이 조회에는 공용 DB가 필요 없다.
2. 같은 명령의 `--check`를 `--recover-score-id <점수 ID>`로 바꾼다. CLI는 현재 프로젝트의 공용 원장과 서버를 대조하고, 미등록이면 마지막 복구 상태와 확인 번호를 출력한다. 서버에는 점수를 보내지 않는다. 처음 이 기능을 사용하면 공용 DB에 `rag_extra_score_recovery` 테이블을 만든다.
3. EC2 운영 담당자가 해당 전송의 수집 작업이 종료됐으며 대기·실행·재시도 중인 작업이 없는지 확인한다. 작업 진행 상태를 확인할 권한이나 기록이 없으면 여기서 대기한다. `--check`의 미등록 건수만으로는 큐 처리가 끝났는지 알 수 없다.
4. 큐 처리가 끝났는데도 미등록이라면 2번 명령 끝에 `--queue-drained <확인 번호>`를 붙인다. CLI가 잠금 안에서 실행 귀속과 정확한 점수 ID를 다시 조회한 뒤, 공용 원장의 최초 값·설명·시각으로 그 한 건만 전송한다. 이미 반영된 점수는 추가 전송 0건으로 끝난다.
5. `복구 접수`를 확인한 뒤 같은 파일로 `--check`를 다시 실행한다. 대상 ID가 미등록 목록에서 사라지고 서버 일치 건수가 늘었는지 확인한다. 한 건만 확인하려면 2번 명령에서 `반영 확인`을 확인한다. 거절·응답 유실·프로세스 중단이 발생하면 2번부터 확인한다. 직전 시도의 확인 번호는 다시 사용할 수 없다.

복구는 원장에 최초 접수가 기록된 점수에 적용한다. 프로젝트·실행·검색 방식·점수 ID 또는 원래 입력을 확인할 수 없으면 전송을 중단한다. 동일한 지표명과 값이어도 서버에 다른 점수 ID가 있으면 충돌로 표시한다.

## 결과 폴더 목록 (2026-11-27 기준)

| 폴더                                                                             | 내용                                                                                 | 보고서                 |
| -------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ | ---------------------- |
| `dev10-abc-2026-11-26/`                                                          | 개발셋 A/B/C 실행                                                                    | 4장                    |
| `final-abc-2026-11-26/`, `final-c-rewrite-2026-11-26/`                           | 최종 20문항 공식 실행(A/B/C 60건, C+질문 다듬기 20건)과 채점                         | 7장                    |
| `faithfulness-final-abc-2026-11-26/`, `faithfulness-final-c-rewrite-2026-11-26/` | 같은 답변의 Faithfulness 사후 채점                                                   | 7.6                    |
| `errata-v07-2026-11-27/`, `errata-d10-2026-11-27/`                               | 문항 결함 정정판 문항(v07, d10)의 재실행·채점. v06은 재분류만 하고 재실행하지 않았다 | 7.4                    |
| `posthoc-final-abc-2026-11-27/`, `posthoc-final-abc-v2-2026-11-27/`              | 표 행 임베딩 입력 v1·v2 색인으로 같은 최종 문항을 사후 재실행                        | 8.1                    |
| `embed-input-exp-2026-11-27/`, `embed-input-exp-v2-2026-11-27/`                  | 표 행 임베딩 입력 실험(14문항+개발셋 8) v1·v2                                        | 8                      |
| `repro-clone-2026-11-26/`                                                        | 새 클론에서 수행한 재현                                                              | `docs/reproduction.md` |
| `chunking/`, `evidence-trick-comparison/`, `team-a/`, `testData.md`              | 청킹 기준선, 함정 질문, 초기 개발 실험                                               | 3~4장                  |
| `local/`                                                                         | Git에서 제외된 로컬 산출물(대용량 색인 등)                                           | -                      |
