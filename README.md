# 서울 분리배출 RAG

서대문구와 송파구 주민이 품목과 배출 상황을 질문하면 공식 문서의 근거와 출처를 안내하는 Knowledge Agent를 만든다. 필요한 조건은 되묻고, 자료에 답이 없으면 정보 부족을 알린다.

확정 범위는 Streamlit 화면, A/B/C 검색, 동 이름 인식, 질문 다듬기와 getSpot 장소 지도다. 화면과 평가 실행기는 같은 Python RAG 함수를 호출한다.

**현재는 폴더 구조, Python 파일 뼈대와 개발 환경을 준비한 단계다.** 시작 파일에는 역할과 담당만 표시되어 있으며 수집, 검색, 생성, 지도와 평가 실행 기능은 아직 구현하지 않았다. 각 담당자가 내부 파일을 확장하고 구현 순서를 정한다.

## 개발 환경

저장소 루트에서 실행한다. Python `3.13.14`, uv `0.13.9` 이상과 `uv.lock`을 사용한다.

```sh
git clone https://github.com/kssk3/best-driver-rag-project.git
cd best-driver-rag-project
uv sync --locked
uv run --locked python --version
uv run --locked python -m pytest --version
```

로컬 uv가 요구 버전보다 낮으면 전역 설치를 바꾸지 않고 `uv tool run --from uv==0.13.9 uv sync --locked`로 같은 환경을 준비할 수 있다. 첫 설치는 Python 배포 서버와 PyPI 연결이 필요하다. 이 방식으로 설치했다면 실행도 `uv tool run --from uv==0.13.9 uv run --locked python --version`처럼 같은 uv 버전을 사용한다. 기존 Python 3.15 가상환경도 동기화하면 `.python-version`에 맞는 3.13.14 환경으로 다시 생성한다.

현재 의존성 파일은 루트의 공용 Python 환경을 관리한다. Streamlit, Selenium과 Langfuse 등 구현에 필요한 패키지는 해당 기능을 처음 연결하는 PR에서 의존성과 잠금 파일을 함께 갱신한다. 기존 FastAPI 의존성이 남아 있어도 별도 HTTP 서버 구현을 요구하지 않는다. 현재 `app.py`는 문서 문자열만 있는 뼈대이며 앱 실행 명령은 실제 화면 구현과 함께 추가한다.

## 작업 위치

| 경로 | 용도 |
| --- | --- |
| `src/` | 공통 실행 기반과 담당별 Python 모듈 |
| `configs/`, `prompts/`, `.streamlit/` | 공통 설정, 프롬프트와 화면 설정 |
| `scripts/` | 수집, 색인과 평가 실행 진입점 |
| `data/` | 수집 원문, 정제 자료와 색인 |
| `eval/` | 개발 10문항과 최종 20문항, 정답 및 허용 근거 |
| `results/` | 실행 원본, 평가와 비교 결과 |
| `tests/` | 단위 검사, 연동 검사와 작은 검증 자료 |

상세 파일 목록, 담당 경로와 연결 원칙은 [구조와 책임](docs/architecture.md)에 있다. 파일별 구현 항목과 플로우 차트는 [Notion 구조 문서](https://app.notion.com/p/422dc8b0e1638150b62acfe703074f30?pvs=204)에서 확인한다. 폴더의 `.gitkeep`은 빈 작업 위치를 Git에 보존하기 위한 파일이다.

## 팀 공통 문서

- [문제와 평가 기준](docs/problem.md): 지원 범위, 평가 분리와 완료 기준
- [공동 진행 단계](ROADMAP.md): 7단계와 병렬 작업 흐름
- [개발 환경과 연결 기준](docs/TEAM-SETUP.md): 공용 규격과 인계 방식
- [검사와 의존성 관리](docs/CI-AND-DEPENDENCIES.md): pytest, Codecov, Dependabot과 Gitleaks

통합 기준 브랜치는 `dev`다. 작업 브랜치는 `feature/<작성자>/<작업명>`으로 만들고, 검증 후 `dev`를 대상으로 PR을 연다. 초기 구조에는 실제 평가셋과 실행 결과가 포함되어 있지 않다.
