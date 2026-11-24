# 출처 목록 로더

`sources.json` 형식의 문서 목록을 읽어 조례 정보와 첨부 관계를 Python 객체로 전달한다. 입력에는 원문 URL과 본문 파일 경로가 있고 실제 조문이나 표 본문은 없다. 반환값은 출처 목록이며 `SourceDocument`와 구분한다.

## 연결 위치와 실행 환경

구현 위치는 `src/ingestion/loaders.py`다. 기존 Python 3.13.14 환경과 Pydantic을 사용한다. 다른 모듈에서는 아래 함수를 가져와 호출한다.

이 문서는 현재 체크아웃의 `load_source_manifest` API를 설명한다. 같은 파일의 본문 로더와 이후 청킹/색인 연결은 [공통 기반 최소 인계본](seokho-handoff.md)을 따른다.

```python
from pathlib import Path

from src.ingestion.loaders import load_source_manifest

sources = load_source_manifest(Path("tests/fixtures/source_manifest.json"))

for source in sources:
    print(source.ordinance_serial, source.title, source.effective_date)
    for attachment in source.attachments:
        print(source.ordinance_serial, attachment.number, attachment.title)
```

파일 경로는 호출자가 전달한다. UTF-8과 UTF-8 BOM 파일을 지원한다. JSON 목록의 문서 순서와 각 문서의 첨부 순서를 유지한다.

## 공개 API

```text
load_source_manifest(path: str | Path) -> list[SourceManifestEntry]
```

함수를 호출할 때 파일을 읽고 검증한 목록을 반환한다. 문서나 첨부를 자동 다운로드하지 않으며, `body_file`에 적힌 원문 파일을 열거나 존재 여부를 확인하지 않는다. 입력 파일은 변경하지 않는다.

| 입력 JSON 키 | 반환 필드 | 의미 |
| --- | --- | --- |
| `구` | `district: str` | 목록에 기록된 적용 구 |
| `자치법규명` | `title: str` | 조례 또는 시행규칙 제목 |
| `일련번호` | `ordinance_serial: str` | 원문 서비스의 일련번호 |
| `시행일` | `effective_date: date` | `YYYYMMDD`를 날짜로 변환한 값 |
| `원문_URL` | `source_url: str` | 원문 주소 |
| `본문_파일` | `body_file: str` | 목록에 선언된 상대 경로 |
| `별표_링크` | `attachments: list[AttachmentLink]` | 해당 문서에 속하는 첨부 목록 |
| `별표_상태` | `attachment_status: str` | 입력에 기록된 수집 상태 |

각 `AttachmentLink`에는 다음 필드가 있다.

| 입력 JSON 키 | 반환 필드 | 의미 |
| --- | --- | --- |
| `번호` | `number: str` | 첨부 목록의 번호. 앞의 0을 보존 |
| `제목` | `title: str` | 첨부 제목 |
| `파일_URL` | `source_url: str` | 첨부 파일 주소 |

## 조례와 첨부 관계

`source.attachments`에 포함된 첨부는 해당 `source`에 속한다. 따라서 첨부를 순회할 때 부모의 `ordinance_serial`을 함께 전달할 수 있다. 같은 첨부 번호가 다른 조례에 나타나는 것은 허용하고, 같은 조례 안에서 중복되는 번호는 오류로 처리한다.

`ordinance_serial`은 외부 서비스의 식별값이다. 내부 `SourceDocument.document_id`나 `version`으로 자동 사용하지 않는다. 첨부에 부모의 시행일을 복사하거나 본문과 버전을 임의로 채우지도 않는다.

제목에 삭제 표시가 있거나 행정 서식인 첨부도 목록에 남긴다. 검색에 사용할 자료를 선별하는 판단은 목록을 읽은 다음 단계에서 처리한다.

`body_file`은 입력에 기록된 위치만 뜻한다. 실제 보관 파일을 확인해 프로젝트 기준으로 지정하는 `SourceDocument.raw_path`와 구분한다. 반환된 상대 경로를 후속 코드에서 사용할 때는 기준 폴더와 실제 파일 존재 여부를 확인해야 한다.

