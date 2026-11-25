# 평가셋

이 브랜치의 [개발셋](dev.json)에는 서대문구 공동주택 수거용기 색상과 송파구 대형폐기물 신고·배출에 관한 두 문항이 있다. 송파구 문항은 [채점 메모](dev-scoring-notes.json)에 초안으로 표시했다. 사람이 공식 원문을 대조한 날짜는 아직 비어 있다. 목표는 개발 10문항(답변 가능 8개·근거 없음 2개)과 별도 최종 20문항이다. 실행기 연결 검사용 [합성 3문항](../tests/fixtures/handoff_eval.json)은 따로 관리한다. [팀 평가 기준](../docs/problem.md)

개발문항 초안은 답변 생성과 품질 추적 담당자(강성수), 최종셋 관리는 화면과 관찰 검증 담당자(이승주), 원문 근거 교차 확인은 데이터 수집과 질문 정제 담당자(이정은)가 맡는다.

현재 `load_evaluation_cases`는 공용 `EvaluationCase` 목록을 읽는다. 필수 필드는 `case_id`, `question`이고 선택 필드는 `district`, `dong`, `conditions`, `expected_status`, `reference_answer`, `allowed_chunk_ids`다. JSON 배열 또는 `{"is_synthetic": true, "cases": [...]}` 형태를 지원하며 다른 필드는 거부한다. 실행 방법은 [인계 문서](../docs/handoff.md#설정-실행-기록과-평가)를 따른다.

최종 채점에 필요한 필수 사실, 원문 위치와 판정 이유의 상세 구조는 현재 실행 입력에 포함되어 있지 않다. 해당 정보는 문항 ID에 연결한 별도 채점 자료로 관리하고, 평가 모듈과 연결할 때 규격을 맞춘다. 실행 입력에 필드를 임의로 추가하지 않는다. 최종셋은 준비하는 시점부터 개발과 튜닝에 사용하지 않는다.

정답표와 허용 근거 목록은 채점에만 사용하고 검색 색인, 생성과 질문 다듬기 입력에 전달하지 않는다. 정답을 뒷받침하는 원문 문서는 정상적으로 색인한다. 청킹을 바꾸면 근거 매핑을 갱신한다.

두 문항을 팀 A 검색기로 각각 평가하고 검색 후보와 답변을 비교하려면 [평가 실행 명령과 CSV 안내](../results/README.md#평가할-때마다-저장하는-csv)를 따른다. 아래 색상표 실험은 한 문항에서 허용된 청크가 상위 5개 안에 있는지(Hit@5), 그중 첫 청크가 몇 위인지를 확인한다. 전체 개발셋 지표 집계, Ragas 자동 채점과 Langfuse 전송은 후속 작업이다.

## 색상표 개발 문항 실행

[공통 환경](../README.md#개발-환경)을 준비하고 저장소 루트에서 실행한다. 실제 검색과 모델 답변 생성에는 로컬 `.env`의 `OPENAI_API_KEY`가 필요하다. 답변 모델은 [설정 파일](../configs/answer-model-settings.json)에 지정한다.

1. **검색 순위를 확인한다.** 이 스크립트는 `data/processed/ordinance-v2-openai-small/index-json.json`을 읽는다. 같은 인계 자료·버전·임베딩 설정으로 만든 색인이 있으면 해당 폴더를 아래 색인 경로에서 재사용할 수 있다. 색인이 준비돼 있으면 두 번째 명령부터 실행하고, 새 환경에서는 첫 번째 명령으로 색인을 만든다. 검색은 문항의 질문과 자치구를 사용하며, 검색 후 허용 청크 ID와 대조해 순위를 출력한다.

   ```sh
   uv run --locked --env-file .env python -m scripts.prepare_data --bundle data/handoff/jungeun/ordinance-handoff-2026-11-24 --version v1 --output-dir data/processed/ordinance-v2-openai-small --openai-model text-embedding-3-small
   uv run --locked --env-file .env python -m src.evaluation.answer_experiments.color_table_retrieval_top5 --output results/local/color-table-retrieval-top5.json
   ```

2. **검색 근거로 답변과 인용을 확인한다.** 같은 질문과 자치구로 저장한 검색 결과가 있으면 그 파일을 `results/local/color-table-retrieval-top5.json`에 두고 이 단계부터 실행할 수 있다. 다섯 청크가 같은 순서로 생성기에 들어갔는지 확인한 뒤 모델 답변, 모범 답안, 인용 순위, 1위 정답 청크 인용 여부를 출력한다.

   ```sh
   uv run --locked --env-file .env python -m src.evaluation.answer_experiments.color_top_answer
   ```

색인 준비와 검색은 기존 출력 경로를 덮어쓰지 않는다. 답변 실험은 위에 지정한 검색 결과 파일을 읽으며 실행 유형은 `fixed_evidence`다. 색인과 원본 실행 JSON은 Git에서 제외된다. 정답 판정 시 질문의 뒤바뀐 전제를 바로잡았는지(유리병용은 주황색, 캔용은 회색)와 어떤 청크를 인용했는지를 따로 확인한다.

근거 한 건을 고정하는 비교 실험은 색상표 문항 하나만 담은 JSON을 `--cases`에 전달하고 `--factory src.evaluation.answer_experiments.answer_evaluation_runtimes:create_color_runtime`을 지정한다. 이 함수는 항상 같은 색상표 행을 제공한다. 두 개발 문항을 함께 평가할 때는 질문별로 검색하는 `create_a_runtime`을 사용한다. [평가 CLI](../scripts/evaluate.py)
