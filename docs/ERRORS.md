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

기존 예외는 담당자가 원하는 시점에 직접 옮긴다. 메시지 하나만 받는 `ValueError`·`RuntimeError` 계열 예외는 `ApplicationError`를 **앞에** 두고 기존 상위 클래스를 함께 상속하면 기존 `raise`와 `except` 코드를 바꾸지 않아도 된다. 아래의 기존 예외 7개가 여기에 해당한다.

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

공통 기반 도입 전의 별도 예외 클래스는 `SourceManifestError`, `SourceDocumentLoadError`, `XMLAdapterError`, `PreprocessedBundleError`, `PreprocessedChunkingError`, `EvaluationCaseError`, `AnswerGenerationError`가 있다.

## 사용자 메시지와 내부 상세

`describe_error`는 화면에 보일 문구와 기록용 상세를 나눈다.

```python
from src.common.errors import describe_error

info = describe_error(error)
info.user_message  # 화면에 표시한다. 원래 예외 메시지를 포함하지 않는다.
info.detail        # 실행 기록에 남긴다. 예: "ValueError: boom"
```

`ApplicationError`가 아닌 예외는 `common.unexpected_error` 코드와 `internal` 분류, 공통 오류 안내로 설명한다. 원래 예외 메시지에는 파일 경로나 본문 조각이 들어갈 수 있으므로 화면에는 `user_message`만 표시한다. `user_message`는 클래스에 고정 문구로만 정하고, 인스턴스에서 실행 값(경로, 질문, 모델 응답)을 넣어 바꾸지 않는다. `detail`은 바깥 예외만 설명하며 `raise ... from`으로 연결된 원인 예외는 포함하지 않는다. API 키, 토큰과 원문 전체는 예외 메시지에도 넣지 않는다.

## 파이프라인 연결

`src/pipeline.py`는 예외를 기록하는 모든 자리에서 `describe_error`를 거친다. 실행 기록에서 에러를 읽는 위치는 다음과 같다.

| 필드 | 채우는 경우 | 내용 |
| --- | --- | --- |
| `PipelineResponse.answer` | 항상 | `status="error"`이면 그 예외 클래스의 `user_message`. 화면에는 이 값을 표시한다. 단, 답변을 만든 뒤 실행 기록 저장만 실패한 경우에는 생성된 답변이 그대로 남는다. |
| `PipelineResponse.error` | `status="error"` | 기록용 내부 상세 `"타입: 메시지"`. 화면에 표시하지 않는다. |
| `PipelineResponse.error_code` | `status="error"` | 응답을 실패시킨 원인 코드 |
| `StageRecord.error`, `StageRecord.error_code` | 해당 단계가 실패 | 그 단계의 내부 상세와 원인 코드 |
| `PlaceLookupResult.error` | 장소 조회 실패 | 내부 상세. 코드는 `place_lookup` 단계 기록에 있다. |

- 질문 다듬기와 장소 조회가 실패해도 문서 답변은 계속 진행한다. 이때 응답의 `error_code`는 `None`이고 코드는 `rewrite` 또는 `place_lookup` 단계 기록에만 남는다. 장소 조회는 예외를 던진 경우와 `PlaceLookupResult(status="error")`를 반환한 경우 모두 `place_lookup` 단계가 `error`로 기록된다.
- 실행 기록 저장이 실패하면 응답이 `error`로 바뀐다. 이미 앞 단계에서 실패했다면 응답의 `error_code`는 최초 원인을 유지한다.
- 평가는 실패한 단계 이름과 `error_code`를 묶어 실패를 분류한다. 예: `citations` 단계의 `pipeline.citation_outside_evidence`와 `generate` 단계의 `generation.invalid_citation`·`generation.missing_citation`은 잘못된 인용이다.
- 여러 단계가 `error`일 때 응답을 실패시킨 단계는 `resolve`, `retrieve`, `context`, `generate`, `citations` 중 `error`인 단계다. 이 단계들은 첫 실패에서 멈추므로 많아야 하나다. 그중 실패가 없으면 `record` 단계다. `rewrite`와 `place_lookup` 실패는 응답 상태를 바꾸지 않으므로 응답 실패 원인으로 세지 않는다.
- `error_code` 필드가 없는 이전 실행 기록 JSON도 그대로 읽힌다. 분류(`category`)는 아직 기록하지 않는다.

### 파이프라인 검사 코드

파이프라인은 콜백 결과가 규격을 어기면 `PipelineContractError`(`contract_violation`)를, 리라이트를 켰는데 rewriter가 없으면 `PipelineConfigurationError`(`configuration`)를 낸다. 둘 다 `ValueError`를 함께 상속한다. `pipeline.invalid_callback_result`는 콜백이 **반환한 값**의 검증 실패에만 붙는다. 콜백 안에서 직접 발생한 pydantic 검증 오류는 `common.unexpected_error`로 기록된다.

| 코드 | 단계 | 원인 |
| --- | --- | --- |
| `pipeline.empty_search_query` | `resolve` | 해석된 검색 질의가 비어 있다. |
| `pipeline.missing_clarification_question` | `resolve` | 되묻기 상태인데 추가 질문이 없다. |
| `pipeline.region_mismatch` | `resolve` | 해석된 구가 요청에서 지정한 구와 다르다. |
| `pipeline.rewriter_not_configured` | `rewrite` | 리라이트를 켰지만 rewriter가 연결되지 않았다. |
| `pipeline.invalid_rewrite_output` | `rewrite` | 리라이트 결과가 비었거나 문자열이 아니다. |
| `pipeline.invalid_retrieval_result` | `retrieve` | 검색 결과가 목록이 아니다. |
| `pipeline.duplicate_chunk_id` | `context` | 검색 후보의 `chunk_id`가 중복된다. |
| `pipeline.missing_citation` | `citations` | `answered`인데 인용이 없다. |
| `pipeline.citation_outside_evidence` | `citations` | 모델 입력에 없던 청크를 인용했다. |
| `pipeline.invalid_callback_result` | 해당 콜백 단계 | 콜백 결과가 공용 규격 검증을 통과하지 못했다. |
| `pipeline.place_lookup_failed` | `place_lookup` | 장소 조회 콜백이 `status="error"`를 반환했다. 응답과 `places`는 그대로다. |

