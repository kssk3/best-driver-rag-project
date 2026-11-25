# 공통 에러 기준

각 도메인이 자기 폴더에서 에러 클래스를 만들 때 따르는 공통 기준이다. 공통 기반은 [`src/common/errors.py`](../src/common/errors.py)에 있고, 동작 규격은 [단위 테스트](../tests/unit/common/test_errors.py)로 확인한다.

`src/common/`은 프로젝트 전체가 공유하는 기반 모듈이며 다른 `src` 패키지를 import하지 않는다. 청크의 `scope_type="common"`(공통 안내 범위)과는 관계없다.

## 공통 기반이 제공하는 것

| 이름 | 역할 |
| --- | --- |
| `ApplicationError` | 프로젝트 예외의 공통 상위 클래스. `code`, `category`, `user_message`를 클래스 속성으로 갖는다. |
| `ErrorCategory` | 실행 중 예외의 공통 분류 5가지 |
| `describe_error(error)` | 어떤 예외든 `ErrorInfo(code, category, user_message, detail)`로 설명한다. |

## 도메인 에러 만들기

에러 클래스와 코드는 각 담당 폴더에서 정의한다. 공통 파일에 도메인 코드를 모으지 않는다.

```python
from src.common.errors import ApplicationError, ErrorCategory


class AnswerDraftError(ApplicationError):
    code = "generation.invalid_draft"
    category = ErrorCategory.CONTRACT_VIOLATION
    # 화면에 보일 문구를 바꿀 때만 지정한다. 기본값은 공통 오류 안내다.
    user_message = "답변을 준비하는 중 오류가 발생했습니다."


raise AnswerDraftError("draft에 status가 없습니다")
```

같은 클래스에서 이유를 더 나눌 때만 인스턴스에서 코드를 지정한다. 클래스 기본값은 바뀌지 않는다.

```python
raise AnswerDraftError("조건 해석 실패", code="generation.condition_decode_failed")
```

### 코드 규칙

- 형식은 `<도메인>.<이유>`이고 각 구간은 소문자로 시작하는 snake_case다. 예: `retrieval.index_not_found`, `ingestion.invalid_manifest`. 점으로 구분한 구간을 더 둘 수도 있지만(`generation.draft.missing_status`) 기본은 두 구간이다.
- 첫 구간은 담당 폴더 이름(`ingestion`, `query`, `retrieval`, `generation`, `evaluation`, `infrastructure`, `interface`, `observability`)을 사용해 다른 도메인과 겹치지 않게 한다. `common.` 접두어는 `src/common/`만 사용한다. 특히 `common.unexpected_error`는 프로젝트 밖 예외를 뜻하므로 도메인에서 쓰지 않는다.
- 하위 클래스에서는 `code = "..."`처럼 타입 표시 없이 대입한다. `code: str = "..."`로 쓰면 mypy가 클래스 변수를 인스턴스 변수로 덮어쓴다는 오류를 낸다(CI mypy 범위인 `src/generation` 등).
- 형식이 틀리면 클래스를 정의하거나 예외를 만드는 시점에 `ValueError`가 발생한다.
- 클래스를 정의하는 시점에 다음 경우는 `TypeError`가 발생한다. `category`가 `ErrorCategory`가 아닐 때, `user_message`가 문자열이 아니거나 비어 있을 때(공백만 있는 문자열 포함), `ValueError` 같은 다른 예외 클래스를 `ApplicationError`보다 앞에 두고 상속했을 때다.
- `code`를 지정하지 않은 하위 클래스는 부모의 코드를 물려받는다. `ApplicationError`를 직접 상속하는 도메인 클래스는 반드시 자기 `code`를 지정한다. 지정하지 않으면 미분류를 뜻하는 `common.application_error`가 그대로 남는다.

### 분류 기준

| 분류 | 사용하는 경우 |
| --- | --- |
| `invalid_input` | 입력 파일이나 요청 형식이 틀려 호출자가 고칠 수 있다. |
| `configuration` | 설정, 환경변수나 키가 없거나 잘못됐다. |
| `external_service` | 외부 API나 모델 호출이 실패하거나 시간 초과됐다. |
| `contract_violation` | 콜백 결과가 공용 규격을 어겼다. 예: 모델 입력에 없는 청크를 인용했다. |
| `internal` | 위에 해당하지 않는 예상하지 못한 오류다. |

