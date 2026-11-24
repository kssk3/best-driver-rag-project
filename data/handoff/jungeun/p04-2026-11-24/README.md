# B팀 P04 데이터 검수 파일

2026-11-24 이정은 / 공유 대상: 양석호와 팀 검토. 원본·전처리 결과·항목별 검수 기록을 담은 PR 검토용 자료.

## 먼저 열 파일

- review/review.html: 원문 미리보기와 추출 표, 최신 사람 검수 기록
- review/review_status.json: 완료·진행 중 항목과 실제 검수 범위
- processed/body/processing_manifest.json: 본문 전처리 목록
- processed/annex/annex_manifest.json: 첨부 추출 목록

## 구성

| 폴더 | 내용 |
| --- | --- |
| raw/ | API 본문 XML4개, 검색 응답 XML4개(OC 인증값 제거 공유본), 출처·버전·해시 manifest |
| raw/attachments/ | 공식 HWP19개와 다운로드 기록; 삭제표시2건은 제외 |
| processed/body/ | 최종 본문 JSON4개와 목록. 조문107개(전체삭제17개 포함), 장제목 포함121단위, 부칙4구획 |
| processed/annex/ | HWP 파싱 XML19개, 추출 JSON19개와 목록. 표32개·셀2643개와 검색용 행555개 |
| review/ | 사람 검수4개 항목의 범위·응답, 재적용 파일, 원문 미리보기와 일정 차이 근거 |
| 저장소 src/ingestion/·scripts/·tests/ | 같은 PR의 수집·전처리 코드와 검사. 이 폴더에 코드 중복 복사 없음 |

본문107개가 모두 현행 답변용이라는 뜻은 아님. 전체삭제17개는 원문 그대로 보존하고 표시함.
법령 API의 본문 XML과 HWP를 도구로 변환한 구조 XML은 출처·형식이 다름.
구청 공식 PDF와 HOP 변환 미리보기 PDF도 구분함.

## 경로와 재처리

모든 문서 JSON의 raw_path는 이 묶음 raw/ 폴더 기준.
첨부 JSON의 extracted_xml은 processed/annex/ 기준.
manifest와 연결된 문서 메타데이터를 함께 읽어야 출처·지역·MST·시행일이 유지됨.
원문파일을 바꾸지 말고 새 버전으로 처리. 각 파일 해시는 bundle_manifest.json 참고.

저장소 루트에서 팀 Python 환경을 준비한 후 원본을 다시 추출할 수 있음. 다음은 저장소 루트 기준 예시:

```zsh
.venv/bin/python -m src.ingestion.clean --manifest data/handoff/jungeun/p04-2026-11-24/raw/manifest.json --output-dir data/processed/documents/new_body_review
python -m src.ingestion.annexes --manifest data/handoff/jungeun/p04-2026-11-24/raw/attachments/manifest.json --output-dir data/processed/documents/new_annex_review --review-overlays data/handoff/jungeun/p04-2026-11-24/review/human_review_overlays.json
```

첨부 재처리는 pyhwp==0.1b15와 six·setuptools가 있는 임시 Python3.13 환경 및 hwp5proc 필요.
검수 재적용 파일은 같은 부모MST·첨부ID·원본해시에만 적용. 원본 변경 시 재검수.
JSON 기존값에 공식 안내의 값을 덮어쓰지 않고 별도 출처로 보존.

## 첨부 상태와 검색용 행 읽기

첨부 JSON은 `jungeun-annex-draft-v2` 초안이다. 기존 최상위 `collection_status`와
`content_present`는 `xml_listing.collection_status`·`xml_listing.content_present`로 이동했다.
이는 lawService의 XML 안에 첨부 본문이 있었는지만 나타낸다. 원본 raw manifest는 변경하지 않았다.
본문 JSON의 `attachments`도 XML 목록 시점의 기록이며 `attachments_scope`에 범위를 명시했다.

- `download_status`: 원본 HWP 확보 상태. 실제 19건 `downloaded`.
- `processing_status`: HWP 구조 추출 결과. 19건 추출, 삭제2건 제외.
- `extracted_text_present`·`extracted_table_count`: 실제 추출 텍스트 유무와 표 수.
- `human_review_status`·`usage_status`: 사람 검수 범위와 색인·외부 모델 이용 상태. 추출 성공과 별개.

