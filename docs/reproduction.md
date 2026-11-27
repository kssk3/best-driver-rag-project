# 재현 방법과 재실행 기록

팀 색인을 만들고, 확정된 평가 문항을 다시 실행해 [비교 보고서](../report.md)와 대조하는 절차다. 아래 예시는 저장소 루트에서 POSIX 셸로 실행한다.

## 준비

```sh
uv sync --locked
```

임베딩, 채팅, 모델 채점에 사용할 `OPENAI_API_KEY`를 로컬 `.env`에 설정한다. 키가 필요한 명령은 uv에 `--env-file .env`를 전달한다. 점수를 올리거나 Streamlit 비교 패널에서 조회하려면 [팀 Langfuse 설정](TEAM-SETUP.md#팀-langfuse-설정)도 필요하다. Windows에서는 Python을 실행하기 전에 셸 환경에 `PYTHONUTF8=1`을 설정한다. PowerShell에서는 `$env:PYTHONUTF8 = "1"`을 사용한다.

## 1. 색인 재생성

```sh
uv run --locked --env-file .env python -m scripts.prepare_data --bundle data/handoff/jungeun/ordinance-handoff-2026-11-24 --version v1 --output-dir data/processed/ordinance-v2-openai-small --openai-model text-embedding-3-small
```

색인을 새로 만들 때는 아직 없는 출력 폴더를 지정한다. 기존 팀 색인이 [청킹 기준선](../results/chunking/README.md)과 일치하면 재사용한다. 색인 준비와 화면 실행을 한 번에 하려면 `uv run --locked --env-file .env python -m scripts.run_chat`을 실행한다. 실행기는 기본 JSON 색인의 청크 지문(`chunks_sha256`)을 기준선과 대조한 뒤 Streamlit을 시작한다.

## 2. 평가 실행과 채점

확정된 [최종 20문항](../eval/test.json)으로 질문 다듬기를 끈 A/B/C를 실행한다. 튜닝에는 [개발 문항](../eval/dev.json)을 사용한다. 아래 명령은 현재 체크아웃에서 새 재현 결과를 만든다. 11월 26일 공식 결과는 [비교 보고서](../report.md)에서 확인한다.

```sh
run_tag=$(date +%Y%m%d-%H%M%S)
abc_dir="results/local/abc-off-$run_tag"
c_rewrite_dir="results/local/c-rewrite-on-$run_tag"

uv run --locked --env-file .env python -m scripts.evaluate \
  --cases eval/test.json --settings configs/abc-answer-eval-settings.json \
  --factory src.evaluation.answer_experiments.abc_runtimes:create_abc_runtimes \
  --output-dir "$abc_dir"
```

같은 셸에서 동일한 색인과 문항으로 질문 다듬기를 켠 C를 실행한다.

```sh
uv run --locked --env-file .env python -m scripts.evaluate \
  --cases eval/test.json --settings configs/team-c-rewrite-chat.json \
  --factory src.evaluation.answer_experiments.answer_evaluation_runtimes:create_a_catalog_runtime \
  --output-dir "$c_rewrite_dir"
```

두 실행이 끝나면 저장된 CSV로 문항별 실행 여부를 확인하고 청크 ID 기준 근거 정밀도와 재현율을 계산한다. `summarize_runs`에서 A·B·C 각각 `rewrite=false`로 20/20, C는 `rewrite=true`로 20/20인지 확인한다. 지표를 해석하기 전에 상태별 건수에서 실행 오류가 있는지 살핀다.

```sh
for run_dir in "$abc_dir" "$c_rewrite_dir"; do
  uv run --locked python -m scripts.summarize_runs "$run_dir/runs.csv"
  uv run --locked python -m src.evaluation.comparison "$run_dir"
done
```

아래 채점 명령은 외부 모델을 호출해 각 실행의 근거 충실도(Faithfulness), 답변 관련성(Answer Relevancy), 답변 품질을 계산한다.

```sh
for run_dir in "$abc_dir" "$c_rewrite_dir"; do
  uv run --locked --env-file .env python -m scripts.score_answers --judge \
    --evaluation "$run_dir/evaluation.json" --cases-csv "$run_dir/cases.csv" \
    --output-dir "${run_dir}-faithfulness"
  uv run --locked --env-file .env python -m scripts.score_relevancy "$run_dir"
  uv run --locked --env-file .env python -m scripts.score_quality \
    --runs "$run_dir/runs.csv" --candidates "$run_dir/candidates.csv" \
    --cases eval/test.json --grading eval/test-grading.json \
    --output-dir "${run_dir}-quality"
done
```

`score_quality`는 판정 모델을 호출하기 전에 문항 ID와 데이터셋 ID를 대조한다. 일부 문항만 다시 실행해 채점할 때는 `--allow-subset`을 지정한다. 정답 충족, 근거 적합, 근거 없음 대응을 `quality.csv`에 저장한다. 실행 한 건당 판정 모델을 최대 두 번 호출하며 읽을 수 없는 판정 응답은 점수 누락으로 기록한다. 모델 판정은 원문 근거와 대조한다. [호출 수와 비용 안내](../results/README.md)

## 3. 재실행 기록: 로컬 CSV가 기본, Langfuse는 켜고 올릴 때만

- **기본 증빙은 로컬 기록이다.** `scripts.evaluate`는 `runs.csv`, `candidates.csv`, `cases.csv`, `evaluation.json`을 남기고 채점기는 `quality.csv`(또는 `scores.csv`)를 남긴다. 공식 결과는 `results/final-*`에 있고, 실행별 기록은 실행 ID·구성·문서/색인/모델 버전을 담는다.
- **Langfuse 추적과 점수 업로드는 선택 사항이다.** `RAG_LANGFUSE_TRACE=1`을 켜면 실행 중 프롬프트와 근거 본문을 포함한 추적 기록을 전송한다. 채점 후 `scripts.upload_scores`로 저장된 점수와 판정 사유를 올린다. Streamlit 비교 패널에서 업로드된 점수를 조회할 수 있다. [팀 설정](TEAM-SETUP.md#팀-langfuse-설정) · [업로드와 조회 안내](../results/README.md#진술별-faithfulness-판정-확인)
- 저장소 안에서 확인할 수 있는 기록은 `results/`의 실행별 CSV다(Git에서 제외되는 `results/local/`은 제외).

## 사후 실험 재현(보고서 8장·8.1, 정오표)

이 실험은 공식 결과(`results/final-*`)를 바꾸지 않는다. 새 출력 폴더를 쓰고 OpenAI 키(`.env`)가 필요하며 외부 모델 호출 비용이 든다.

- 표 행 임베딩 입력 실험(8장): `uv run --locked --env-file .env python -m scripts.exp_embed_input --output-dir results/local/<새 폴더>` 이 명령은 변환 색인 `index-variant.json`과 `hits.csv`, `meta.json`을 만든다. 결과 예시는 `results/embed-input-exp-v2-2026-11-27/`다.
- 최종 문항 사후 재실행(8.1): 위 변환 색인을 `index_path`로 가리키는 설정 파일을 만들어 `uv run --locked --env-file .env python -m scripts.exp_posthoc_final --settings <설정> <scripts.evaluate와 같은 인자>`를 실행한다. 기본 색인을 가리키면 시작 전에 중단된다. 채점은 2장의 `score_quality`와 같다.
- 정오표(7.4): `eval/errata/`의 정정판 문항·채점 자료(`test-d10-corrected*.json` 등)를 `scripts.evaluate`와 `score_quality --grading`에 넘겨 같은 방식으로 실행한다. 결과 예시는 `results/errata-*/`다.

## 독립 환경 재현

작성자의 또 다른 PC에서 **새로 받은 클론**에 README의 명령만 따라 처음부터 돌려 본 기록이다. 팀원의 재현을 대신하지 않는다. 같은 PC·같은 OS라 다른 환경에서의 재현을 보장하지 않는다.

| 날짜       | 실행자                   | 환경                                                          | 커밋                                                      | 수행 |
| ---------- | ------------------------ | ------------------------------------------------------------- | --------------------------------------------------------- | ---- |
| 2026-11-26 | 작성자 PC의 임시 새 클론 | Windows 11, Python 3.13.14, `.env` 없이 OS 환경변수의 키 사용 | `b49f59c`(브랜치 `feature/seungju/eval-sets`를 로컬 클론) | 아래 |

1. `uv sync --locked`: 7초(캐시된 패키지), `python --version` 3.13.14. [측정]
2. README의 `scripts.prepare_data`(`--openai-model text-embedding-3-small`): 18초, 543청크. 청킹 기준선 지문이 일치하고 청크 ID 집합이 원본 색인과 같다. 색인 `index_id`는 원본과 달랐다(재생성할 때마다 달라지는 값으로 보이며 원인은 확인하지 않았다). 검색 결과에는 영향이 없었다. [측정]
3. 대표 질문 5개(정상 3, 조건 구분 1, 근거 없음 1, 한계 1: `test-d06`, `test-d08`, `test-v03`, `test-n01`, `test-v01`)를 A/B/C로 15건 실행했다. 질문은 최종 20문항에서 골랐고 공식 60건과 섞지 않는 **별도 재현 실행**이다. 결과: 15건 모두 **상태와 정답 청크 순위가 원본과 같았다.** 답변은 문장이 조금 달랐고(예: 현금 교환 안내의 표현) 금액·구간·정보 부족 안내 같은 핵심 사실은 같았다. 응답 시간은 평균 A 1.6초, B 1.8초, C 5.0초로 원본과 비슷했다. [측정]
4. 원본은 [results/repro-clone-2026-11-26/](../results/repro-clone-2026-11-26/)(`runs.csv`, `candidates.csv`, `cases.csv`, `evaluation.json`)에 있다.

**하지 않은 것**: Streamlit 화면과 `scripts.run_chat`, 채점(`score_answers`, `score_quality`), 테스트 실행, Windows 아닌 OS, `.env` 파일을 쓰는 경로. 타인 재현에서는 이 중 화면 실행과 `PYTHONUTF8` 없이 도는 Windows 한국어 환경(채점 테스트가 `cp949` 오류)을 우선 확인해야 한다.