이 분류는 실행 중 예외를 나누는 기준이다. [문제와 평가 기준](problem.md#지표와-실패-기록)의 실패 분류(검색 누락, 순위 실패, 생성 오류, 잘못된 인용, 근거 없음 대응 실패)는 평가 결과를 나누는 별도 기준이다.

## 기존 예외를 옮기는 방법

기존 예외는 담당자가 원하는 시점에 직접 옮긴다. 메시지 하나만 받는 `ValueError`·`RuntimeError` 계열 예외는 `ApplicationError`를 **앞에** 두고 기존 상위 클래스를 함께 상속하면 기존 `raise`와 `except` 코드를 바꾸지 않아도 된다. 현재 7개 예외가 모두 여기에 해당한다.

순서를 바꿔 `class X(ValueError, ApplicationError)`로 쓰면 `ValueError.__init__`이 먼저 실행돼 `code=` 인자를 받지 못하므로, 공통 기반이 클래스 정의 시점에 `TypeError`로 막는다. 이 오류는 해당 모듈을 import할 때 발생하므로 변경한 브랜치의 테스트에서 바로 드러난다.

예외가 아닌 mixin 클래스는 이 검사 대상이 아니다. mixin을 `ApplicationError` 계열보다 앞에 둘 때는 `__init__`을 정의하지 않거나, 정의한다면 `*args, **kwargs`를 그대로 `super().__init__`에 넘겨야 한다. 그렇지 않으면 `code=` 인자가 오류 없이 무시된다. `OSError`(여러 인자)나 `KeyError`(`str()`에 따옴표 추가)처럼 생성자나 문자열 표현이 다른 예외를 상위 클래스로 쓸 때는 동작을 따로 확인한다.

```python
# 변경 전
class SourceManifestError(ValueError): ...

# 변경 후: raise SourceManifestError("...")와 except ValueError가 그대로 동작한다.
class SourceManifestError(ApplicationError, ValueError):
    code = "ingestion.invalid_manifest"
    category = ErrorCategory.INVALID_INPUT
```

현재 별도 예외 클래스는 `SourceManifestError`, `SourceDocumentLoadError`, `XMLAdapterError`, `PreprocessedBundleError`, `PreprocessedChunkingError`, `EvaluationCaseError`, `AnswerGenerationError`가 있다.

## 사용자 메시지와 내부 상세

`describe_error`는 화면에 보일 문구와 기록용 상세를 나눈다.

```python
from src.common.errors import describe_error

info = describe_error(error)
info.user_message  # 화면에 표시한다. 원래 예외 메시지를 포함하지 않는다.
info.detail        # 실행 기록에 남긴다. 예: "ValueError: boom"
```

`ApplicationError`가 아닌 예외는 `common.unexpected_error` 코드와 `internal` 분류, 공통 오류 안내로 설명한다. 원래 예외 메시지에는 파일 경로나 본문 조각이 들어갈 수 있으므로 화면에는 `user_message`만 표시한다. `user_message`는 클래스에 고정 문구로만 정하고, 인스턴스에서 실행 값(경로, 질문, 모델 응답)을 넣어 바꾸지 않는다. `detail`은 바깥 예외만 설명하며 `raise ... from`으로 연결된 원인 예외는 포함하지 않는다. API 키, 토큰과 원문 전체는 예외 메시지에도 넣지 않는다.

## 현재 연결 범위

공통 기반만 추가했으며 공용 실행 흐름에는 아직 연결하지 않았다. `src/pipeline.py`는 지금도 예외를 `"타입: 메시지"` 문자열로 `PipelineResponse.error`, `StageRecord.error`와 `PlaceLookupResult.error`에 기록하고, `src/contracts.py`에는 에러 코드 필드가 없다. 응답과 실행 기록에 `code`를 남기는 변경은 공용 규격을 사용하는 담당자와 합의한 뒤 별도로 진행한다.
