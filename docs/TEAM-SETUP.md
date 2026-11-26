# 개발 환경과 공통 연결 기준

공용 인터페이스를 변경할 때는 [로드맵과 역할표](../ROADMAP.md#업무-분담과-인계)에서 담당자와 인계 대상을 확인한다. 파일 위치는 [담당 경로](architecture.md#담당-경로), 동작 기준은 [제품 요구사항](problem.md)을 따른다.

## 작업별 연결 기준

하위 에이전트에 작업을 맡길 때도 대상 브랜치와 커밋을 명시하고, 해당 행의 구현과 호출부 또는 테스트를 함께 확인한다. 공통 기반을 처음 인계했을 때의 설계와 검증 결과는 [11월 24일 인계 기록](handoff.md)에 있다.

| 변경 영역 | 구현과 함께 확인할 항목 |
| --- | --- |
| 공용 요청·응답·콜백 | [자료형](../src/contracts.py), [콜백 인자](../src/runtime.py), [호출 순서](../src/pipeline.py)를 확인한다. `create_runtime`에는 지역 해석기·검색기·생성기를 전달하고 필요하면 질문 다듬기·장소 조회 콜백을 추가한다. `run(request)`가 반환한 `RunRecord`의 `record.response`에서 최종 응답을 읽는다. [연결 테스트](../tests/integration/test_handoff_runtime.py) |
| 자료 준비·청킹·색인 | [준비 명령](../README.md#실제-자료-준비와-근거-조회)과 [준비 코드](../scripts/prepare_data.py)에서 전처리 묶음이 형식별 청크·색인이 되는 경로를 확인한다. [검색 명령](../scripts/search_index.py)은 지정한 구의 근거를 순위순으로 출력한다. 표 행을 수정할 때는 [청킹 테스트](../tests/unit/test_preprocessed_chunking.py)에서 원문 위치와 표의 맥락이 보존되는지 확인한다. |
| 서비스 검색·화면 | [팀 검색기](../src/retrieval/search.py)의 `make_vector_retriever(index, embedder)`는 A 방식의 지역 제한 상위 후보를 반환한다. B/C와 [화면 진입점](../app.py)의 서비스 연결은 남아 있다. [검색 비교 실험](../src/evaluation/answer_experiments/evidence_retrieval_benchmark.py)은 별도 실험 자료에서 벡터와 앙상블을 비교한다. [A 검색 테스트](../tests/unit/test_search.py) |
| 지역·질문 다듬기·장소 | [지역 해석기](../src/retrieval/regions.py), [질문 다듬기](../src/query/rewrite.py), [질문 다듬기와 검색 연결 테스트](../tests/unit/query/test_search_rewrite.py)에서 성공·실패 시 실제 검색 질의를 확인한다. 장소 파싱은 [`parse_places`](../src/retrieval/spots.py)와 [getSpot 테스트](../tests/unit/test_spots.py)를 대조한다. [공용 오류 코드](ERRORS.md) |
| 답변·인용 | [생성 모듈 안내](../src/generation/AGENTS.md), [어댑터](../src/generation/pipeline_adapter.py), [답변 정책](../src/generation/answer.py)과 [고정 근거 테스트](../tests/unit/answer_experiments/test_evidence_pipeline_answers.py)를 확인한다. 검색 후보, 생성기에 전달한 청크, 최종 인용을 차례로 대조한다. 외부 모델에 보낸 요청은 모델 호출부에서 확인한다. |
| 평가·검증 | [채점 기준](problem.md#평가셋과-최종-80건), [브랜치별 평가셋과 실행 명령](../eval/README.md), [실행기](../src/evaluation/runner.py)를 확인한다. 실행기는 질문·위치·조건으로 요청을 만들고, 모범 답안과 허용 청크 ID는 채점에 사용한다. [CI 검사 명령](CI-AND-DEPENDENCIES.md) |

## 실행 환경

설치는 [README](../README.md)의 루트 uv 환경을 사용한다. `.python-version`, `pyproject.toml`과 `uv.lock`을 함께 확인한다. 공용 의존성을 추가할 때 관련 담당자와 실행 가능성을 확인하고 의존성 파일과 잠금 파일을 함께 갱신한다.

UI는 Streamlit으로 구현하고 공통 Python RAG 함수를 직접 호출하는 것이 목표다. 공통 파이프라인과 평가 실행기는 구현됐으며 같은 `RAGPipeline.run`을 사용한다. Streamlit은 공용 의존성에 포함되어 있고 `app.py`로 실행한다(데모 색인 선행, 명령은 [README](../README.md)). 지금 화면은 합성 데모 파이프라인에 연결되어 있다. 현재 터미널에서는 `scripts.search_index`로 실제 색인의 근거를 조회하고, 공통 응답 흐름은 `scripts.demo`의 합성 자동 실행으로 확인한다. 실행 방법은 [README](../README.md)를 따른다. 별도 Next.js 프론트엔드, FastAPI 진입점과 Compose 구성은 현재 필수 범위에 포함하지 않는다.

합성 데모는 로컬 JSON 색인과 해시 임베딩을 사용한다. 조례·별표 인계 자료로 실제 색인을 만들 때는 `text-embedding-3-small`을 지정한다. 검색 CLI는 순위와 근거를 출력하고, 파이프라인 답변은 `create_runtime`에 전달한 생성기가 만든다. [환경변수 예시](../.env.example)

PR #24의 [공용 채팅 모듈](../src/infrastructure/chat_models.py)은 `create_chat_model`로 모델을 생성하고 `invoke_chat`으로 호출한다. 기본 제한 시간은 30초이고 재시도는 0회다. [평가용 답변 초안](../src/generation/model_draft.py)도 같은 생성·호출 함수를 사용하며, 답변 모델에는 JSON 객체 형식을 요청한다. [공용 함수 테스트](../tests/unit/test_chat_models.py)

## 공동 입출력

공용 인터페이스를 바꾸는 담당자와 그 결과를 받는 담당자는 [공용 자료형](../src/contracts.py)을 기준으로 필드를 확인한다. [지역 전달 테스트](../tests/unit/test_pipeline_region_handoff.py)는 생성기에 해석된 구·동이 전달되고 실행 기록에 원래 요청이 보존되는지 확인한다.

| 전달 데이터 | 반드시 구분하거나 보존할 내용 |
| --- | --- |
| 문서와 청크 | 식별자, 본문, 원문 위치, 출처, 적용 지역과 조건, 버전 |
| 질문과 검색 질의 | 원질문, 사용자 조건, 해석한 지역, 변환 질의, 변환 상태 |
| 검색 결과 | 후보 식별자, 본문, 출처와 조건, 단계별 점수와 순위 |
| 생성 입력과 인용 | `RunRecord.candidates`는 검색 후보, `model_input_chunk_ids`는 생성기에 전달한 청크의 순서, `response.citations`는 최종 답변이 인용한 근거를 담는다. |
| 장소 결과 | 문서 청크와 별도 형식, 장소명, 주소, 좌표, 출처, 확인된 수거 종류 |
| 실행 기록 | 요청과 실행 식별자, 실행 유형, 설정과 자료 버전, 단계별 상태, 시간과 오류 |

같은 형식을 각 모듈에 복제하지 않는다. 공용 규격 변경은 호출 코드, 예시, 검증과 문서를 함께 맞춘다. 내부 파일과 함수 구성은 담당자가 정한다.

### 전처리 자료 지역 해석과 답변 생성 연결

`create_runtime`의 지역 해석기로 `src.retrieval.regions.resolve_request`를, 생성기로 `make_answer_generator(draft_evidence_answer, decode_conditions=decode_evidence_conditions)`를 전달한다. 검색기는 순위순으로 정렬한 `SearchCandidate` 목록을 반환해야 한다. 최종 응답은 `runtime.run(request).response`에서 읽는다. [고정 근거 테스트](../tests/unit/answer_experiments/test_evidence_pipeline_answers.py)는 지역 해석 결과와 검색 근거를 미리 지정해 요청·청크·인용을 검증한다. 아래 표는 연희동 질문에서 선택한 구에 따른 검색·생성 입력을 설명한다. PR #13의 [지역 전달 테스트](../tests/unit/test_pipeline_region_handoff.py)는 생성기에 전달된 구·동과 실행 기록에 보존된 원래 요청을 확인한다.

| 연희동 수거용기 색상 질문의 입력 조건 | 공통 런타임에서 확인한 결과 |
| --- | --- |
| 사용자가 서대문구를 선택 | 검색기는 서대문구로 검색한다. 생성기는 원문에 적힌 색상으로 답하고 전달받은 청크를 인용한다. |
| 질문에 연희동만 입력하고 구는 선택하지 않음 | 검색기와 생성기 모두 해석된 서대문구·연희동을 받는다. 실행 기록의 원래 요청에는 사용자가 구를 선택하지 않았다는 사실이 남는다. |
| 사용자가 송파구를 선택 | 선택한 구와 연희동에서 추론한 구가 달라 검색과 생성 전에 지역을 다시 묻는다. |

연습용 매핑표에는 동 4곳이 들어 있다. 위례동 일정 충돌은 송파구를 명시하고 근거를 고정한 별도 관찰 사례다.

## 질문, 지역과 답변

아래는 최종 서비스에 적용할 공통 요구사항이다. 현재 공통 흐름은 생성 입력의 지역/길이 제한, 실제 입력에 포함된 인용 ID 확인과 상태/오류 기록을 제공한다. 최초 검색의 지역 제한과 조건 해석, 질문 변환의 의미 보존 및 답변 판단은 각 콜백 구현에서도 충족해야 한다. 데모는 명시된 구를 확인하고 해시/단어 포함 조건으로 검색하므로 동 추론이나 실제 A/B/C 품질 구현으로 취급하지 않는다.

- 지역 제한은 A 검색부터 적용한다. 동 이름 인식이 선택한 구와 충돌하거나 행정동과 법정동이 모호하면 임의로 덮어쓰지 않는다.
- 질문 다듬기는 의미와 조건을 보존하며 변환 질의를 실제 검색에 사용한다. 변환 실패 시 원질문으로 검색하고 실패 상태를 기록한다.
- 생성기는 원질문을 기준으로 답한다. 유사한 문장을 검색했다는 사실만으로 질문의 지역이나 예외 조건까지 답할 수 있다고 판단하지 않는다.
- 상태는 `answered`, `needs_clarification`, `insufficient_evidence`, `error`를 구분한다. 실행 오류를 정보 부족 대응 성공으로 집계하지 않는다.
- 인용 ID와 URL은 실제 근거에 연결한다. 검색 후보에 있었지만 실제 모델 입력에는 없었던 자료와 답변 인용을 혼동하지 않는다.
- 장소의 수거 종류를 확인하지 않고 요청 품목을 받는다고 단정하지 않는다. 결과 없음, 조회 오류와 좌표 누락을 구분하고 기준 위치 없이 가까운 순서를 만들지 않는다.

현재 리라이트 실패 시 공통 흐름은 지역 해석기가 전달한 기존 `ResolvedQuery.search_query`로 돌아간다. 원질문 복귀 요구를 맞추려면 지역 해석기는 이 값에 원질문을 보존하고 실제 문장 변환은 리라이트 콜백에서 수행해야 한다. 실제 원질문은 `RunRecord.request`, 해석 결과는 `resolved_query`, 최종 검색 질의는 `search_query`로 구분해 기록한다.

## 자료와 기록

같은 본문도 출처와 지역 조건이 다르면 연결을 보존한다. 임베딩 재사용 기준은 본문, 모델과 관련 설정을 반영하며 출처 저장 기준과 구분한다. 청킹 후에도 표, 각주와 예외가 남아 있어야 한다.

[로더](../src/ingestion/loaders.py)는 출처 목록과 본문이 있는 문서를 구분한다. [일반 청커](../src/ingestion/chunking.py)는 문서당 청크 한 개를 만들고, [전처리 자료 청커](../src/ingestion/preprocessed_chunking.py)는 조문·부칙·표 행 단위로 나누며 표 머리글·병합 셀·비고를 보존한다. 두 청커 모두 크기 제한을 넘는 청크에는 오류를 낸다. 빈 `conditions` 목록은 기록된 조건이 없다는 뜻이다. [임베딩 재사용](../src/ingestion/indexing.py) · [색인 저장과 교체](../src/infrastructure/stores.py)

문서와 색인뿐 아니라 동 매핑, 별칭 사전, 모델, 프롬프트와 실행 설정의 버전을 남긴다. 응답 캐시는 필수 최적화가 아니며 최종 비교에서 효과를 배제한다. 최적화 비교 대상은 질문 다듬기다.

합성 예시와 공유 가능한 작은 검증 자료는 `tests/fixtures/`에 두고 합성 여부를 표시한다. 문서 자료는 `data/`, 평가 정답은 `eval/`, 실행 결과는 `results/`로 구분한다. 수집과 색인 입력을 저장소 전체에서 자동 탐색하지 않는다. 정답표와 허용 근거 목록은 검색, 생성과 리라이트 입력에 들어가지 않으며 원문 문서는 정상적으로 색인한다.

같은 요청의 후보, 실제 입력, 답변과 인용을 연결한다. 검색 담당자는 상위 5개 후보와 문항별 허용 청크 ID를, 답변 담당자는 저장 답변의 관련성 점수·산출 방법과 Faithfulness를 인계한다. 같은 실행의 숫자 점수는 Langfuse에서 함께 조회하고, 추가로 확인한 필수 사실이나 인용 오류는 해당 실행에 별도로 기록한다. 서비스 응답과 사후 채점의 시간·비용도 구분한다.

공통 파이프라인은 실행 원본 JSON과 단계별 상태·시간을 저장한다. 공통 평가 실행기는 문항·구성별 응답을 반환한다. 색상표 전용 스크립트에서 확인한 단일 문항의 Hit@5와 개발셋 전체 채점의 범위는 [평가셋 안내](../eval/README.md)에 정리했다. 답변 담당자는 저장된 질문·답변·생성 근거로 Faithfulness를 채점한다. 실행 전체의 토큰·비용 집계는 후속 작업이다.

## 팀 Langfuse 설정

이미 올라간 실행을 보려면 팀 EC2 주소로 로그인해 멤버 권한을 받은 프로젝트를 연다. **Traces**에서 `rag`는 실검색, `demo`는 합성 검증이다. 조회만 하는 팀원은 API 키가 필요 없다.

새 실행을 올릴 팀원은 저장소 루트에서 `uv sync --locked`를 실행하고 로컬 `.env`에 아래 값을 설정한다. 프로젝트의 HTTPS 주소와 키 쌍은 팀 내부에서 전달받는다.

| 설정 | 값과 용도 |
| --- | --- |
| `LANGFUSE_BASE_URL` | 팀 EC2의 Langfuse HTTPS 기본 주소 |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` | 해당 EC2 프로젝트에서 발급한 업로드 키 쌍 |
| `RAG_SCORE_LEDGER_DSN` | 추가 실험 점수를 쓸 때 모든 팀원이 공유하는 PostgreSQL 연결 문자열. [공용 전송 기록 설정](../results/README.md#기존-실행에-팀-실험-점수-연결) |
| `RAG_LANGFUSE_TRACE` | 기본은 꺼짐. `1`을 설정하면 공용 채팅 어댑터의 모델 입력과 응답(프롬프트·근거 포함)이 실행 중 전송된다. |

실행할 때는 `uv run --locked --env-file .env`로 이 파일을 읽는다. 채점 담당자는 `evaluation.json`, `runs.csv`, `cases.csv`가 같은 실행 묶음인지 확인하고, 새 출력 폴더에 채점 결과를 저장한다. `--judge`는 모델 호출이 발생하며 `OPENAI_API_KEY`가 필요하다. 이미 채점된 결과를 공유할 때는 저장된 점수와 상세 파일로 업로드만 실행한다. [A/B/C 실행 예시](../eval/README.md) · [채점 상세 업로드와 조회](../results/README.md#진술별-faithfulness-판정-확인)

## 연결과 검증

각 담당자는 공통 예시로 독립 구현하고 준비된 작은 기능부터 통합한다. 화면용 예시, 고정 근거 생성 시험과 실제 RAG 실행은 기록에서 구분한다. 예시 응답만 표시한 상태를 실제 검색 연결로 보고하지 않는다.

[공용 검증 모듈](../src/validation.py)과 관찰 패널은 뼈대 단계다. 현재 파이프라인은 인용 ID가 선택된 청크에 속하는지 검사한다. 생성 담당자는 재시도·보류 조건을 정하고, 공용 검증은 UI 없이도 사용할 수 있게 연결한다. 새 결과를 보고할 때는 해당 커밋의 테스트 출력, 모델 실행 기록 또는 평가 기록을 근거로 제시한다.
