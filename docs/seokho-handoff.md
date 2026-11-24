# 공통 기반과 실제 자료 인계

이 문서는 양석호 담당 공통 기반을 팀 코드에 연결하는 방법과 현재 구현 범위를 설명한다. PR 8의 실제 전처리 자료로 XML 유래 HTML/JSON 색인을 만들고 근거 조회까지 확인했다. 공통 응답 파이프라인은 합성 데모로 검증했으며 팀 A/B/C 검색과 답변 LLM, UI는 아직 연결하지 않았다. 담당 구분은 [구조와 책임](architecture.md), 팀 연결 규칙은 [공동 입출력](TEAM-SETUP.md)에 둔다.

## 인수인계 요약

공통 계약, 출처/본문 로더, XML→HTML 변환, 조문/표 행 청킹, 형식별 색인, 팀 콜백 연결, 인용 검사, 실행 기록과 평가 실행기를 구현했다. `SourceDocument` 규격은 유지한다. 실제 자료는 HTML/JSON 각각 557개 청크로 색인하고 근거 조회까지 확인했으며, 공통 응답 흐름은 합성 데모의 답변/지역 재질문/근거 부족으로 검증했다. 팀원이 먼저 읽을 내용은 [Notion 인수인계](https://app.notion.com/p/422dc8b0e16381758494e218a97087aa)에도 정리했다.

기본 입력은 저장소에 포함된 `data/handoff/jungeun/p04-2026-11-24/`다. Python 3.13.14와 uv 0.13.9 이상으로 [환경을 준비](#처음-실행하기)한 뒤 [자료 준비 명령](#준비와-실제-색인-명령)을 실행한다. 외부 API 없이 문서/청크 준비와 합성 데모를 실행할 수 있다. 실제 색인 생성과 근거 조회에는 OpenAI 인증과 네트워크가 필요하며, 생성 색인은 Git에 없으므로 새 환경에서 다시 만들어야 한다. 기존 v2 ZIP도 대체 입력으로 지원한다.

양석호는 공용 규격과 런타임, 재현 가능한 실행·평가 기반을 구현해 인계를 마쳤다. 아래 파일별 구현·검증 내역은 당시 기여 기록이다. 후속 작업은 [현재 4인 역할표](../ROADMAP.md#업무-분담과-인계)와 [담당 경로](architecture.md#담당-경로)를 따른다.

후속 공용 계약 변경은 해당 기능 담당자가 결과를 사용하는 담당자와 확인한다. 질문 다듬기의 입력·실패 시 복귀 값, 검증·추적 훅, 시도별 기록에 관한 기존 제안은 [공용 규격과 팀 연결](#공용-규격과-팀-연결)에 있다.

현재 실제 질문 도구는 근거 조회 CLI이며 챗봇 답변이나 대화 기억을 제공하지 않는다. 질문 범위 판별과 관련성 하한이 없어 `안녕`에도 무관한 검색 결과가 나올 수 있다. 관련 품목의 별표가 상위 결과에 빠진 사례가 있으며, HTML/JSON 검색 우열과 최종 답변 품질은 아직 검증하지 않았다.

## 실제 전처리 자료 연결

수집과 HWP 전처리의 책임은 [PR 8](https://github.com/kssk3/best-driver-rag-project/pull/8)에 있다. 현재 기본 입력은 이 PR로 저장소에 포함된 `data/handoff/jungeun/p04-2026-11-24/`이며 별도로 받은 v2 ZIP도 지원한다. 공통 기반은 해시와 문서 관계를 확인하고 이미 만들어진 XML/JSON을 읽는다. 원문을 다시 수집하거나 묶음 안의 코드를 실행하지 않는다. 확인한 PR head는 `7598fa3`이며 전처리 파일 44개와 원본 파일 23개가 제공된 ZIP과 바이트 단위로 일치했다.

`src/ingestion/xml_adapter.py`의 `xml_to_html`은 본문 `LawService` XML의 조문/부칙과 첨부 `HwpDoc` XML의 문단/표/병합셀을 HTML로 변환한다. 작성자/폰트 메타데이터와 제개정이유는 검색 본문에 넣지 않는다. XML의 공백과 문구를 보존하며 DTD/entity 선언과 잘못된 표 좌표는 거부한다. 같은 원문의 전처리 JSON은 문자열을 유지해 읽는다. `SourceDocument`와 `Chunk`의 `html/json` 계약은 유지한다.

`load_preprocessed_bundle`은 본문 4개와 첨부 19개를 각각 HTML/JSON 쌍으로 읽어 공용 문서 46개를 만든다. 부모/첨부 관계, 지역, 시행일, 출처 URL과 보관 원본의 프로젝트 상대 `raw_path`를 연결한다. 두 표현은 `document_id`와 `version`을 공유하고 `content_format`으로 구분한다. 삭제 첨부 2개는 제외 기록에 남긴다. 서식 8개와 표지판 1개는 문서로 보관하되 품목별 근거 색인에서 제외하므로, 형식별 색인 대상은 본문 4개와 첨부 10개다.

사람 검수 보정은 부모 MST, 첨부 ID와 원본 해시가 일치할 때 적용한다. 표지판 분류와 그림의 품목별 색상 정보처럼 검수된 범위를 유지하며 실제 수거시설 현황으로 확대하지 않는다. HTML과 JSON 양쪽에서 같은 보정 내용을 사용한다.

`chunk_preprocessed_documents`는 본문의 조문/부칙 단위와 표 행을 사용한다. 표 행에는 병합된 상위 셀, 머리글과 같은 별표 구획의 모든 문단 및 후행 비고를 함께 넣는다. 삭제 조문과 삭제 별표 구획은 색인에서 제외하고 부칙의 과거/현행 혼재 주의를 유지한다. 중첩표는 별도 의미 연결 규격이 없어 현재 청커가 거부한다. 문자 한도를 넘는 내용을 임의로 자르지 않는다.

기본 청킹은 JSON의 원문 `text`를 사용한다. `rows_for_search.search_text`의 용어 정규화는 적용하지 않는다. 따라서 현재 실험은 XML→HTML과 JSON의 같은 원문 표현을 비교하는 경로이며, 원시 XML 문자열이나 정규화 개선 효과의 비교가 아니다.

### 준비와 실제 색인 명령

저장소 루트에서 실행한다. 기본 인계 자료는 Git에 포함돼 있으며 별도 다운로드가 필요 없다. `--version v1`은 원문 버전이고 인계 파일명의 `v2`와 다른 값이다. 출력 폴더는 새 경로여야 한다.

```powershell
uv run --locked python -m scripts.prepare_data --bundle data/handoff/jungeun/p04-2026-11-24 --version v1 --output-dir data/processed/p04-v2-prepared
```

위 명령은 외부 API 없이 준비한다. 별도로 받은 v2 ZIP을 쓰려면 입력만 `--bundle "C:/자료/p04_data_review_2026-11-24_v2.zip"`으로 바꾼다. 실제 색인까지 만들 때는 `OPENAI_API_KEY` 환경변수를 설정한 프로세스에서 다음 명령을 사용한다. `.env` 파일은 자동으로 읽지 않는다. 기존 로컬 키 파일을 사용하려면 `--api-key-file "C:/비공개/openai-key.txt"`처럼 명시적으로 추가한다. 키 내용은 출력하거나 결과 JSON에 기록하지 않는다.

`scripts.prepare_data`와 `scripts.search_index`는 `src/infrastructure/embeddings.py`의 `configure_key_file`과 `BoundedEmbeddings`를 함께 사용한다. 명시한 키 파일은 현재 프로세스에만 적용하며, 임베딩 입력은 토큰 한도를 확인해 자동 잘림이나 평균 없이 전송한다.

```powershell
uv run --locked python -m scripts.prepare_data --bundle data/handoff/jungeun/p04-2026-11-24 --version v1 --output-dir data/processed/p04-v2-openai-small --openai-model text-embedding-3-small
```

생성물은 `documents.json`, `identities.json`, `chunks-html.json`, `chunks-json.json`, `report.json`이며 실제 색인을 요청하면 `index-html.json`과 `index-json.json`도 만든다. ZIP 입력은 필요한 원본과 전처리 자료를 `input/`에 보관한다. 검토한 `data/handoff/` 인계 자료는 Git에 포함되지만 새 청크/색인과 실행 결과는 Git 제외 경로에 저장하며 개인 보관 ZIP과 키 파일도 커밋하지 않는다. 실패한 실행도 `report.json`에 상태, 단계와 오류 종류를 남기므로 일부 파일의 존재만으로 성공을 판단하지 않는다.

같은 자료를 다시 처리할 때는 다른 출력 폴더를 사용한다. 수집처 식별자가 바뀐 개정본에도 기존 문서 ID를 유지해야 한다면 이전 `identities.json`의 `source_key`와 ID 연결을 확인해 `--identities`로 제공한다. 원문 버전은 호출자가 명시하며 로더가 개정을 추정하지 않는다.

### 실제 근거 조회

현재 확인한 로컬 색인은 `data/processed/p04-v2-openai-small/`에 있다. 이 폴더는 Git에 포함되지 않으므로 새 환경에서는 위 준비 명령으로 생성해야 한다. 같은 임베딩 인증 설정을 사용한다.

```powershell
uv run --locked python -m scripts.search_index --index data/processed/p04-v2-openai-small/index-html.json --index data/processed/p04-v2-openai-small/index-json.json --district 송파구
```

질문을 반복 입력하고 `/종료`로 종료한다. `--question "질문"`으로 한 번만 조회할 수 있고, 이때 `--output results/local/검색기록.json`을 추가하면 전체 근거를 새 파일에 저장한다. 화면에는 청크 본문의 앞부분과 출처를 표시한다. 옵션으로 넘긴 공백 질문/지역은 실행 전에 거부하고 반복 입력 중 빈 질문은 건너뛴다.

이 도구는 같은 질문 벡터로 두 색인을 조회하며 지역이 다른 청크와 지역 미확인 청크를 제외한다. 실제 벡터의 단순 코사인 유사도 확인용으로, 답변 생성이나 팀 A/B/C 검색 구현을 대신하지 않는다. 지역은 `--district`로 지정하고 문장에서 추론하지 않는다.

## 처음 실행하기

저장소 루트에서 실행한다. 프로젝트 환경은 Python 3.13.14이며 `uv` 0.13.9 이상을 사용한다. 다음 명령의 `uv run`은 프로젝트 가상환경을 사용한다.

```powershell
uv sync --locked
uv run --locked python -m scripts.demo
```

데모는 합성 문서, 외부 API를 호출하지 않는 해시 임베딩과 원문 인용 생성기를 사용한다. API 키가 필요하지 않다. 데모 성공은 파일 읽기, 색인, 공통 호출과 기록 연결을 확인하는 것이며, 의미 검색이나 실제 LLM 답변 성능의 증거가 아니다.

출력 폴더에는 `index.json`, `summary.json`, `runs/<run_id>.json`이 생성된다. `--output-dir`에는 아직 없는 폴더를 지정한다. 반복 실행에서 기존 결과를 지우지 않으려면 다른 폴더를 지정하거나 옵션을 생략해 자동 생성되는 실행별 폴더를 사용한다.

색인과 평가를 따로 실행할 때는 다음 진입점을 사용한다.

```powershell
uv run --locked python -m scripts.index --documents tests/fixtures/handoff_documents.json --output data/indexes/demo.json --demo --dimensions 128
uv run --locked python -m scripts.evaluate --cases tests/fixtures/handoff_eval.json --output-dir results/local/handoff-eval --demo --settings configs/demo.json
```

`--documents`에는 공용 `SourceDocument` 목록을 지정한다. 출처 목록인 `sources.json`, 검수 ZIP 전체와 평가 정답표는 이 입력에 넣지 않는다. 색인은 명시한 출력 파일을 교체하며, 입력 문서와 출력 색인 경로는 달라야 한다. `data/indexes/`와 `results/local/`의 생성물은 Git 추적 대상에서 제외된다.

평가 명령은 앞서 만든 색인을 읽으며 자동으로 다시 만들지 않는다. 평가 출력 폴더도 아직 없어야 하고, `evaluation.json`과 `runs/<run_id>.json`이 생성된다. 위 색인 명령은 128차원을 명시했으며, 데모 질의 임베더는 설정값 대신 실제 색인 메타데이터의 차원으로 생성하고 provider identity를 확인한다.

HTML/JSON 비교용 입력은 `scripts.index --content-format html` 또는 `--content-format json`으로 서로 다른 색인 파일에 저장할 수 있다. 형식별 분리만으로 동등한 내용이나 성능 비교가 검증되는 것은 아니다.

## 자료를 교체하는 방법

전처리 묶음 연결 외에 기존 파일을 직접 읽는 공용 로더는 다음과 같다.

| 입력 | 함수 | 반환과 범위 |
| --- | --- | --- |
| `sources.json` 형식의 문서 목록 | `load_source_manifest(path)` | `list[SourceManifestEntry]`. 조례/시행규칙과 첨부 링크의 포함 관계를 보존한다. 본문을 다운로드하거나 생성하지 않는다. |
| 메타데이터와 본문을 갖춘 공용 문서 JSON | `load_source_documents(path)` | `list[SourceDocument]`. JSON 배열 또는 `documents` 목록 포장을 읽는다. |
| 전처리된 HTML/JSON 본문 파일 한 개 | `load_preprocessed_content(path, metadata=...)` | `SourceDocument`. 파일 본문과 호출자가 제공한 출처 정보를 연결한다. |

세 함수는 `src/ingestion/loaders.py`에 있다. 폴더를 자동 탐색하지 않으며, 지정한 파일만 읽는다. UTF-8과 UTF-8 BOM을 지원한다. 목록의 `본문_파일`은 기재된 경로이며 파일 보관 완료를 뜻하지 않는다.

단일 전처리 파일을 연결하는 예시는 다음과 같다. `data/processed/example-annex.html`은 사용자가 준비할 본문 파일이며 저장소에 포함되어 있지 않다. 아래 ID와 버전, URL은 합성 예시다. 실제 자료의 ID 발급과 개정 이력 관리는 로더가 수행하지 않는다.

```python
from src.ingestion.loaders import load_preprocessed_content

document = load_preprocessed_content(
    "data/processed/example-annex.html",
    metadata={
        "document_id": "synthetic-annex-2",
        "version": "synthetic-revision-1",
        "title": "합성 별표 안내",
        "source_url": "https://example.org/annex-2.hwp",
        "scope_type": "district",
        "districts": ["서대문구"],
        "parent_document_id": "synthetic-ordinance",
        "parent_document_version": "synthetic-parent-revision-1",
    },
)
```

`content_format`은 `.html`/`.json` 확장자에서 정하고, `content`는 파일 문자열을 보존한다. 두 필드는 `metadata`로 덮어쓸 수 없다. `raw_path`를 생략하면 기존 모델의 기본값 `None`을 유지한다. 이 경로는 전처리 파일 경로가 아니라 실제 보관한 원본의 프로젝트 상대 경로이며, 로더가 임의로 채우지 않는다.

공용 문서 목록은 `SourceDocument` 필드의 JSON 객체들을 배열에 넣는다. 합성 fixture처럼 `{"documents": [...], "is_synthetic": true, "description": "..."}` 형태도 지원한다. 문서 ID, 버전, 표현 형식이 모두 같은 항목은 중복으로 거부한다. 같은 원문의 HTML/JSON 표현은 원문 ID/버전을 공유하고 형식으로 구분할 수 있다.

기존 `SourceDocument` 클래스와 의미는 유지했다. 부모 ID와 버전의 참조 형태를 검사하지만, 부모가 별도 파일에 있을 수 있어 이 일반 로더에서 부모 존재를 강제하지 않는다. HTML은 요소 존재와 명백한 잘림을 검사하는 수준이다. JSON 파싱과 문자열 보존이 원문 의미나 표/각주의 완전한 검수를 대신하지는 않는다. v2 묶음에는 위 `load_preprocessed_bundle` 전용 경로를 사용하며 HWP/PDF 직접 추출은 수집/전처리 담당 영역이다.

## 청킹과 색인

```python
from src.ingestion.chunking import chunk_documents
from src.ingestion.indexing import MemoryEmbeddingCache, build_index
from src.infrastructure.embeddings import DemoHashEmbeddings
from src.infrastructure.stores import save_index

chunks = chunk_documents([document], max_characters=20_000)
cache = MemoryEmbeddingCache()
index = build_index(chunks, DemoHashEmbeddings(dimensions=64), cache=cache)
save_index(index, "data/indexes/example.json")
```

일반 입력용 `chunk_documents`는 문서 전체를 하나의 청크로 만든다. 기본 한도 20,000자는 Python 문자열의 문자 수이며 모델 토큰 한도가 아니다. 초과하면 문서 ID를 포함한 오류를 내고 자동 분할하거나 일부를 버리지 않는다. 실제 v2 자료에는 앞서 설명한 `chunk_preprocessed_documents`의 조문/표 행 분할을 사용한다.

청크는 원문 ID/버전, 표현 형식, 제목, 본문, URL과 적용 지역을 보존한다. 일반 전체 청크의 `source_location`은 `"문서 전체"`이며 v2 청크는 조문/부칙 위치 또는 `table-N/row[R]`를 사용한다. `conditions=[]`는 별도 조건 추출을 하지 않았다는 뜻이다. 본문에 있는 조건과 예외는 삭제하지 않는다. 동일 입력과 청킹 규칙에서는 청크 ID가 재실행해도 유지된다.

`EmbeddingProvider`는 `identity`, `embed_documents(texts)`, `embed_query(text)` 경계다. 기존 LangChain 임베더는 `LangChainEmbeddingsAdapter`로 연결할 수 있다. 모델, 차원과 벡터에 영향을 주는 설정이 바뀌면 `identity`도 바꿔야 한다. 실제 OpenAI 연결을 선택할 때는 `create_openai_embeddings(model, dimensions=...)` 또는 색인 CLI의 `--openai-model`을 사용한다. 인계 데모에서는 이 경로를 사용하지 않는다.

임베딩 캐시는 같은 provider identity와 정확히 같은 본문의 벡터를 재사용한다. 본문이 같아도 출처별 청크는 합치지 않는다. `MemoryEmbeddingCache`는 같은 객체를 넘긴 동안만 유지되며, 프로세스 간 영구 캐시가 아니다.

`build_index`는 전달받은 전체 청크로 새 스냅샷을 만든다. 기존 색인과 자동 병합하거나 증분 삭제하지 않는다. 로컬 JSON에는 벡터, 청크, 임베딩 identity, 차원, 청킹 버전과 원문 버전 목록이 저장된다. `save_index`는 내용을 검증한 다음 임시 파일을 거쳐 지정 파일을 원자적으로 교체한다. 실제 DB와 벡터 저장소는 연결하지 않았다.

## 공용 규격과 팀 연결

공용 타입은 `src/contracts.py`에서 가져온다. 각 담당자가 동일한 구조를 별도 정의하지 않는다.

| 경계 | 공용 타입 |
| --- | --- |
| 문서와 검색 근거 | `SourceDocument`, `Chunk`, `SearchCandidate` |
| 사용자 요청과 해석된 검색 질의 | `PipelineRequest`, `ResolvedQuery`, `PipelineOptions` |
| 생성 결과와 최종 응답 | `GenerationResult`, `Citation`, `PipelineResponse` |
| 별도 장소 조회 | `PlaceResult`, `PlaceLookupResult` |
| 실행과 평가 입력 | `StageRecord`, `RunRecord`, `EvaluationCase` |

`PipelineOptions.variant`의 A/B/C는 연결할 검색 방식의 선택값이다. 공용 타입이 이 값을 받는다는 사실만으로 팀의 Vector, Hybrid, reranker가 구현된 것은 아니다. 응답 상태는 `answered`, `needs_clarification`, `insufficient_evidence`, `error`를 구분한다. 장소는 문서 청크와 별도 결과로 전달하며, 좌표나 수거 가능한 품목을 추정해서 채우지 않는다.

평가의 `reference_answer`와 `allowed_chunk_ids`는 사후 비교용이다. 검색/질문 변환/생성 입력에 넣지 않는다. 검색 후보, 실제 생성 입력 청크와 실제 인용 근거도 각각 구분해 기록한다.

`src/runtime.py`의 `create_runtime`에 각 담당자의 함수를 주입한다. 콜백 호출 규격은 다음과 같다.

| 인수 | 호출 규격 | 담당 연결 지점 |
| --- | --- | --- |
| `resolver` | `(PipelineRequest) -> ResolvedQuery` | 지역/동 해석과 추가 확인 필요 여부 |
| `rewriter` | `(ResolvedQuery) -> str` | 해석된 검색 질의 변환. 원래 요청의 `conditions`는 아직 전달되지 않음 |
| `retriever` | `(ResolvedQuery, *, variant, top_k) -> list[SearchCandidate]` | A/B/C 검색 구현 |
| `generator` | `(PipelineRequest, list[Chunk]) -> GenerationResult` | 원질문과 실제 입력 근거를 사용한 답변/인용 ID |
| `place_lookup` | `(PipelineRequest, ResolvedQuery) -> PlaceLookupResult` | 장소 조회, 생략 가능 |

다음은 준비된 팀 함수를 받는 연결 함수 예시다. 실제 모델이나 DB는 콜백을 만드는 담당 코드에서 준비한다.

```python
from src.config import load_settings
from src.runtime import create_runtime

def connect_team_modules(*, resolver, retriever, generator,
                         rewriter=None, place_lookup=None):
    settings = load_settings()
    # 실제 실행에 사용한 데이터/색인/모델/프롬프트 버전은
    # settings.pipeline.versions에 넣는다. API 키는 넣지 않는다.
    return create_runtime(
        settings,
        resolver=resolver,
        retriever=retriever,
        generator=generator,
        rewriter=rewriter,
        place_lookup=place_lookup,
    )
```

연결된 `pipeline`은 UI와 평가에서 동일하게 사용한다. `run`의 반환값은 응답만이 아니라 `RunRecord`다.

```python
from src.contracts import PipelineRequest

record = pipeline.run(PipelineRequest(question="사용자 질문", district="서대문구"))
response = record.response
print(response.status, response.answer)
```

파이프라인은 지역 확인, 선택적 질의 변환, 검색, 생성 입력 선택, 생성과 인용 검사를 수행한다. 지역 확인이 필요하면 뒤 단계를 건너뛴다. 질의 변환이 실패하면 이전 검색 질의를 사용하고 경고를 남긴다. 생성 입력에서는 지역 미확인 청크와 다른 지역의 청크를 제외하며, 문맥 문자 수 한도를 넘으면 청크 전체를 제외한다. 이 한도는 `PipelineOptions.max_context_chars`이고 토큰 한도가 아니다.

공용 계약에는 다음 연결 문제가 남아 있다. 현재 `rewriter`는 `ResolvedQuery`만 받으며 원질문과 `PipelineRequest.conditions`를 직접 받을 수 없다. 실패 시 사용하는 값도 `resolver`의 `search_query`여서 팀 요구사항인 원질문 복귀와 다를 수 있다. `(PipelineRequest, ResolvedQuery) -> str`로 확장하고 실패 시 원질문을 사용하는 변경안은 담당자 합의 전 제안이며 아직 적용하지 않았다.

`validation.py`와 `tracing.py`를 주입하는 전용 인자는 없다. 생성 콜백 내부에서 공용 검증 함수를 호출하고 재생성/보류할 수는 있으나, 그 시도별 결과를 공용 단계 기록으로 받는 계약은 없다. 파이프라인의 마지막 인용 검사는 실제 입력에 없는 인용을 오류로 처리하는 최종 확인이다. 생성 담당의 복구 정책, 공용 검증 결과 형식과 추적 연결 위치는 담당자와 별도 확정해야 한다. `RunRecorder`는 호출마다 실패를 포함한 실행을 별도 파일에 저장하며, 재시도 번호나 이전 시도 연결을 제공하지 않는다.

`answered`에는 실제 생성 입력에 포함된 청크의 인용 ID가 필요하다. 검색 후보에만 있던 ID를 인용하면 `error`로 기록한다. 장소 조회 실패는 `response.places`의 상태로 별도 표시한다. 지역/품목 조건의 의미 판단과 근거 부족 응답 정책은 주입한 콜백의 책임도 포함하므로, 이 흐름만으로 답변 정확성을 보장하지 않는다.

## 설정, 실행 기록과 평가

`load_settings(path=None, project_root=None)`은 명시한 JSON 설정을 `RuntimeSettings`로 읽는다. 설정을 생략하면 모델 기본값을 사용한다. `index_path`와 `runs_path`의 상대 경로 기준은 `project_root` 또는 현재 작업 폴더다. API 키와 비밀값은 이 JSON이나 실행 기록에 넣지 않고 제공자 환경변수로 전달한다. `.env.example`은 필요한 변수 이름의 예시이며 현재 CLI는 `.env` 파일을 자동 로드하지 않는다.

| 설정 | 의미 |
| --- | --- |
| `index_path` | 사용할 로컬 색인 파일 |
| `runs_path` | 실행 원본 JSON을 저장할 폴더 |
| `max_document_characters` | 문서 전체 청킹의 문자 수 한도 |
| `demo_dimensions` | `scripts.demo`가 새 색인을 만들 때 사용할 데모 임베딩 차원 |
| `pipeline` | 검색 변형, 질의 변환 사용, top-k, 생성 입력 문자 한도와 실행 버전 |

`create_runtime`은 콜백과 기록기를 연결하며 자동으로 실제 DB나 모델을 생성하지 않는다. `RunRecorder`는 실행마다 `<run_id>.json`을 생성하고 같은 실행 ID 파일을 덮어쓰지 않는다. 기록에는 원질문, 해석된 지역과 질의(`resolved_query`), 실제 검색 질의, 후보, 생성 입력 ID, 답변/인용, 단계별 상태와 시간이 들어간다. `RunRecord.duration_ms`는 기록 파일 저장 전까지의 파이프라인 시간이다. 토큰 사용량, API 비용과 Langfuse trace는 현재 자동 수집하지 않는다.

`load_evaluation_cases(path)`는 평가 문항 배열 또는 `{"is_synthetic": true, "cases": [...]}` 포장을 읽는다. `evaluate_cases(cases, pipelines)`는 구성 이름을 키로 하는 파이프라인 딕셔너리를 받아 모든 문항/구성을 실행하고, `case_id`, 구성 이름, 실제 실행 ID, 응답과 원본 기록을 반환한다. 호출 실패도 `error` 결과로 남긴다. Ragas나 Hit@5를 계산하지 않으며, 반환된 실제 결과에 후속 평가를 붙이는 경계다.

실제 팀 함수를 평가 CLI에 연결할 때는 `--demo` 대신 `--factory 모듈명:함수명`을 지정한다. 이 함수는 `RuntimeSettings`를 인자로 받고 `RAGPipeline` 한 개 또는 구성 이름을 키로 하는 `dict[str, RAGPipeline]`을 반환해야 한다. 평가 파일에서 실행 코드를 읽지 않으며, 명령행에 명시한 연결 함수만 불러온다. 서로 다른 설정을 비교하려면 연결 함수가 각 설정의 파이프라인을 만들어 반환한다. 데모의 `--demo` 경로는 합성 구성 한 개를 실행한다.

개별 `runs/<run_id>.json`도 저장하려면 연결 함수가 `create_runtime` 등으로 기록기를 붙여야 한다. 평가 CLI는 반환된 파이프라인에 기록기를 강제로 추가하지 않는다. 기록기를 생략해도 정상 반환된 `RunRecord`는 `evaluation.json` 안에 포함된다.

`create_demo_pipeline(settings)`는 이미 저장된 데모 색인을 읽고, 해시 벡터와 간단한 단어 포함 조건으로 후보를 선택한다. A 호출 형태만 지원하며 실제 팀 A 검색 품질 구현은 아니다. 데모의 질의 변환은 공백 정리이고, 생성기는 첫 근거 본문을 표시한다. B/C 검색, 실제 질문 변환과 답변 모델의 성능을 대신하지 않는다.

## 파일별 인계 범위

| 파일 | 제공하는 역할 | 교체하거나 연결할 부분 |
| --- | --- | --- |
| `src/contracts.py` | 공용 문서/청크/요청/응답/기록 타입 | 팀 함수의 입출력에서 공통으로 사용 |
| `src/ingestion/loaders.py` | 출처 목록과 명시적인 공용 문서 파일 읽기 | 일반 입력의 출처 메타데이터 제공 |
| `src/ingestion/bundle_archive.py`, `preprocessed_bundle.py`, `xml_adapter.py` | v2 묶음 검증과 XML→HTML/JSON 문서 쌍 생성 | 새 전처리 규격, 개정본 ID 연결과 추가 검수 범위 |
| `src/ingestion/chunking.py`, `preprocessed_chunking.py` | 일반 문서 전체 청크와 v2 조문/표 행 청크 | 품질 검증에 따른 분할 개선 |
| `src/ingestion/indexing.py` | provider 기반 색인 스냅샷 생성과 메모리 캐시 | 실제 임베딩 provider와 갱신 정책 |
| `src/infrastructure/embeddings.py` | provider 경계, 데모 해시 임베딩, LangChain 연결, 입력 한도 검사와 명시적 키 파일 설정 | 사용할 모델과 설정 |
| `src/infrastructure/stores.py` | 검증 가능한 로컬 JSON 색인 저장/읽기 | 실제 DB/벡터 저장소 |
| `src/pipeline.py` | 주입받은 팀 함수를 연결하는 공통 호출 흐름 | 지역 해석, 질문 변환, 검색, 답변 생성과 장소 조회 |
| `src/observability/records.py` | 실행 원본 기록 | 운영 저장 위치와 보존 정책, Langfuse 연결 |
| `src/evaluation/runner.py` | 같은 공통 흐름으로 평가 사례 실행 | Ragas, Hit@5, 사람 채점과 최종 비교 |
| `src/config.py`, `src/runtime.py` | 설정 읽기와 함수 연결 | 실제 서비스의 설정 및 자원 생성 |
| `src/demo.py`, `scripts/demo.py` | 외부 API 없는 합성 흐름 확인 | 실제 서비스 성능 평가로 대체하지 않음 |
| `scripts/index.py`, `scripts/evaluate.py` | 명시적인 입력/출력 파일을 받는 CLI | 실제 자료와 검증용 사례 경로 |
| `scripts/prepare_data.py`, `scripts/search_index.py` | v2 자료 준비/실제 색인과 지역 제한 근거 조회 | 팀 검색/생성 파이프라인 연결, 검색 품질 개선 |

## 구현 경계와 검증

이 인계본에는 실제 팀 A/B/C 검색, 질문 변환 모델, 답변 LLM, 지도 UI, 장소 DB, Ragas와 Langfuse 연동이 포함되지 않는다. Streamlit이나 HTTP 서버도 이 공통 기반의 실행 조건이 아니다. 데모의 해시 임베딩과 원문 인용 생성기는 연결 확인용이며 최종 20문항 평가나 HTML/JSON 성능 비교 결과로 사용하지 않는다.

2026-11-24, Python 3.13.14 환경에서 확인한 결과는 다음과 같다. 테스트 명령과 CI 설정은 [검사와 의존성 관리](CI-AND-DEPENDENCIES.md)를 따른다.

- PR #8 통합 당시 로컬 테스트 307개가 통과했고, 커버리지 XML 생성과 `src`, `scripts`, `app.py`의 문법 검사를 마쳤다. 이후 PR #11을 통합한 답변 브랜치의 결과는 [답변과 지역 해석 검증](../README.md#dev-반영-후-답변과-지역-해석-검증)에 기록했다.
- uv 0.13.9의 `uv sync --locked`로 새 Python 3.13.14 의존성 환경을 설치하고 전체 테스트 307개를 통과했다. 같은 새 환경에서 합성 데모의 `answered`, `needs_clarification`, `insufficient_evidence` 세 경로와 `scripts.prepare_data`, `scripts.search_index`의 `--help` 실행을 확인했다. 다른 운영체제나 사용자 PC에서의 재현을 확인한 결과는 아니다.
- 저장소에 포함된 v2 인계 폴더를 외부 임베딩 요청 없이 다시 처리해 `report.json`의 `completed`/`not_requested` 상태를 확인했다. HTML 557개와 JSON 557개 청크 배열은 기존 실제 색인의 청크 배열과 완전히 같았다.

- XML 어댑터 단위 검사와 실제 v2 파일 23개 대조에서 본문 121단위/부칙 4구획, 표 32개/셀 2,643개의 원문 텍스트, 좌표와 병합 보존을 확인했다. 기존 `SourceDocument`의 AST가 변경 전과 일치함을 확인했다.
- 실제 `text-embedding-3-small` 호출로 HTML/JSON 각각 557개 청크, 1,536차원 색인을 완성했다. 로컬 입력 토큰 계수는 HTML 498,212개(청크 최대 2,145개), JSON 408,678개(최대 2,007개)다. 이는 전송할 문자열의 로컬 계수이며 제공자 사용량/청구 내역이 아니다.
- 실제 근거 조회 3개 질문을 두 색인에 실행했다. 송파구 일반주택 음식물 배출시간의 같은 근거는 HTML 1위와 JSON 2위에 나타났다. 우유팩 전용 수거함 부재와 페트병 라벨 질문은 양쪽 상위 3개에서 해당 품목별 별표가 빠졌다. 검색 동작 확인이며 품질 우열이나 정확도 평가 결과로 해석하지 않는다.
- 실제 데모 CLI에서 출처 목록 4건과 첨부 21건을 읽고, 합성 문서 3개의 청크와 실행 JSON 3개를 생성했다. 결과는 `answered`, `needs_clarification`, `insufficient_evidence`로 구분됐다.
- 색인 CLI의 기본 64차원 결과를 평가 CLI가 읽는 흐름, 연결 함수 오류의 기록과 종료 코드 1, 재실행 시 기존 결과를 덮어쓰지 않는 동작을 통합 테스트로 확인했다.

실제 임베딩 API와 로컬 근거 조회까지 검증했다. DB, 팀 A/B/C 검색, 답변 LLM, 지도/UI와 최종 품질 평가는 연결 전이며 bge-m3 비교도 미실행이다. 합성 데모와 실제 색인 성공을 분리배출 답변 정확도나 최종 HTML/JSON 품질 비교 완료로 해석하지 않는다.

코드 변경과 로컬 실행 결과를 원격 배포나 원격 PR 완료로 해석하지 않는다. 팀 저장소로 공유할 때는 실제 변경과 검증 결과를 기준으로 별도 PR을 작성한다.
