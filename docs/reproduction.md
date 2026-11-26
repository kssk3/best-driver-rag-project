# 재현 방법과 재실행 기록

다른 팀원이 README만 보고 색인을 만들고, 같은 질문으로 평가를 다시 돌려 결과를 대조하는 절차다. 비밀값(`.env`, 키)은 저장소에 없으므로 각자 준비한다.

## 준비

```sh
uv sync --locked
```

`.env`에 `OPENAI_API_KEY`를 넣는다. Langfuse에 올릴 때만 `LANGFUSE_BASE_URL`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`가 더 필요하다([설정](TEAM-SETUP.md#팀-langfuse-설정)). `.env`는 uv가 자동으로 읽지 않으므로 아래 명령처럼 `--env-file .env`를 붙인다. Windows에서는 `PYTHONUTF8=1`을 앞에 둔다.

## 1. 색인 재생성

```sh
uv run --locked --env-file .env python -m scripts.prepare_data --bundle data/handoff/jungeun/ordinance-handoff-2026-11-24 --version v1 --output-dir data/processed/ordinance-v2-openai-small --openai-model text-embedding-3-small
```

만들어진 청크가 청킹 기준선과 같은지는 [`results/chunking/`](../results/chunking/README.md)의 지문(`chunks_sha256`)과 `scripts.run_chat`이 대조한다. 화면까지 한 번에 띄우려면 `uv run --locked --env-file .env python -m scripts.run_chat`을 쓴다. 색인이 없으면 먼저 만든다.

## 2. 평가 실행과 채점

개발 문항(`eval/dev.json`)과 최종 문항(`eval/test.json`)은 [평가셋 안내](../eval/README.md)를 따른다. 질문 다듬기를 끈 A/B/C를 같은 조건으로 실행한다.

```sh
uv run --locked --env-file .env python -m scripts.evaluate --cases eval/test.json --settings configs/abc-answer-eval-settings.json --factory src.evaluation.answer_experiments.abc_runtimes:create_abc_runtimes --output-dir results/local/<새 출력 폴더>
uv run --locked --env-file .env python -m scripts.score_answers --judge --evaluation results/local/<새 출력 폴더>/evaluation.json --cases-csv results/local/<새 출력 폴더>/cases.csv --output-dir results/local/<채점 출력 폴더>
uv run --locked python -m scripts.summarize_runs results/local/<새 출력 폴더>/runs.csv
uv run --locked --env-file .env python -m scripts.score_quality --runs results/local/<새 출력 폴더>/runs.csv --candidates results/local/<새 출력 폴더>/candidates.csv --cases eval/test.json --grading eval/test-grading.json --output-dir results/local/<품질 채점 폴더>
```

`score_quality`는 정답 충족, 근거 적합, 근거 없음 대응을 0/1로 채점해 `quality.csv`에 남긴다(판정 모델 호출, 실행당 최대 3회). 판정 응답을 읽지 못한 행은 0점이 아니라 점수 없음으로 남고 요약에서 따로 센다. 모델 판정이어서 사람의 검토가 필요하다.

출력 폴더는 기존 결과를 덮어쓰지 않도록 항상 새 이름을 쓴다. 호출 수와 비용은 [결과 안내](../results/README.md)를 본다.

## 3. 재실행 기록은 Langfuse에 쌓인다

실행(trace)과 점수는 팀 Langfuse 프로젝트에 올라가고, 실행 ID·구성·문서/색인/모델 버전·점수와 판정 사유가 함께 남는다([업로드와 조회](../results/README.md#진술별-faithfulness-판정-확인)). 누가 언제 어떤 구성으로 다시 돌렸는지는 Langfuse에서 실행 단위로 비교한다. 같은 문항을 다시 돌린 기록이 같은 `case_id`로 누적되므로, 별도 파일에 옮겨 적지 않아도 재현 기록이 된다.

저장소 안에서 확인할 수 있는 기록은 `results/`의 실행별 `runs.csv`, `scores.csv`, `candidates.csv`다(Git에서 제외되는 `results/local/`은 제외).

## 독립 환경 재현 (AI 수행, 타인 재현이 아님)

작성자의 PC에서 AI(Claude)가 **새로 받은 클론**에 README의 명령만 따라 처음부터 돌려 본 기록이다. 팀원의 재현을 대신하지 않으며 위 "타인 재현 기록"과 구분한다. 같은 PC·같은 OS라 다른 환경에서의 재현을 보장하지 않는다.

| 날짜 | 실행자 | 환경 | 커밋 | 수행 |
| --- | --- | --- | --- | --- |
| 2026-11-26 | Claude(AI), 작성자 PC의 임시 새 클론 | Windows 11, Python 3.13.14, `.env` 없이 OS 환경변수의 키 사용 | `b49f59c`(브랜치 `feature/seungju/eval-sets`를 로컬 클론) | 아래 |

1. `uv sync --locked`: 7초(캐시된 패키지), `python --version` 3.13.14. [측정]
2. README의 `scripts.prepare_data`(`--openai-model text-embedding-3-small`): 18초, 543청크. 청킹 기준선 지문이 일치하고 청크 ID 집합이 원본 색인과 같다. 색인 `index_id`는 원본과 달랐다(재생성할 때마다 달라지는 값으로 보이며 원인은 확인하지 않았다). 검색 결과에는 영향이 없었다. [측정]
3. 대표 질문 5개(정상 3, 조건 구분 1, 근거 없음 1, 한계 1: `test-d06`, `test-d08`, `test-v03`, `test-n01`, `test-v01`)를 A/B/C로 15건 실행했다. 질문은 최종 20문항에서 골랐고 공식 60건과 섞지 않는 **별도 재현 실행**이다. 결과: 15건 모두 **상태와 정답 청크 순위가 원본과 같았다.** 답변은 문장이 조금 달랐고(예: 현금 교환 안내의 표현) 금액·구간·정보 부족 안내 같은 핵심 사실은 같았다. 응답 시간은 평균 A 1.6초, B 1.8초, C 5.0초로 원본과 비슷했다. [측정]
4. 원본은 [results/repro-clone-2026-11-26/](../results/repro-clone-2026-11-26/)(`runs.csv`, `candidates.csv`, `cases.csv`, `evaluation.json`)에 있다.

**하지 않은 것**: Streamlit 화면과 `scripts.run_chat`, 채점(`score_answers`, `score_quality`), 테스트 실행, Windows 아닌 OS, `.env` 파일을 쓰는 경로. 타인 재현에서는 이 중 화면 실행과 `PYTHONUTF8` 없이 도는 Windows 한국어 환경(채점 테스트가 `cp949` 오류)을 우선 확인해야 한다.

**팀원이 재현하려면**: 이 브랜치가 `dev`에 병합돼야 `eval/test.json`과 이 문서가 새 클론에 들어온다. 병합 전에는 브랜치를 받아야 한다.

## 타인 재현 기록

아래 표에 다른 팀원이 처음부터 다시 돌려 확인한 결과를 적는다. 지금은 비어 있다.

| 날짜 | 실행자 | 대상(문항·구성) | 사용한 명령 | 결과 위치 | 원본과의 차이 |
| --- | --- | --- | --- | --- | --- |
| (아직 없음) | | | | | |
