# Python 커버리지, 린트, 의존성과 비밀정보 검사

[팀 개발 환경](TEAM-SETUP.md)의 공통 Python 구조에 맞춰 검사한다. 공통 설정이나 의존성을 바꾸는 담당자는 영향을 받는 모듈의 담당자와 테스트 결과를 확인한다. [현재 역할표](../ROADMAP.md#업무-분담과-인계)

## 현재 구현과 검사 범위

공통 문서 로딩과 제공된 전처리 묶음 연결, 문서 전체 및 조문/표 행 청킹, 로컬 색인, 콜백 기반 파이프라인, 실행 기록과 평가 실행기가 구현되어 있다. 합성 자동 데모와 실제 임베딩 색인의 근거 조회 CLI도 실행할 수 있다. `app.py`의 Streamlit 화면은 아직 파일 뼈대이며, 실제 팀 A/B/C 검색, 답변 모델, 장소 DB와 품질평가 연동은 별도 작업이다. 현재 제공하는 API와 연결 방법은 [공통 기반 최소 인계본](seokho-handoff.md)에 정리한다.

[커버리지 워크플로](../.github/workflows/coverage.yml)는 Ubuntu에서 `.python-version`의 Python을 준비하고 uv `0.13.9`를 설치한 뒤 `uv sync --locked`로 잠금 파일에 맞춰 의존성을 설치한다.

- `src/`, `scripts/` 또는 `app.py`에 Python 파일이 있으면 `compileall`로 문법을 검사한다.
- `tests/`에 `test_*.py` 또는 `*_test.py` 파일이 있으면 pytest와 커버리지를 실행한다. 현재 단위 테스트와 통합 테스트가 있으므로 이 실행 조건을 충족한다. 테스트가 없는 경우에만 Actions 요약에 미실행을 기록한다.
- 테스트 수집이나 실행이 실패하면 pytest 오류를 그대로 드러낸다. 문법 검사 성공을 기능 검증 통과로 취급하지 않는다.
- `app.py`도 문법 검사 범위에 포함하지만 Streamlit 화면의 실행을 검증하는 것은 아니다. Node 설치와 Next.js 테스트 작업은 없다.

기존 검사 이름을 이어가기 위해 워크플로의 job ID `backend`는 유지한다. 이 이름이 별도 HTTP 백엔드를 요구한다는 의미는 아니다.

## 테스트와 커버리지

저장소 루트에서 CI와 같은 명령을 실행한다.

```sh
uv sync --locked
uv run --locked python -m compileall -q src scripts app.py
uv run --locked python -m pytest tests --cov --cov-config=.coveragerc --cov-report=xml:coverage.xml
```

[커버리지 설정](../.coveragerc)은 분기 커버리지와 상대 파일 경로를 사용한다. 보고서에는 `src/`와 `app.py`를 포함하고 `tests/`를 제외한다. `scripts/`는 문법 검사와 CLI 테스트 대상이지만 현재 커버리지 보고 대상에는 포함되지 않는다. 결과 파일은 루트 `coverage.xml`이다.

검증용 표본은 `tests/fixtures/`, 단위 테스트는 `tests/unit/`, 연결 테스트는 `tests/integration/`에 있다. 위의 공통 pytest 명령으로 함께 실행한다. `.coveragerc`에는 커버리지 하한을 지정하지 않았다.

로컬 테스트 수와 합성 데모/CLI에서 확인한 동작은 [인계본 검증 기록](seokho-handoff.md#구현-경계와-검증)에 모은다. 해당 결과는 GitHub Actions 실행 성공이나 Codecov 업로드 성공을 뜻하지 않는다.

Windows의 기본 pytest 임시 폴더에 권한 오류가 생겼던 환경에서는 다음과 같이 프로젝트 안의 새 임시 경로를 지정해 검사했다. 오류가 없는 환경에서는 위의 공통 명령을 사용한다.

```powershell
New-Item -ItemType Directory -Path '.cache' -Force | Out-Null
$ciTestTemp = Join-Path (Get-Location) ('.cache/pytest-' + [guid]::NewGuid().ToString('N'))
uv run --locked python -m pytest tests --cov --cov-config=.coveragerc --cov-report=xml:coverage.xml --basetemp $ciTestTemp
```

커버리지는 테스트가 실행한 코드의 범위다. 검색 품질, 정답 충족과 실제 인용의 적합성은 [문제와 평가 기준](problem.md)의 고정 문항으로 별도 측정한다. 단위 테스트, 실제 외부 서비스 연결 시험과 최종 RAG 평가의 결과를 구분해 기록한다.

## 린트, 포맷과 타입 검사

[린트 워크플로](../.github/workflows/lint.yml)는 커버리지 워크플로와 같은 조건(PR, `main`·`dev` 푸시)에서 별도 job으로 실행된다. 린트가 실패해도 테스트 결과는 커버리지 워크플로에서 따로 확인할 수 있다. 세 단계는 앞 단계가 실패해도 모두 실행해 한 번에 결과를 보여 준다. 단, `uv sync --locked`가 실패하면 뒤 단계는 건너뛴다.

- **Ruff 린트**: `src`, `scripts`, `tests`, `app.py`를 검사한다. 규칙은 `pyproject.toml`의 `[tool.ruff.lint] select`에 명시한 `E4`, `E7`, `E9`, `F`, `I`(문법·이름 오류, 명백한 문장 구조 문제, import 정렬)이다. Ruff 기본 규칙이 바뀌어도 이 목록은 유지되지만, 같은 접두어에 새 규칙이 추가되거나 포맷 스타일이 바뀔 수 있으므로 Dependabot의 Ruff 버전 갱신 PR에서 Lint 결과를 확인한다.
- **Ruff 포맷 검사**: 같은 범위가 `ruff format` 결과와 같은지 확인한다. 줄 길이는 Ruff 기본값 88열이다. Ruff는 이 범위 안의 Markdown 파일에 들어 있는 Python 코드 블록도 포맷 대상으로 삼는다. 일괄 포맷 커밋은 [`.git-blame-ignore-revs`](../.git-blame-ignore-revs)에 등록되어 GitHub blame에서 건너뛴다.
- **mypy 타입 검사**: `pyproject.toml`의 `[tool.mypy] files`에 적은 경로만 검사한다. 현재 범위는 `src/generation`, `src/evaluation/answer_experiments`이며, 다른 경로는 담당자가 타입 오류를 정리한 뒤 목록에 추가한다. 목록 밖 모듈(예: `src/contracts.py`)은 import를 따라가 타입 정보로만 쓰고 오류는 보고하지 않는다(`follow_imports = "silent"`).

저장소 루트에서 CI와 같은 명령을 실행한다. 전역에 설치한 `ruff`는 잠금 파일과 버전이 다를 수 있으므로 항상 `uv run --locked`로 실행하고, 다른 파일이 바뀌지 않도록 경로를 지정한다.

```sh
uv run --locked ruff check src scripts tests app.py
uv run --locked ruff format --check src scripts tests app.py
uv run --locked mypy

# 위반 수정 (포맷, 자동 수정 가능한 린트 위반)
uv run --locked ruff format src scripts tests app.py
uv run --locked ruff check --fix src scripts tests app.py
```

GitHub blame은 이 파일을 자동으로 적용한다. 로컬 `git blame`에서도 건너뛰려면 아래처럼 설정한다. 이 설정은 `.git-blame-ignore-revs`가 없는 브랜치(예: 이 변경이 병합되기 전의 `main`)에서 `git blame`을 실패시키므로, 그런 브랜치에서는 `git -c blame.ignoreRevsFile= blame ...`으로 실행한다. 일괄 포맷 커밋의 SHA가 바뀌지 않도록 이 브랜치는 merge commit으로 병합한다.

```sh
git config blame.ignoreRevsFile .git-blame-ignore-revs
```

## Codecov와 GitHub Actions

PR 이벤트와 `main` 또는 `dev`에 푸시할 때 검사한다. 테스트가 있고 Dependabot 실행이 아닌 경우, 같은 저장소에서 만든 PR이나 푸시는 `CODECOV_TOKEN`으로 보고서를 업로드하도록 설정되어 있다. 포크 PR과 Dependabot PR은 테스트를 실행하되 업로드하지 않는다. 업로드 실패는 검사 실패로 처리한다.

[Codecov 설정](../codecov.yml)은 `python` 플래그에 `src/`와 `app.py`를 연결한다. 워크플로는 지정한 `coverage.xml`만 업로드하며 자동 보고서 탐색은 끈다. 예전 프론트엔드의 경로 보정과 저장소 자체의 최소 커버리지 목표는 지정하지 않았다.

원격 실행을 확인할 때는 Actions 결과, `coverage.xml`의 파일 경로와 Codecov에 표시된 커밋을 대조한다. 로컬 테스트 결과만으로 토큰 설정, 실제 업로드와 서비스 연결 상태를 완료 처리하지 않는다.

## 의존성과 런타임

`.python-version`은 `3.13.14`, `pyproject.toml`의 `requires-python`은 `==3.13.14`다. 프로젝트는 uv `0.13.9` 이상을 요구하며 CI는 `0.13.9`를 명시적으로 설치한다. `package = false`로 설정되어 있고 개발 의존성 그룹에 `pytest`, `pytest-cov`, `ruff`, `mypy`가 있으며 버전은 `uv.lock`으로 고정한다. 새 기능에 필요한 패키지는 해당 구현 PR에서 추가하고 `uv.lock`과 실제 설치 결과를 함께 확인한다.

LangChain, Ragas, FastAPI 등의 패키지가 선언되어 있어도 해당 기능의 구현이나 외부 서비스 연결이 완료되었다는 뜻은 아니다. 현재 `streamlit`은 프로젝트 의존성에 선언되어 있지 않다. 합성 데모와 CLI는 API 키 없이 실행되며, 실제 OpenAI 임베딩을 선택할 때는 제공자 환경변수가 필요하다. `.env.example`에는 비어 있는 `OPENAI_API_KEY` 항목만 둔다.

[Dependabot 설정](../.github/dependabot.yml)은 루트 Python 의존성인 `uv`와 `github-actions`를 매주 확인한다. 새 Dockerfile 등 별도 관리 대상이 생기면 실제 파일과 실행 환경을 확인한 뒤 해당 항목을 추가한다.

## 비밀정보 검사

[Gitleaks 워크플로](../.github/workflows/gitleaks.yml)는 PR, `main` 푸시 또는 수동 실행에서 동작한다. `dev` 푸시만으로는 이 워크플로가 실행되지 않는다. 전체 Git 이력을 체크아웃하고 checkout 인증 정보는 남기지 않는다. Gitleaks `8.30.1`의 Linux 배포 파일을 받아 워크플로에 고정한 SHA-256과 대조한 후 실행한다.

[검사 설정](../.gitleaks.toml)은 기본 탐지 규칙을 사용한다. 현재 HEAD까지의 전체 변경 이력과 병합의 첫 부모 차이를 검사하고 탐지된 비밀값은 가린다. 로컬에 같은 버전의 Gitleaks가 설치되어 있다면 워크플로와 같은 명령을 사용할 수 있다.

```sh
gitleaks git --config .gitleaks.toml --redact=100 --log-opts="--full-history --diff-merges=first-parent HEAD" .
```

이 명령은 커밋 이력을 검사하므로 아직 커밋하지 않은 작업 파일을 검사한 결과와 구분한다. 이번 문서 갱신에서는 Gitleaks를 실행하거나 원격 검사 성공을 확인하지 않았다.

[Git 제외 설정](../.gitignore)은 `.env`, `.env.*`, 가상환경, 캐시와 커버리지 산출물을 제외하고 `.env.example`만 허용한다. 수집 원문 `data/raw/`, 전처리 자료 `data/processed/`, 색인 `data/indexes/`와 로컬 실행 결과 `results/local/`도 제외한다. 각 데이터 폴더의 `.gitkeep`과 검토한 `tests/fixtures/` 표본은 별도로 관리한다. 실제 API 키와 인증 정보는 커밋하지 않는다.
