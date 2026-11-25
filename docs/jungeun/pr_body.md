## 요약

PR #8 후속 검토에서 확인한 HWP 글자 겹침 문자 누락, 별지 구획·삭제 분류, 테스트 기본 인코딩 의존을 보완했다. PR #9가 병합된 최신 `dev`(`0328e8f`)를 반영했으며, 정은 담당 수집·전처리 코드와 자료·검수 문서만 변경했다.

## 주요 변경

- 비어 있는 TCPSControl 본문 대신 `textlength`의 BSTR 원문을 보존. 기존 자식 본문 우선, 임의 번호·글리프 치환 제외.
- 별표·별지 및 가지번호 제목을 인식해 서식 8건의 구획 메타데이터를 정정. 삭제 별지 다음 활성 서식의 삭제 상태 초기화.
- 기존 테스트 3파일의 읽기·쓰기 10곳에 UTF-8 명시, 명시 로드 방식의 CP949 모사 도구와 회귀 검사 추가.
- PDF 인쇄 발행일·파일 속성·웹 수정일·지도 생성일을 구분. 송파구 별표4의 마지막 개정 표시(2017-04-06)와 시행규칙 문서 시행일(2020-03-19)도 구분.
- Yi 음절·PUA 원문 및 TAB 6개의 기존 공백 표현을 별도 검수 기록에 명시.

## 변경 전후 예시

대상 `2053883_154690993.json`, 원문 위치 `blocks[0]`. 원문 `별지1 <삭제 2014.9.25.>`와 해당 위치·부모 MST·첨부 ID는 그대로다.

```jsonc
// 변경 전
{"section_title": "", "deleted_section": false}
// 변경 후
{"section_title": "별지1 <삭제 2014.9.25.>", "deleted_section": true}
```

원문 ID·위치와 JSON 필드 이름·자료형은 변경하지 않았다. 변경된 상태는 서식 8건의 구획 제목 142블록·10표, 삭제 구획 3블록이며 상세 대상은 `review/annex_section_review.json`에 기록했다. 사람 검수 상태와 `usage_status`는 변경하지 않았다.

## 참고사항

- `chunk_id`는 공통 청킹 단계에서 생성. 이번 수집·전처리 단계에서는 생성하지 않는다.
- `160561037`: 색상 6개·공동주택 일반용기 적용 범위·원문 위치 보존. 빈 행·원문 셀은 변경하지 않았다.
- `160319461`: 표지판 원문 보존, 품목 배출 검색에서 제외.
- 위례동 HTML·PDF의 서로 다른 요일과 출처는 별도 관찰 사례로 유지. 실제 수거요일 확정 아님.
- 내용 검수와 외부 모델 이용 상태를 구분. 기존 사람 검수 4항목·이용 미검토 상태 유지.
- 공통 로더·청커·XML→HTML·계약·의존성·CI 코드는 최신 dev와 동일.

## 검증

- Python 3.13.14: 저장소 전체 335개, 전처리 65개, CP949 파일 입출력 모사 65개 통과.
- 새 구획 회귀 검사 19개: 기존 함수에서는 10실패·9통과, 수정 후 19통과.
- 담당 Python 17파일 Ruff 검사·서식 검사와 Git 공백 검사 통과.
- 원문 XML·HWP·구조 XML, 셀·좌표·병합·원문 ID·표/행 ID 및 검수 범위 보존 대조.
- 최신 공통 로더는 46문서, 색인 대상 청커는 HTML/JSON 각 557개 생성. 색인 대상 원문·청크 ID·위치 불변을 대조. 외부 모델·API 호출 및 실제 검색 평가와 구분.

```sh
python -m pytest tests -q
PYTHONPATH=tests/fixtures/ingestion:. python -m pytest -p cp949_path_plugin tests/unit/ingestion -q
git diff --check origin/dev
```

## 남은 제약

