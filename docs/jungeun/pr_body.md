## 요약

서대문구·송파구 자치법규를 검토 기록에 따라 수집하고, XML의 첨부 링크만으로 읽을 수 없던 별표의 표 내용을 본문·부칙과 함께 추출할 수 있게 했다. 출처·지역·버전·원문 위치와 조건을 보존하며, 석호님이 원본과 전처리 JSON을 함께 대조할 수 있도록 인계 자료를 준비했다. 통합 대상은 `dev`이며 공통 RAG 규격 연결 전 단계다.

## 주요 변경

- 수집: API·문서 검토 기록과 재검토 기한, 정확한 문서명 및 MST를 확인한 뒤 실행별 XML·해시·첨부 링크를 기록한다. OC는 환경변수 또는 비공개 입력으로 받는다.
- 본문: 4개 문서의 107조문과 장 제목을 포함한 121단위, 부칙 4구획을 추출한다. 전체 삭제 조문 17개를 표시하고 일부 항·호 삭제와 구분한다. 원문과 앞뒤 공백만 정리한 본문을 함께 보존한다.
- 첨부: 삭제 표시 2건을 제외한 HWP 19건에서 표 32개·셀 2,643개를 추출했다. 셀 좌표·병합 범위·주석·별표 구획을 보존하고 행정 서식은 구분한다. 처리본의 XML 목록 단계 값인 `collection_status`·`content_present`는 `xml_listing`으로 옮겼다. 원본 다운로드 기록은 유지하며, `download_status`·`processing_status`·`extracted_text_present`·`extracted_table_count`·`human_review_status`의 의미를 분리한다.
- 공유 보호: 검색 응답 XML 4건의 상세 링크에서 OC 인증값 15곳을 가렸다. 개인 원본은 별도로 보존하며 원본 해시·공유본 해시·가림 기록을 구분한다. 공개 브랜치는 인증값이 포함된 이전 로컬 커밋을 포함하지 않는다.
- 검색 준비: 명시한 원문 용어 16개의 내부 공백 복원과 검색용 공백 정리를 추가했다. 원문과 변경 전·후 로그를 보존한다. `tables[].rows_for_search`는 병합된 부모 셀을 각 행에 연결하고 셀 좌표·상속 여부·출처와 비고·각주 문맥 참조를 보존한다. 실제 표 32개에서 헤더·서식 행을 포함한 555개 행을 생성했으며, 팀 청킹·검색기 연결은 별도다.
- 검수: 사람이 확인한 분류와 그림 요약을 별도 기록으로 저장하고, 부모 MST·첨부 ID·원본 해시가 일치할 때만 재적용한다. 공식 자료 간 시간·요일 차이는 원문 값을 덮어쓰지 않고 출처별로 남긴다.
- 인계: 원본·전처리 JSON·검수 기록과 읽는 순서를 [인계 폴더](https://github.com/kssk3/best-driver-rag-project/tree/feature/jungeun/data-preparation/data/handoff/jungeun/p04-2026-11-24)에 포함했다. 기존 `data/raw`·`data/processed` 제외 규칙을 유지하며 공통 스키마·로더·청킹·검색과 다른 담당자의 코드는 변경하지 않았다.

## 검증

- macOS의 Python 3.13.14에서 합성 XML·모의 응답 기반 단위 테스트 37개 통과. 문법·Git 공백 검사와 수집 설정 4건의 `--check` 통과.
- Ruff 0.14.10 임시 도구로 담당 Python 14개 파일의 검사(`--select E4,E7,E9,F,I --target-version py313 --line-length 88`)와 포맷 검사 통과. uv 0.13.9도 임시 도구로 사용했으며 전역 uv 0.13.5와 팀 의존성·잠금 파일은 변경하지 않았다.
- 사용자가 실제 API로 본문 XML 4건·첨부 링크 21개를 수집했고, Codex가 저장 파일·출처·MST·시행일·해시를 대조했다.
- Codex가 첨부 19개를 내려받고 본문·부칙 문자열을 원본 XML과 대조하고, 표의 셀 좌표·병합 범위·텍스트 순서를 HWP 변환 구조 XML과 대조했다. 실제 HWP 19건을 오프라인으로 재추출하고 사람 검수 2건의 분류·색상 요약 재적용을 확인했다.
- 사람이 확인한 범위는 판매소 표지판 분류, 공동주택 수거용기 색상 6개, 음식물 배출시간의 출처별 차이, 위례동 일정 충돌 처리 방침의 4개 항목이다. 이를 모든 셀의 승인이나 현장 일정 확정으로 확대하지 않았다.
- 로컬 합성 문서 3개의 BM25 예제 1건에서 용어 복원 전후의 질의 매칭을 확인했다. 실제 팀 B/C 검색·재정렬 통합이나 검색 품질 검증은 실행하지 않았다.

실행한 주요 검증 명령:

```sh
.venv/bin/python -m pytest tests -q
.venv/bin/python -m compileall -q src scripts app.py
.venv/bin/python -m scripts.collect --config configs/collection/law_collection.example.json --check
git diff --check
```

## 남은 문제

화·목·일 권역 재활용 일정의 공식 웹/PDF와 지도 표시 코드 간 차이는 사용자 확인이 1건 남아 있다. 전체 셀을 사람이 개별 승인한 상태는 아니며, 원문 확보·추출 검수와 자료의 색인·외부 모델 이용 승인은 구분한다. HOP 미리보기 일부 대형 표에는 겹침 경고가 있어 원본 HWP와 추출 구조를 함께 확인한다.

공통 스키마·로더·청킹·검색·외부 모델은 연결하지 않았고, HTML/Selenium 수집·getSpot과 RAG 전체 흐름은 검증하지 않았다. 인계 형식은 담당 내부 초안으로, 공통 입력 규격에 맞추는 작업이 남아 있다.

---

## Summary

Collect Seodaemun-gu and Songpa-gu ordinances according to recorded reviews, and extract appendix tables that are only linked from the XML alongside the body and supplementary provisions. Preserve source, district, version, location and conditions, and prepare originals with processed JSON for Seokho to compare. The integration target is `dev`; shared RAG interfaces remain unconnected.

## Changes

- Validate API/document reviews, review expiry, exact titles and MST values before recording per-run XML, hashes and attachment links. Read OC from an environment variable or hidden prompt.
- Extract 107 articles, 121 units including headings, and four supplementary-provision sections across four documents. Mark 17 entirely deleted articles separately from deleted paragraphs or items. Keep original text alongside text with only surrounding whitespace removed.
- Extract 32 tables and 2,643 cells from 19 HWP attachments, excluding two marked as deleted. Preserve cell coordinates, merged ranges, notes and appendix sections, and distinguish administrative forms. Move the processed records' XML-listing-stage `collection_status` and `content_present` under `xml_listing`. Keep raw download records unchanged and distinguish `download_status`, `processing_status`, `extracted_text_present`, `extracted_table_count` and `human_review_status`.
- Protect shared artifacts by redacting 15 OC values in detail links across four search-response XML files. Keep private originals separately and distinguish original hashes, shared-file hashes and redaction records. The public branch excludes the previous local commits containing the authentication value.
- Prepare search text by restoring internal spacing in 16 explicitly listed source terms and normalizing whitespace, while preserving original text and before/after change logs. `tables[].rows_for_search` carries merged parent cells into each applicable row, retaining coordinates, inheritance flags, source identifiers and references to notes/context. Produce 555 rows including headers and form rows from the 32 actual tables; integration with team chunking and retrieval is separate.
- Store confirmed human classifications and image summaries separately and reapply them only when parent MST, attachment ID and source hash match. Retain source-specific time and schedule differences without rewriting originals.
- Include originals, processed JSON, review records and reading instructions in the [handoff folder](https://github.com/kssk3/best-driver-rag-project/tree/feature/jungeun/data-preparation/data/handoff/jungeun/p04-2026-11-24). Preserve the existing raw/processed ignore rules and leave shared schemas, loaders, chunking, retrieval and other owners' code unchanged.

## Validation

- All 37 unit tests using synthetic XML and mocked responses passed on macOS with Python 3.13.14. Syntax, Git whitespace and the four-target configuration checks passed.
- Ruff 0.14.10 in a temporary tool environment passed checks with the options listed above and formatting checks for 14 owned Python files. uv 0.13.9 was also used as a temporary tool; global uv 0.13.5 and team dependency/lock files were unchanged.
- The user collected four body XML files and 21 attachment links through the live API. Codex verified saved files, sources, MST values, effective dates and hashes.
- Codex downloaded 19 attachments and compared body/supplement text against the source XML and table coordinates, merged ranges and text order against HWP-derived structural XML. All 19 actual HWP files were re-extracted offline, and two human-review records were reapplied with their classifications and color summaries preserved.
- Human confirmation covers four specific items: signage classification, six communal-housing bin colors, source-specific food-waste time differences and the handling of conflicting Wirye schedules. It does not establish approval of every cell or verified on-site schedules.
- One local BM25 example using three synthetic documents confirmed query matching before and after known-term restoration. Actual team B/C retrieval, reranking integration and retrieval quality were not validated.

The commands are listed once in the Korean validation section above.

## Remaining work

One user confirmation remains for differences between official web/PDF guidance and map display code for recycling in the Tuesday/Thursday/Sunday area. Every cell has not been individually approved by a person. Acquisition and extraction review do not establish permission for indexing or external model input. Some large tables in HOP previews show overlap warnings; compare the original HWP and extracted structure together.

Shared schemas, loaders, chunking, retrieval and external models remain unconnected. HTML/Selenium collection, getSpot and the complete RAG flow were not validated. The handoff uses an internal draft format that still needs alignment with the shared input contract.