원본 `cells[].text`·문단·좌표·병합 정보는 보존했다. 각 표의 `rows_for_search`는 별도 검색용 표현이다.
병합된 상위 품목을 포함한 셀 값을 행마다 연결하고 원래 `cell_id`·좌표·상속 여부를 남긴다.
예를 들어 `2101297_160319453_table-1-row-3`의 신문지 행에 `2. 골판지 외 종이류`도 포함된다.
행 ID는 부모 MST·첨부 ID·표·행으로 구성한다.

검색용 `search_text`는 공백을 정리하고 확인한 16개 용어 내부의 공백만 복원한다.
`폴리\n에틸렌테레프\n탈레이트`는 `폴리에틸렌테레프탈레이트`로 복원하지만
`주소\n전화`는 `주소 전화`로 구분한다. `normalization_changes`에 변경 전후를 남긴다.
한글 바로 뒤 줄바꿈이 있는 원본 셀57개 모두가 단어 분할 오류는 아니며, 전부 붙이지 않았다.
총322개 셀에서 공백 변화가 있고 이 중24개 셀에 명시 용어 복원이 있다.
목록 밖의 단어 분할은 후속 검수 대상이다.

행에 `context_required: true`와 `context_ref: attachment.blocks`를 남겼다.
표의 `section_title`·`deleted_section`, 제목·열 제목·비고·조건·예외와 함께 읽어야 하며
행 문자열만 곧바로 색인하지 않는다.
로컬 BM25 예시에서 용어 검색 일치를 확인했으며 실제 팀 B/C 검색·청킹 연결은 미실행이다.

## 검증 상태

- 단위테스트37개, 문법·공백 검사 통과. 임시 Ruff0.14.10의 명시 옵션 검사와 서식 검사14개 파일 통과.
- 본문·부칙 문자열, 출처·MST·시행일·해시 대조 통과.
- 첨부19개 실제 오프라인 재추출과 검수2건(표지판 분류·색상6개) 재적용 확인.
- 셀 좌표·병합 범위·텍스트 순서 대조 통과. 모든 수치·조건을 사람이 개별 승인한 상태는 아님.
- 이정은 확인: 표지판 분류, 공동주택 수거용기 색상6개, 송파구 배출시간 차이,
  위례동 공식 출처 충돌의 처리 방침. 실제 현장 수거요일을 확정한 기록과 구분.
- 남은 확인: 화목일 권역 재활용 요일의 공식 자료 간 차이 처리 방침.
- 공통 로더·청킹·색인·검색·외부 모델 호출은 미실행. 색인/외부 모델 이용 상태는 미검토.
- 구청 포털의 운영 안내와 조례 원문은 별도 자료. 공식 자료끼리 충돌한 값은 자동 정답으로 단정하지 않음.
- 일정 증거 일부는 도구 출력에서 정규화한 DOM/JS 발췌이며 서버 원본바이트가 아님.
- HOP 대형 표 일부에 겹침 경고가 있어 미리보기만으로 최종 승인하지 않음.

이 파일은 항목별 검수 범위를 설명하며 전체 사람 검수·전체 RAG 완료를 뜻하지 않음.

## Git 포함 범위

이 폴더는 사용자가 XML·JSON도 PR에 포함하도록 요청한 공유 스냅샷이다.
기존 data/raw·data/processed 제외 규칙은 변경하지 않았다.
배출 일정 충돌·사람 검수 대기와 색인/외부 모델 이용 미검토 상태를 그대로 보존한다.

원문 XML에는 수집 당시 줄끝 공백이 포함되어 있다. 이를 지우면 원본 해시가 달라지므로
이 스냅샷의 Git 속성에서 바이트 정규화를 막고 XML 데이터·원문 표시용 검수 HTML·서버 원본 robots.txt의 공백 검사를 제외했다.
소스 코드·문서의 공백 검사는 그대로 유지한다.


## 공유 검색응답의 인증값 제거

`raw/*/search_1.xml` 4개는 응답의 `자치법규상세링크` URL 안에 포함된
OC 인증값만 `REDACTED`로 바꾼 공유본이다(총15곳). 원문 응답 바이트와 같다고
표현하지 않는다. 본문 XML4개와 HWP 원본19개는 이 조치로 변경하지 않았다.

`review/search_response_redactions.json`에 파일별 원본 SHA256·공유 SHA256,
제거 필드·개수와 개인 원본 보관 위치를 남겼다. 인증값 자체는 기록하지 않았다.
개인 원본 검색응답은 Git 제외된 로컬 수집 폴더에만 보존하며 이 묶음에 포함하지 않는다.
`raw/manifest.json`의 `search_responses`는 공유본 기준 경로·해시를 담고,
기존 `raw_path`·`raw_sha256`는 본문 XML의 경로·해시를 그대로 유지한다.