공통 XML→HTML 경로에는 TCPS 20개·40코드포인트 누락(서식 2건)과 별지 구획 미인식(서식 8건)이 남는다. 해당 서식은 색인 제외 대상이다. 공통 코드는 수정하지 않았고, 담당자의 추가 작업을 전제하지 않는 재현·영향 기록만 준비했다: [HTML 미해결 기록](docs/jungeun/html_tcps_handoff.md).

실제 Windows·폰트 표시·번호 글리프 의미, 전체 사람 검수, 정책 적용일·출처 대체 관계, 실제 검색·외부 모델 이용 검토는 미완료다. 구청 소책자 원본·쪽 이미지의 공개 공유 조건도 미확인으로 표시했으며 로컬 보관을 재배포 승인으로 해석하지 않는다.

발행정보의 근거는 공식 PDF 2쪽 목차 왼쪽 녹색 상자와 날짜 검증 기록에 남겼다. 발행정보 쪽 이미지는 로컬 검토본에 보관했다.

관련 자료는 #8, #9 및 [인계 자료](data/handoff/jungeun/ordinance-handoff-2026-11-24/README.md)에서 확인할 수 있다.

---

## Summary

Address HWP character-composition loss, form-section/deletion classification and default-encoding dependence identified after PR #8. Incorporate PR #9's latest dev (`0328e8f`), changing only Jungeun's collection/preprocessing code, data and review documents.

## Changes

- Preserve the TCPSControl BSTR payload when rendered content is empty; prefer existing child content without inferred number/glyph substitutions.
- Recognize annex/form headings and branch numbers. Correct section metadata in eight forms and reset deletion at each active form.
- Specify UTF-8 in ten I/O calls across three existing test files; add explicit CP949 simulation and regression checks.
- Distinguish publication, file, web and map dates, including the annex's last-amendment display from the document's effective date.
- Record unresolved Yi/PUA codepoints and the existing six TAB-to-space representations separately.

## Before/after example

The shared example above targets `2053883_154690993.json`, `blocks[0]`. Its text, source location, parent MST and attachment ID remain unchanged. Existing field names and types are preserved. Changed classification metadata covers 142 paragraph/table blocks, ten table titles and three deleted blocks across eight forms. The audit lists each target. Human review and `usage_status` remain unchanged.

## Notes

- Common chunking creates `chunk_id`; collection/preprocessing does not.
- Preserve attachment `160561037`'s six colors, apartment general-bin applicability and source location; no blank-row or source-cell changes.
- Retain signage `160319461` while excluding it from item-disposal retrieval.
- Keep Wirye HTML/PDF observations and sources separate without choosing the actual schedule.
- Keep four human-review items separate from unreviewed external-model usage.
- Common loaders, chunkers, XML-to-HTML, contracts, dependencies and CI match latest dev.

## Validation

Python 3.13.14: 335 repository tests and 65 ingestion/CP949-simulation tests passed. The 19 section regressions previously yielded ten failures and nine passes; all 19 now pass. Ruff checks/formatting cover 17 owned Python files. Verify original bytes, text, geometry, identities and review boundaries. Reproduction commands are shared above. Offline loading produced 46 documents and 557 eligible chunks per format; eligible IDs and locations remained stable. This is separate from external-model/API execution and retrieval evaluation.

## Remaining limitations

Common XML-to-HTML still omits 20 TCPS controls/40 codepoints in two forms and misses form sections in eight forms. These forms are excluded from indexing. This PR leaves common code unchanged and records reproduction/impact without assigning further work to Seokho; see the linked HTML limitation note.

Native Windows/font rendering, number-glyph interpretation, exhaustive human review, effective dates/source supersession, real retrieval and external-model usage remain unverified. Distribution conditions for the district booklet and page images are also unreviewed; local evidence storage does not establish redistribution permission. The date record points to the green publication box on page two of the official booklet. The captured page remains in the local review copy. Related references and the handoff link are shared above.
