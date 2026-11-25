# 실행 원본과 비교 결과

실행별로 질문, 검색 후보, 생성기에 전달된 청크, 답변과 인용, 소요 시간, 오류, 실행 설정과 자료 버전을 보관한다. 팀 A의 개발 문항 2개로 얻은 기준 데이터는 아래 CSV에서 확인할 수 있다. 최종 20문항에 대한 구성별 비교는 후속 작업이다.

`scripts.demo`는 합성 색인과 `summary.json`을, `scripts.evaluate`는 `evaluation.json`을 생성한다. 데모 경로는 각 실행 폴더의 `runs/<run_id>.json`에 개별 기록도 남긴다. 평가의 `--factory` 경로에서 개별 파일을 남기려면 연결 함수가 `create_runtime` 등으로 기록기를 붙여야 한다. 기록기가 없어도 정상 반환된 `RunRecord`는 `evaluation.json`에 포함된다. 평가 명령에 `--output-dir`를 지정할 때는 새 폴더를 사용하며, 기록기는 같은 실행 ID 파일을 덮어쓰지 않는다. 자세한 경로와 명령은 [인계 문서](../docs/handoff.md)를 따른다.

양석호가 인계한 실행 기록을 바탕으로 이명지는 검색 순위, 이정은은 프롬프트 변경 전후, 강성수는 답변·인용을 확인한다. 이승주는 청킹 변경의 영향과 화면에 표시되는 근거를 비교한다. [현재 역할표](../ROADMAP.md#업무-분담과-인계)

## 전처리 자료 검색·답변 실험 결과

[전처리 자료 질문별 결과표](testData.md)에서 저장소에 포함된 CSV 원본을 열 수 있다. 재현하려면 [검색 비교 명령](../README.md#dev-반영-후-답변과-지역-해석-검증)을 실행하고 `results/local/` 아래에 새 출력 폴더를 지정한다. 출력 폴더 안의 `vector/`, `ensemble/`, `answers/`에는 각각 `runs.csv`와 `candidates.csv`가 생긴다. 같은 실행의 두 파일은 `run_id`로 연결한다. `candidate_count`가 빈칸이면 후보 목록을 받지 못했고, `0`이면 검색을 마쳤지만 찾은 후보가 없다는 뜻이다.

`vector/`와 `ensemble/`에는 검색 순위와 소요 시간이 기록된다. `answers/`에는 함정 질문 3개에 근거를 직접 제공해 얻은 답변이 기록된다. 이 CSV들은 검색 비교 명령을 실행할 때 생성된다. 공통 런타임은 실행별 기록을 JSON으로 저장한다.

답변 작업 브랜치의 색상표 실험에서는 검색 결과 JSON과 그 결과를 사용한 답변 실행 JSON이 따로 생긴다. 답변 기록의 `model_input_chunk_ids`를 검색 순위와 대조하고 `response.citations`에서 실제 인용을 확인한다. 저장된 후보를 다시 사용한 답변 실행의 유형은 `fixed_evidence`다. [실행 명령과 판정 기준](../eval/README.md#색상표-개발-문항-실행)

최초 실패, 재시도와 변경 후 추가 실험은 별도로 남긴다. `RunRecord.duration_ms`는 기록 파일 저장 전까지의 파이프라인 시간이며 리라이트 시간을 포함한다. 토큰 사용량과 API 비용은 자동 수집하지 않는다. Ragas 사후 평가 시간은 아래의 별도 채점 명령이 기록한다. 합성 데모는 `run_kind="demo"`로 기록하며 실제 검색/생성 결과와 구분한다.

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

아래 명령은 새 디렉터리의 `scores.csv`에 시도×지표별 한 행을 쓴다. 기본 실행은 입력만 검증하고 점수를 비운다. 같은 스냅샷의 `cases.csv`에서 문항 ID로 행을 찾아 실행 기록의 원래 질문·구·동·조건과 대조한다. 조건은 JSON 객체로 비교한다. 값이 다르면 해당 시도에 `input_error`와 원인을 남기고 다음 문항을 처리한다. 채점 입력은 기록된 질문·답변과 `model_input_chunk_ids` 순서로 후보 본문을 역참조한 목록이다. 이 ID는 생성 어댑터 경계의 기록이다. 모델 서버 수신 여부는 별도 확인이 필요하다.

```sh
stamp=2026-11-25T064832Z
uv run --locked python -m scripts.score_answers \
  --evaluation "results/team-a/$stamp/evaluation.json" \
  --cases-csv "eval/snapshots/$stamp/cases.csv" \
  --output-dir results/local/faithfulness-check
```

각 호출에 새 `evaluation_id`가 부여된다. `attempt_index`는 원본 배열의 1부터 시작하는 위치라서 반환된 실행 기록이 없는 행도 추적할 수 있다. `run_kind`로 고정 근거와 실제 검색 실행을 구분한다. 고정 근거 점수는 별도로 해석한다. `versions_json`은 생성 시점의 구성 버전이며 채점기 버전과 모델은 별도 열에 남는다. `scored_at_utc`는 평가 시도 종료 시각, `duration_ms`는 해당 시도 시간이다. `scored`의 0.0은 유효한 점수다. `no_score`(NaN·누락 등), `input_error`(근거 ID 등), `scorer_error`, `skipped`의 원인은 `reason`으로 확인한다.

승인 후 한 문항의 모델 스모크를 실행하려면 위 명령에서 새 출력 폴더를 지정하고 `--case-id p04-colors-trick --judge-model gpt-4o-mini`를 추가한다. 해당 모델에 접근할 수 있는 `OPENAI_API_KEY`가 필요하다. 저장된 질문·답변에서 진술을 추출하고, 진술이 있으면 생성 입력 근거로 지지 여부를 판정한다(문항당 논리 호출 1~2회). 검색·임베딩·답변 재생성은 호출하지 않는다. 필수 사실 충족은 스냅샷의 채점 메모와, 표시한 인용의 타당성은 인용한 원문과 각각 대조한다. [Ragas Faithfulness](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/faithfulness/)

### 승인 후 Langfuse 업로드

점수가 저장된 후 별도 명령으로 실행한다. 기본은 네트워크 없는 점검이다. `--report`에는 매 시도마다 새 파일을 지정한다. 입력 확인만 한 행과 숫자 점수가 없는 행은 건너뛴다.

```sh
uv run --locked python -m scripts.upload_scores \
  --scores results/local/faithfulness-smoke/scores.csv \
  --report results/local/faithfulness-smoke/preview.csv
```

실서버 스모크는 앞 절에서 승인받아 채점한 한 문항의 CSV로 진행한다. 대상 프로젝트의 HTTPS `LANGFUSE_BASE_URL`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`를 환경변수로 설정하고 위 명령에 `--upload`를 붙인다. 보고서 이름은 `upload-1.csv`로 바꾼다. 숫자 점수 1건당 시작 시각을 표시하는 OTLP span 하나와 숫자 점수 한 건을 각각 POST한다. span은 실행 시점을 표시하는 길이 0의 기록이다. 본문은 파생 ID·고정 이름·시각·실행 유형·점수로 구성한다. 인증은 HTTPS Basic 헤더를 사용한다. [Langfuse OTLP 규격](https://github.com/langfuse/langfuse/blob/main/fern/apis/server/definition/opentelemetry.yml) · [점수 API 스키마](https://github.com/langfuse/langfuse/blob/main/fern/apis/server/definition/scores.yml)

보고서의 `accepted`는 두 요청을 서버가 접수했다는 뜻이다. 실제 스모크에서는 `trace_id`와 `score_id`로 서버에 표시된 값과 날짜를 확인한다. 네트워크 오류로 접수가 불확실하면 `*_unconfirmed`, 부분 거절 등은 `*_not_accepted`로 기록하고 종료 코드 1을 반환한다. 원인을 확인한 뒤 같은 `scores.csv`와 새 보고서 이름으로 재시도한다. 같은 실행은 같은 trace ID와 span 시작 시각을 사용한다. 같은 평가·실행·지표는 같은 점수 ID와 이름을 사용하며, 요청의 `timestamp`에 원래 `scored_at_utc`를 보낸다. 업로드 시도 시각은 보고서의 `upload_attempted_at_utc`에만 남긴다. 서버에서 점수를 교체하는 조건은 ID·이름·timestamp의 날짜가 모두 같은 경우다. [Langfuse 점수 교체 규칙](https://langfuse.com/faq/all/tracing-data-updates)
