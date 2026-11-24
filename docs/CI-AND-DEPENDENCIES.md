# Python 커버리지, 의존성과 비밀정보 검사

[팀 개발 환경](TEAM-SETUP.md)의 Python과 Streamlit 구조에 맞춰 검사한다. 공통 기반과 통합 담당자(양석호)는 공통 설정을 관리하고, 각 담당자는 자기 모듈의 테스트와 의존성 변경을 검토한다.

## 초기 구조의 검사 범위

현재는 폴더와 Python 파일 뼈대를 준비한 단계다. 기능 구현과 기능 테스트, 실제 RAG 실행 결과는 아직 없다. [커버리지 워크플로](../.github/workflows/coverage.yml)는 항상 `uv sync --locked`로 기존 Python 환경을 확인한다.

- `src/`, `scripts/` 또는 `app.py`에 Python 파일이 있으면 `compileall`로 문법을 검사한다.
- `tests/`에 `test_*.py` 또는 `*_test.py` 파일이 있으면 pytest와 커버리지를 실행한다. 테스트 파일이 없으면 Actions 요약에 기능 테스트와 커버리지를 실행하지 않았다고 기록한다.
- 테스트 파일은 있지만 수집에 실패하거나 테스트가 실패하면 pytest 오류를 그대로 드러낸다. 뼈대의 문법 검사 성공을 기능 검증 통과로 취급하지 않는다.
- Streamlit 화면도 Python 검사 범위에 포함한다. Node 설치와 Next.js 테스트 작업은 사용하지 않는다.

기존 검사 이름을 이어가기 위해 워크플로의 job ID `backend`는 유지한다. 이 이름이 별도 HTTP 백엔드를 요구한다는 의미는 아니다.

## 테스트와 커버리지

기능 코드와 테스트를 추가한 뒤 저장소 루트에서 실행한다.

```sh
uv sync --locked
uv run --locked python -m pytest tests --cov --cov-config=.coveragerc --cov-report=xml:coverage.xml
```

[커버리지 설정](../.coveragerc)은 저장소 루트 기준으로 `src/`와 `app.py`를 보고서에 포함하고 `tests/`는 제외한다. 결과 파일은 루트 `coverage.xml`이다. 검증용 표본은 `tests/fixtures/`, 단위 테스트는 `tests/unit/`, 연결 테스트는 `tests/integration/`에 둔다.

커버리지는 테스트가 실행한 코드의 범위다. 검색 품질, 정답 충족과 실제 인용의 적합성은 [문제와 평가 기준](problem.md)의 고정 문항으로 별도 측정한다. 단위 테스트, 실제 외부 서비스 연결 시험과 최종 RAG 평가의 결과를 구분해 기록한다.

## Codecov와 GitHub Actions

PR을 열거나 갱신할 때와 `main` 또는 `dev`에 푸시할 때 검사한다. 테스트 실행 조건을 충족한 일반 팀 PR과 일반 푸시는 `CODECOV_TOKEN`으로 보고서를 업로드한다. 포크 PR과 Dependabot PR은 테스트를 실행하되 업로드하지 않는다. 업로드 실패는 검사 실패로 처리한다.

[Codecov 설정](../codecov.yml)은 `python` 플래그에 `src/`와 `app.py`를 연결한다. 예전 프론트엔드의 경로 보정은 사용하지 않는다. 최소 커버리지 목표는 아직 지정하지 않았다.

첫 실제 테스트를 추가할 때 `coverage.xml`의 파일 경로와 Codecov에 표시된 커밋을 대조한다. 서비스 연결 상태는 실제 업로드로 확인하며, 설정 파일이 있다는 이유만으로 연결 완료로 기록하지 않는다.

## 의존성과 런타임

`.python-version`과 `pyproject.toml`은 Python `3.13.14`로 맞추고 `uv.lock`도 같은 환경을 기준으로 관리한다. CI는 `.python-version`을 읽어 같은 Python 버전을 설치한다. uv와 GitHub Actions 버전은 유지한다. 새 기능에 필요한 패키지는 해당 구현 PR에서 추가하고 잠금 파일과 실제 설치 결과를 함께 확인한다.

[Dependabot 설정](../.github/dependabot.yml)은 루트 Python 의존성인 `uv`와 `github-actions`를 매주 확인한다. 새 Dockerfile 등 별도 관리 대상이 생기면 실제 파일과 실행 환경을 확인한 뒤 해당 항목을 추가한다.

## 비밀정보 검사

[Gitleaks 워크플로](../.github/workflows/gitleaks.yml)와 [설정](../.gitleaks.toml)은 유지한다. PR, `main` 푸시 또는 수동 실행에서 Git 이력을 검사하며 로그의 비밀값은 가린다.

로컬에 워크플로와 같은 버전의 Gitleaks가 설치되어 있다면 다음 명령으로 확인한다.

```sh
gitleaks git --config .gitleaks.toml --redact=100 --log-opts="--full-history --diff-merges=first-parent HEAD" .
gitleaks git --staged --config .gitleaks.toml --redact=100 .
```

두 번째 명령은 커밋 전 스테이징한 변경을 검사한다. 실제 API 키, 인증 정보와 로컬 `.env`는 커밋하지 않는다.
