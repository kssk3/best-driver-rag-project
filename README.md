# 서울시 분리배출 안내 지식 에이전트

“서대문구인데 생활쓰레기를 언제 내놓나요?” 안내 담당자가 이 질문을 받으면 품목을 확인하고, 구청 원문을 찾아 동·주택 유형·적용 기간까지 대조해야 합니다. 이 프로젝트의 목표는 **담당자가 어떤 근거로 안내했는지 다시 확인할 수 있고, 조건이 부족하면 필요한 정보만 되묻는 것**입니다. 현재 공유하는 내용은 개발 계획, 모듈 간 데이터 형식, 개발 환경과 자동 검사 설정입니다.

## Python 개발 환경

팀원은 [uv 설치 안내](https://docs.astral.sh/uv/getting-started/installation/)에 따라 **uv 0.13.9 이상**을 한 번 설치한 뒤 저장소 루트에서 실행합니다. 첫 설치에는 Python 배포 서버와 PyPI에 접속할 수 있어야 합니다.

```sh
git clone https://github.com/kssk3/best-driver-rag-project.git
cd best-driver-rag-project
uv sync
```

`.python-version`은 Python **3.15.2**를 지정합니다. [pyproject.toml](pyproject.toml)은 실행 의존성 15개와 개발 도구(pytest, pytest-cov)를 선언하고, [uv.lock](uv.lock)은 간접 의존성까지 실제 설치 버전을 고정합니다. `uv sync`는 필요한 Python을 확보하고 루트 `.venv/`에 두 그룹을 함께 설치합니다. DB 연결 정보 없이 설치할 수 있습니다.

| 용도 | 실행 패키지 |
| --- | --- |
| API·데이터 검증·환경 변수 | `fastapi`, `uvicorn`, `pydantic`, `python-dotenv` |
| RAG 구성·모델·문서 분할 | `langchain`, `langchain-core`, `langchain-community`, `langchain-openai`, `langchain-text-splitters` |
| PostgreSQL·문서 읽기·키워드 검색 | `langchain-postgres`, `psycopg[binary,pool]`, `pypdf`, `rank-bm25` |
| 평가·데이터셋 | `ragas`, `datasets` |

설치 결과는 `uv run python --version`과 `uv run pytest --version`으로 확인합니다. 새 변경을 받은 뒤에는 다시 `uv sync`를 실행합니다. 앱 코드는 `backend/`에 작성하고 프론트엔드 패키지는 `frontend/`에서 npm으로 관리합니다.

Python 3.15.2로 macOS Apple Silicon에서 처음 설치할 때 `jiter`, `scikit-network`, `zstandard`는 소스에서 빌드됩니다. 이 단계에서는 OS의 C/C++ 빌드 도구와 Rust 도구가 필요할 수 있습니다. 같은 환경의 재동기화에서는 설치된 패키지를 재사용합니다.

## 팀원은 이렇게 시작합니다

| 시점 | 읽을 문서 | 읽고 할 일 |
| --- | --- | --- |
| 작업을 고르기 전 | [해결할 문제와 과제 평가 기준](docs/problem.md) | 사용자 질문 하나를 골라 어떤 원문이면 답할 수 있는지, 어느 조건에서는 보류할지 설명합니다. |
| 당일 작업을 정할 때 | [4일 팀 로드맵](ROADMAP.md) | 내 담당 행에서 오늘 넘길 산출물과 받는 사람을 확인합니다. 수업의 5일차 재현·발표 준비도 확인합니다. |
| 다른 모듈과 연결할 때 | [팀 개발 환경과 API 계약](docs/TEAM-SETUP.md) | 같은 예시 요청·응답으로 먼저 개발하고, 실제 검색 결과를 연결한 뒤 청크 ID와 원문 위치를 대조합니다. |
| 테스트와 PR을 준비할 때 | [커버리지·의존성·비밀정보 검사 가이드](docs/CI-AND-DEPENDENCIES.md) | 언어별 테스트 실행 경로와 의존성 변경을 확인합니다. 검색 성능과 답변 정확도는 고정 평가셋으로 별도 측정합니다. |

Gitleaks의 PR 이벤트를 확인하기 위한 임시 문장입니다.