## 입력 검증과 오류

다음 입력은 `SourceManifestError`로 처리한다. 예외 메시지에는 입력 파일과 문제가 발생한 항목을 표시한다.

- 잘못된 JSON, 중복 JSON 키 또는 UTF-8로 읽을 수 없는 내용
- 최상위 목록이나 문서/첨부 구조의 불일치
- 필수 필드 누락, 지원하지 않는 추가 필드, 잘못된 값 타입
- 존재하지 않는 날짜나 `YYYYMMDD`와 다른 시행일 표기
- HTTP/HTTPS 원문 주소 형식 오류
- 절대 경로 또는 상위 폴더 이동을 포함한 본문 경로
- 중복 문서 일련번호 또는 동일 문서의 중복 첨부 번호

숫자로 들어온 일련번호와 첨부 번호를 문자열로 자동 보정하지 않는다. 빈 문서 목록과 빈 첨부 목록은 허용한다. 파일이 없으면 `FileNotFoundError`가 발생하며, 읽기 권한 같은 파일 시스템 오류도 호출자가 처리한다.

```python
from src.ingestion.loaders import SourceManifestError, load_source_manifest

try:
    sources = load_source_manifest("tests/fixtures/source_manifest.json")
except SourceManifestError as error:
    print(f"목록 형식 오류: {error}")
except OSError as error:
    print(f"목록 파일 읽기 오류: {error}")
```

오류가 있는 목록은 일부 문서만 반환하지 않는다. 잘못된 자료를 수정한 뒤 목록 전체를 다시 읽는다.

## 원문 처리와의 경계

`load_source_manifest`의 완료 범위는 문서 목록과 첨부 관계 읽기다. 이 함수는 `SourceDocument`나 `Chunk`를 만들지 않으며 ID/버전 발급, 다운로드와 HWP/PDF 추출을 수행하지 않는다.

같은 모듈에는 공용 문서 목록을 읽는 `load_source_documents`와 전처리 파일에 명시적인 메타데이터를 연결하는 `load_preprocessed_content`도 구현돼 있다. 제공된 v2 전처리 묶음은 별도 `src/ingestion/preprocessed_bundle.py`의 `load_preprocessed_bundle`로 읽고, `scripts.prepare_data`에서 ZIP 검증과 구조 청킹, 선택적 실제 색인까지 연결한다. 입력 형식과 실행 방법은 [실제 전처리 자료 연결](seokho-handoff.md#실제-전처리-자료-연결)에 정리한다. 출처 목록의 URL을 따라 원문을 재수집하는 기능은 이 로더의 범위에 포함하지 않는다.

## 검증

2026-11-24에 목록 로더 테스트 39개가 통과했다. 제공된 원본 `sources (1).json`과 테스트 fixture에서 문서 4건과 첨부 21건, 배열 순서와 번호의 앞자리 0이 보존되는 것을 확인했다. 빠른 시작 예제에서도 시행일이 `date`로 변환되고 첨부 번호 `000700`이 유지됐다. 전체 프로젝트의 최신 검증 범위는 [인계본 검증 기록](seokho-handoff.md#구현-경계와-검증)에 둔다.

로더 테스트는 부모별 첨부 관계, 삭제/서식 항목 보존, 빈 목록, UTF-8 BOM, 잘못된 JSON과 키/타입/날짜/주소/경로, 중복 일련번호와 첨부 번호를 확인한다. 목록 로딩은 본문용 `SourceDocument` 정의와 독립적으로 검증한다.

실행 명령과 Windows 임시 폴더 접근 오류의 재현 방법은 [검사와 의존성 관리](CI-AND-DEPENDENCIES.md)에 모은다.

이 검증은 목록 로딩 범위다. 원문 추출이나 실제 검색/답변 성능을 확인한 결과는 아니다.
