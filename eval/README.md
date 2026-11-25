# 평가셋

팀 `dev`의 `c04cb70`에는 개발·최종 문항 파일이 없다. 답변 담당 브랜치 `feature/sungsoo/model-answer-draft`의 `49db656`에는 [개발셋](dev.json)에 서대문구 공동주택 수거용기 색상을 묻는 답변 가능 문항 1개가 있다. 목표는 개발 10문항(답변 가능 8개·근거 없음 2개)과 별도 최종 20문항이다. 합성 3문항은 실행기 연결을 확인하는 [테스트 자료](../tests/fixtures/handoff_eval.json)다. [팀 평가 기준](../docs/problem.md)

개발문항 초안은 답변 생성과 품질 추적 담당자(강성수), 최종셋 관리는 화면과 관찰 검증 담당자(이승주), 원문 근거 교차 확인은 데이터 수집과 질문 정제 담당자(이정은)가 맡는다.

현재 `load_evaluation_cases`는 공용 `EvaluationCase` 목록을 읽는다. 필수 필드는 `case_id`, `question`이고 선택 필드는 `district`, `dong`, `conditions`, `expected_status`, `reference_answer`, `allowed_chunk_ids`다. JSON 배열 또는 `{"is_synthetic": true, "cases": [...]}` 형태를 지원하며 다른 필드는 거부한다. 실행 방법은 [인계 문서](../docs/handoff.md#설정-실행-기록과-평가)를 따른다.

최종 채점에 필요한 필수 사실, 원문 위치와 판정 이유의 상세 구조는 현재 실행 입력에 포함되어 있지 않다. 해당 정보는 문항 ID에 연결한 별도 채점 자료로 관리하고, 평가 모듈과 연결할 때 규격을 맞춘다. 실행 입력에 필드를 임의로 추가하지 않는다. 최종셋은 준비하는 시점부터 개발과 튜닝에 사용하지 않는다.

정답표와 허용 근거 목록은 채점에만 사용하고 검색 색인, 생성과 질문 다듬기 입력에 전달하지 않는다. 정답을 뒷받침하는 원문 문서는 정상적으로 색인한다. 청킹을 바꾸면 근거 매핑을 갱신한다.

공용 [평가 실행기](../src/evaluation/runner.py)는 문항별 응답과 실행 기록을 반환한다. 아래 검색 실험은 색상표 한 문항의 Hit@5와 첫 정답 순위를 계산한다. 전체 개발셋 집계, Ragas 자동 채점과 Langfuse 전송은 아직 연결되지 않았다.

## 색상표 개발 문항 실행

아래 명령은 위 작업 브랜치의 코드가 있는 프로젝트 루트에서 실행한다. 팀 `dev`만 받은 환경에는 이 문항과 전용 스크립트가 없다. [공통 환경](../README.md#개발-환경)을 준비하고, 실제 호출에는 로컬 `.env`에 `OPENAI_API_KEY`를 설정한다. 답변 모델은 [설정 파일](../configs/answer-model-settings.json)에서 확인한다.

1. **검색 순위를 확인한다.** 이 스크립트는 `data/processed/ordinance-v2-openai-small/index-json.json`을 읽는다. 새 환경에서는 먼저 아래 첫 번째 명령으로 색인을 만든다. 색인이 이미 있으면 두 번째 명령부터 실행한다. 검색은 문항의 질문과 자치구를 사용하며, 검색 후 허용 청크 ID와 대조해 순위를 출력한다.

   ```sh
   uv run --locked --env-file .env python -m scripts.prepare_data --bundle data/handoff/jungeun/ordinance-handoff-2026-11-24 --version v1 --output-dir data/processed/ordinance-v2-openai-small --openai-model text-embedding-3-small
   uv run --locked --env-file .env python -m src.evaluation.answer_experiments.color_table_retrieval_top5 --output results/local/color-table-retrieval-top5.json
   ```

2. **검색 근거로 답변과 인용을 확인한다.** 검색 결과 파일이 이미 있으면 이 명령부터 다시 실행할 수 있다. 다섯 청크가 같은 순서로 생성기에 들어갔는지 확인한 뒤 모델 답변, 모범 답안, 인용 순위, 1위 정답 청크 인용 여부를 출력한다.

   ```sh
   uv run --locked --env-file .env python -m src.evaluation.answer_experiments.color_top_answer
   ```

색인 준비와 검색은 기존 출력 경로를 덮어쓰지 않는다. 답변 실험은 위에 지정한 검색 결과 파일을 읽으며 실행 유형은 `fixed_evidence`다. 색인과 원본 실행 JSON은 Git에서 제외된다. 정답 판정 시 질문의 뒤바뀐 전제를 바로잡았는지(유리병용은 주황색, 캔용은 회색)와 어떤 청크를 인용했는지를 따로 확인한다.

근거 한 건만 제공하는 비교 실험은 평가 CLI에 `--factory src.evaluation.answer_experiments.answer_evaluation_runtimes:create_color_runtime`을 지정한다. 이 함수는 모든 질문에 같은 색상표 행을 공급한다. 개발 문항을 늘릴 때는 질문별로 검색하는 구성에서 순위와 답변을 확인한다. [평가 CLI](../scripts/evaluate.py)
