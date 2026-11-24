# 폴더 구조와 책임

병렬 작업을 시작할 폴더와 Python 파일 뼈대를 마련했다. 파일에는 담당과 역할만 표시했으며 기능, 공통 타입과 실행 함수는 각 담당자가 구현한다. 아래 구조는 내부 파일 개수나 구현 순서를 제한하지 않는다.

## 폴더 배치

```text
.
├─ .github/                  PR, 의존성 갱신과 자동 검사
├─ .streamlit/               Streamlit 설정
├─ configs/                  수집, 파이프라인과 평가 설정
├─ prompts/                  생성과 질문 다듬기의 프롬프트
├─ src/                      공통 설정, 규격, 런타임, 파이프라인과 검증
│  ├─ ingestion/             수집과 정제, 로더, 청킹과 색인
│  ├─ query/                 별칭과 질문 다듬기
│  ├─ retrieval/             A/B/C 검색, 지역 해석, 장소 저장과 조회
│  ├─ generation/            근거 기반 생성과 응답 정책
│  ├─ infrastructure/        저장소, 임베딩과 외부 자원 연결
│  ├─ interface/             Streamlit 화면, 지도와 관찰 패널
│  ├─ evaluation/            공통 실행기, 담당별 지표와 비교 분석
│  └─ observability/         실행 원본 기록과 Langfuse 연결
├─ scripts/                  수집, 색인과 평가 명령
├─ data/
│  ├─ raw/                   수집 원문과 장소 원자료
│  ├─ processed/             정제 문서, 청크와 장소 자료
│  └─ indexes/               재생성 가능한 색인
├─ eval/                     개발셋과 최종셋, 정답과 허용 근거
├─ results/                  실행별 원본과 평가 결과
├─ tests/
│  ├─ unit/                  외부 연결을 대체한 동작 검사
│  ├─ integration/           모듈과 실제 외부 서비스 연결 검사
│  └─ fixtures/              합성 여부를 표시한 작은 검증 자료
└─ docs/                     팀 공통 기준과 재현 문서
```

Streamlit 진입점의 뼈대는 루트 `app.py`에 있다. 화면 코드는 `src/interface/`에 두고 공통 RAG 함수를 호출하도록 구현한다. 현재 파일에는 docstring만 있고 기능 코드와 공용 호출 규격은 없다. Python 패키지에는 `__init__.py`를 두었다.

## 담당 경로

| 담당 업무 | 주요 위치 | 다른 담당자와 맞출 경계 |
| --- | --- | --- |
| 데이터 수집과 질문 정제 담당자(이정은) | `src/ingestion/`의 수집과 정제, `src/query/`, 수집 설정과 별칭 자료 | 문서와 getSpot 원자료, 원질문 및 변환 질의의 인계 |
| 검색과 지역 및 장소 조회 담당자(이명지) | `src/retrieval/`, `src/evaluation/`의 검색 지표 | 지역 해석, A/B/C 후보, 장소 DB 저장과 조회, Hit@5 |
| 답변 생성과 품질 추적 담당자(강성수) | `src/generation/`, `src/evaluation/`의 Ragas 평가, `src/observability/`의 Langfuse 연결 | 응답 정책, 실제 입력과 인용, 개발문항 초안과 답변 평가 |
| 화면과 관찰 검증 담당자(이승주) | `src/interface/`, `app.py`, `.streamlit/`, 공용 검증과 비교 분석 | 지도, 상태 표시, 순위와 인용 관찰, 최종 평가셋 관리 |
| 공통 기반과 통합 담당자(양석호) | `src/` 공통 기반, `src/ingestion/`의 로더/청킹/색인, `src/infrastructure/`, 공통 평가 실행기와 원본 저장 | 호출 규격, 런타임과 버전, 전체 파이프라인과 재현 |

`src/ingestion/`, `src/evaluation/`와 `src/observability/`는 책임이 나뉜 공유 영역이다. 같은 폴더의 모든 기능을 한 담당자의 업무로 보지 않는다. 코드를 만들 때 파일별 책임을 구분하고 각 담당자의 내부 로직을 통합 코드에 복제하지 않는다.

## Python 시작 파일

현재 파일은 역할과 담당만 표시한 뼈대다. 공용 데이터 필드, 타입, 함수 시그니처와 외부 자원 선택을 미리 고정하지 않는다. 담당자는 내부 파일을 확장할 수 있으며 공용 호출 경계 변경은 사용하는 담당자와 맞춘다.

