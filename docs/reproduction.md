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
```

출력 폴더는 기존 결과를 덮어쓰지 않도록 항상 새 이름을 쓴다. 호출 수와 비용은 [결과 안내](../results/README.md)를 본다.

## 3. 재실행 기록은 Langfuse에 쌓인다

실행(trace)과 점수는 팀 Langfuse 프로젝트에 올라가고, 실행 ID·구성·문서/색인/모델 버전·점수와 판정 사유가 함께 남는다([업로드와 조회](../results/README.md#진술별-faithfulness-판정-확인)). 누가 언제 어떤 구성으로 다시 돌렸는지는 Langfuse에서 실행 단위로 비교한다. 같은 문항을 다시 돌린 기록이 같은 `case_id`로 누적되므로, 별도 파일에 옮겨 적지 않아도 재현 기록이 된다.

저장소 안에서 확인할 수 있는 기록은 `results/`의 실행별 `runs.csv`, `scores.csv`, `candidates.csv`다(Git에서 제외되는 `results/local/`은 제외).

## 타인 재현 기록

아래 표에 다른 팀원이 처음부터 다시 돌려 확인한 결과를 적는다. 지금은 비어 있다.

| 날짜 | 실행자 | 대상(문항·구성) | 사용한 명령 | 결과 위치 | 원본과의 차이 |
| --- | --- | --- | --- | --- | --- |
| (아직 없음) | | | | | |