`pipeline.place_lookup_failed`는 예외 없이 단계 기록에 직접 붙이는 코드다. 이 단계의 `error`에는 `"타입: 메시지"` 대신 콜백이 반환한 `PlaceLookupResult.error`가 들어가며, 비어 있으면 "장소 조회 콜백이 실패 상태를 반환했습니다."를 쓴다.

`pipeline.missing_citation`과 `pipeline.citation_outside_evidence`는 생성기가 청크 ID를 직접 돌려줄 때 걸린다. `make_answer_generator`를 쓰는 P04 생성기는 인용 번호를 먼저 검사하므로, 같은 문제가 `generate` 단계의 `generation.missing_citation`·`generation.invalid_citation`으로 기록된다.

### 답변 생성 코드

`src/generation/pipeline_adapter.py`의 `AnswerGenerationError`는 `(ApplicationError, RuntimeError)`이며 메시지는 기존처럼 실패 이유(`invalid_draft` 등)다. 실패 이유는 어댑터가 직접 붙이는 값(`condition_decode_failed`, `pending_evidence`, `invalid_citation`)과 `answer.py`에서 넘어오는 `error_kind`(현재 `invalid_input`, `generation_failed`, `invalid_draft`, `missing_citation`, `invalid_citation`)다. `answer.py`는 이유를 다음 순서로 정한다.

- 일반 답변: 상태가 `answered`가 아니거나 본문이 비었거나 링크가 있으면 `invalid_draft`다. 본문이 올바를 때 `citation_indices`가 없거나 목록이 아니거나 비어 있으면 `missing_citation`, 목록 안에 근거 범위 밖 번호나 정수가 아닌 값(문자열, `True`, `None` 등)이 하나라도 있으면 `invalid_citation`이다.
- 출처 충돌 응답: 근거 측면을 차례로 검사한다. 측면이 객체가 아니거나 발췌문이 문자열이 아니면 `invalid_draft`, 근거 번호가 잘못되면 `invalid_citation`이다. 발췌문이 원문에 없거나 링크가 있음, 같은 출처의 반복, 측면이 둘 미만, 발췌문이 모두 같음은 `invalid_draft`다. 앞 측면의 번호 오류가 먼저 발견되면 뒤 측면의 형식 오류는 확인하지 않는다.
- 어댑터는 인용된 청크 ID가 비었거나 전달한 청크에 없으면 `invalid_citation`으로 둔다.

코드는 다음과 같이 정해진다.

| 코드 | 뜻 | 기록을 본 뒤 할 일 |
| --- | --- | --- |
| `generation.<이유>` | 원인이 분류된 생성 실패. 예: `generation.generation_failed`는 답변 초안 함수(모델 호출)의 실패, `generation.invalid_citation`은 잘못된 인용 번호나 청크 | 이유에 맞게 원인을 확인한다. |
| `generation.invalid_error_kind` | 실패 이유 값이 한 구간의 snake_case가 아니어서 코드로 쓸 수 없음. 에러 처리 중에 새 오류가 나지 않도록 하는 방어 장치 | `answer.py`의 `error_kind` 값이 바뀌었는지 확인한다. |
| `generation.failed` | 코드 없이 `AnswerGenerationError`를 던진 미분류 오류(클래스 기본값) | 그 `raise`에 이유와 코드를 붙인다. |

세 경우 모두 화면 문구는 "답변을 준비하는 중 오류가 발생했습니다."다.


## 질문 정제 적용

`src/query/errors.py`는 공통 기반을 상속하며 기존 예외 타입과 상세 메시지를 유지한다.

| 클래스 | 기존 타입 | 분류 | 코드 |
| --- | --- | --- | --- |
| `RewriteCallError` | `RuntimeError` | `external_service` | `query.rewrite_call_failed` |
| `RewriteOutputTypeError` | `TypeError` | `contract_violation` | `query.rewrite_invalid_type` |
| `RewriteOutputError` | `ValueError` | `contract_violation` | 기본 `query.rewrite_invalid_format`, 별칭 규칙 위반은 `code="query.rewrite_rule_violation"` |
| `RewriteConfigurationError` | `ValueError` | `configuration` | `query.rewrite_not_configured` |

`rewrite.py`의 모델 호출과 출력 검사에 적용했다. 실행 중 정제 실패는 기존 파이프라인이 잡아 지역 해석이 끝난 `resolved.search_query`로 검색을 계속한다. `prompt_runtime.py`에서 호출 함수가 누락된 경우는 런타임 생성 시 실패하며 검색 복귀와는 별개다.

`rewrite_question()`의 반환 필드는 변경하지 않았다. 실행 중 정제 실패의 코드는 [파이프라인 연결](#파이프라인-연결)에 따라 `rewrite` 단계 기록의 `error_code`에 남으며, `category`는 아직 기록하지 않는다. 모델 요청·응답 본문은 상세 메시지에 넣지 않는다.