### 데이터 수집과 질문 정제 (이정은)

| 파일 | 역할 |
| --- | --- |
| `src/ingestion/collect.py` | 공식 문서 수집 |
| `src/ingestion/clean.py` | 본문과 조건 정제 |
| `src/ingestion/spots.py` | getSpot 원자료 수집 |
| `src/query/aliases.py` | 품목과 표현 별칭 |
| `src/query/rewrite.py` | 질문 다듬기 |
| `scripts/collect.py` | 수집 실행 진입점 |

### 검색과 지역 및 장소 조회 (이명지)

| 파일 | 역할 |
| --- | --- |
| `src/retrieval/regions.py` | 구와 동 이름 해석 |
| `src/retrieval/search.py` | A/B/C 검색 |
| `src/retrieval/spots.py` | 장소 저장과 조회 |
| `src/evaluation/retrieval_metrics.py` | 검색 지표 |

### 답변 생성과 품질 추적 (강성수)

| 파일 | 역할 |
| --- | --- |
| `src/generation/answer.py` | 근거 기반 답변과 응답 정책 |
| `src/evaluation/answer_metrics.py` | 답변 자동 평가 |
| `src/observability/tracing.py` | Langfuse 추적 |

### 화면과 관찰 검증 (이승주)

| 파일 | 역할 |
| --- | --- |
| `app.py` | Streamlit 진입점 |
| `src/interface/chat.py` | 질문과 답변 화면 |
| `src/interface/map.py` | 장소 목록과 지도 |
| `src/interface/inspection.py` | 관찰 검증 패널 |
| `src/validation.py` | UI 독립 공용 검증 |
| `src/evaluation/comparison.py` | 구성 비교와 실패 분석 |

### 공통 기반과 통합 (양석호)

| 파일 | 역할 |
| --- | --- |
| `src/config.py` | 공통 설정 |
| `src/contracts.py` | 공용 입출력 규격 |
| `src/runtime.py` | 외부 자원 초기화 |
| `src/pipeline.py` | 공통 RAG 흐름 |
| `src/ingestion/loaders.py` | 정제 문서 로딩 |
| `src/ingestion/chunking.py` | 공통 청킹 |
| `src/ingestion/indexing.py` | 색인과 버전 연결 |
| `src/infrastructure/embeddings.py` | 임베딩 연결 |
| `src/infrastructure/stores.py` | 공통 저장소 연결 |
| `src/evaluation/runner.py` | 공통 평가 실행기 |
| `src/observability/records.py` | 실행 원본 저장 |
| `scripts/index.py` | 색인 실행 진입점 |
| `scripts/evaluate.py` | 평가 실행 진입점 |

총 42개 Python 파일 중 32개는 역할별 시작 파일이고, 10개는 `src/`, 각 하위 패키지와 `scripts/`의 `__init__.py`다. 기능 구현과 테스트는 아직 없다.

파일별 구현 항목과 확인 기준은 [Notion 구조 문서](https://app.notion.com/p/422dc8b0e1638150b62acfe703074f30?pvs=204)에 정리한다. 전체 API 규격을 확정한 문서가 아니라 기존 책임을 기준으로 준비한 구현 안내다.

## 연결 원칙

```mermaid
flowchart TD
    UI["Streamlit 입력"] --> P["공통 RAG 함수"]
    E["공통 평가 실행기"] --> P
    P --> R["지역과 조건 해석"]
    R --> Q["질문 다듬기 또는 원질문"]
    Q --> S["A/B/C 검색"]
    S --> G["원질문 기준 답변 생성"]
    R --> L["장소 조회"]
    G --> O["응답, 실제 인용과 실행 기록"]
    L --> O
    O --> UI
    O --> E
```

이 도식은 기능의 연결을 나타낸다. 필요한 조건을 되묻거나 오류를 처리하는 분기는 [공통 연결 기준](TEAM-SETUP.md)을 따른다. 장소 조회와 문서 검색의 결과 형식은 분리한다.

통합 코드는 검색과 생성 모듈의 공용 호출 지점을 사용한다. 내부 파일 분리와 알고리즘 선택은 각 담당자가 정하며, 공용 입출력, 의존성, DB 구조와 실행 기록 변경은 사용하는 담당자와 맞춘다.

평가셋과 실행 결과의 관리 원칙은 [eval](../eval/README.md), [results](../results/README.md)에 둔다. `eval/`의 정답과 `results/`의 결과를 수집 자료나 검색 색인으로 사용하지 않는다.
