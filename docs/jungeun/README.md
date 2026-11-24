# 이정은 수집·전처리 작업

Python 3.13.14, 통합 기준 dev. 담당 내부 데이터 형식이며 공통 RAG 규격과의
연동은 미실행이다. 수집·추출 완료와 사람의 조건 검수를 구분한다.

## 담당 범위

| 파일 | 역할 |
| --- | --- |
| src/ingestion/collect.py | P01·P02 법령 API 수집과 출처·버전 확인 |
| src/ingestion/source_review.py | API·문서 이용조건 검토 기록 검사 |
| scripts/collect.py | 수집 실행 진입점 |
| src/ingestion/clean.py | P04 본문·부칙 분리와 원문 조건 보존 |
| src/ingestion/annexes.py | P04 공식 첨부 다운로드, HWP 표·문단 추출, 검수 재적용 |
| src/ingestion/search_preparation.py | P04 검색용 공백·용어 표기 정리와 병합 셀의 행별 연결 |
| src/ingestion/spots.py | P03 getSpot — 기존 뼈대 |
| src/query/aliases.py, rewrite.py | P05·P06 별칭·질문 정제 — 기존 뼈대 |

로더·청킹·색인, 공통 contracts/config/runtime/pipeline과 다른 담당자의 코드는
변경하지 않았다. HTML/Selenium 수집과 getSpot은 구현하지 않았다.
configs/query, prompts/query와 관련 테스트·표본 폴더는 이후 작업용 빈 위치다.

## 수집 실행

팀 저장소 루트에서 실행한다. OC는 LAW_OC 환경변수 또는 비공개 입력으로 전달한다.
설정 예시에는 OC 값이 없다.

```zsh
.venv/bin/python -m scripts.collect --config configs/collection/law_collection.example.json --check
.venv/bin/python -m scripts.collect --config configs/collection/law_collection.example.json
```

--check는 검토 기록만 확인하며 요청·인증값 입력·저장을 하지 않는다.
현재 예시는 이정은이 2026-11-24 확인한 4건의 검토 기록이다.
재검토 기한 2027-01-01은 OC 실제 만료일과 다르다. 다른 사용자는 자신의 API 승인
범위와 이용조건을 확인한 뒤 사용한다. 승인은 색인·외부 모델 이용 승인과 구분한다.

본문 수집은 제목 공백을 제외한 정확 일치와 reviewed_mst를 확인한다.
실행별 폴더를 만들고 XML 원본·해시·출처·검토 기록을 manifest.json에 남긴다.
이 명령은 본문 XML의 첨부 링크만 기록한다. 전체 별표 검색이나 첨부 다운로드는
수행하지 않는다. 첨부 다운로드 함수는 별도의 검토 기록을 요구한다.

## 확인한 결과

사용자 수집 실행 ID: `e783d23192ac49dc82ba05f5b31b0667`.

| 문서 | MST | 조문 | 장 제목 포함 단위 | 첨부 링크 |
| --- | --- | ---: | ---: | ---: |
| 서대문구 조례 | 2101297 | 52 | 59 | 9 |
| 서대문구 시행규칙 | 2101385 | 9 | 9 | 9 |
| 송파구 조례 | 2053883 | 38 | 45 | 2 |
| 송파구 시행규칙 | 1481479 | 8 | 8 | 1 |
| 합계 | | 107 | 121 | 21 |

삭제 조문17개(6/1/8/2)도 위 조문 수에 포함하며 별도 표시하여 보존한다.
제목이 비어 있는 삭제 조문과 활성 조문의 일부 항·호 삭제를 구분하는 회귀 검사를 추가했다.
Codex가 부칙 4구획과 제개정이유 XML을 본문과 분리했다.
첨부는 삭제 표시 2건을 제외하고 19개 파일을 확보했다.
HWP에서 표 32개·셀 2,643개를 추출했고 행정서식 8건을 별도 분류했다.
이 표에서 병합 셀을 반영한 검색용 행 555개를 만들었다. 헤더·서식 행도 포함한
추출 개수이며, 답변용 청크 수나 사람이 승인한 행 수가 아니다.
본문·부칙 문자열, 출처·MST·시행일·해시와 셀 좌표·병합 범위·텍스트 순서를 대조했다.

## 첨부 상태와 검색용 표현

처리된 첨부 JSON은 `jungeun-annex-draft-v2` 형식이다. 원본 다운로드 기록은
수정하지 않고, XML 목록 단계 정보와 HWP 파일 처리 결과를 구분했다.

| 필드 | 의미 |
| --- | --- |
| xml_listing.collection_status | XML 목록 수집 시점의 링크 확보 상태 |
| xml_listing.content_present | 해당 XML 목록 항목에 별표 본문 텍스트가 있었는지 |
| download_status | 별도 첨부 HWP 파일 확보 상태 |
| processing_status | HWP 구조 추출의 성공·실패·제외 상태 |
| extracted_text_present | 추출한 HWP 문단 또는 셀에 텍스트가 있는지 |
| extracted_table_count | 추출한 HWP의 표 개수 |
| human_review_status | 사람이 실제 확인한 범위의 상태 |
| usage_status | 색인·외부 모델 이용 검토 상태 |

처리본의 최상위 `collection_status`·`content_present`는 `xml_listing` 아래로
옮겼다. 예를 들어 XML은 `link_only`·본문 없음이어도 HWP는 `downloaded`이고
`extracted_text_present=true`일 수 있다. 사람 검수나 이용 승인도 이 값에서 추론하지 않는다.

`normalize_search_text()`는 명시한 원문 용어 16개의 내부 공백을 복원하고 검색용
공백을 정리한다. 동의어 치환이나 임의 형태소 결합은 하지 않는다. 원문 `text`와
셀 `paragraphs`를 보존하면서 `search_text`와 변경 전·후 로그를 별도로 만든다.
예: `폴리\n에틸렌테레프\n탈레이트` → `폴리에틸렌테레프탈레이트`.

`tables[].rows_for_search`는 병합된 부모 셀을 각 해당 행에 연결한다.
셀 원점·병합 범위·상속 여부·원본 셀 ID와 부모 MST·첨부 ID를 보존한다.
행의 `context_ref=attachment.blocks`, `context_required=true`를 통해 별표 제목·
비고·각주도 함께 읽도록 한다. 행 텍스트만 떼어 조건을 확정하지 않는다.
이 표현을 팀 청킹·검색기에 연결하는 작업은 남아 있다.

## 재현과 경로 기준

본문 예시. 기존 출력 폴더가 있으면 중단하므로 재실행에는 새 경로를 지정한다.

```zsh
.venv/bin/python -m src.ingestion.clean --manifest data/raw/documents/law_runs/e783d23192ac49dc82ba05f5b31b0667/manifest.json --output-dir data/processed/documents/new_body_review
```

원본 경로는 수집 manifest.json이 있는 실행 폴더 기준이다.
문서 메타데이터와 units를 함께 전달하며, raw_text는 원문 그대로,
text는 앞뒤 공백만 제거한다. 항·호·예외·개정 문구를 삭제하지 않는다.
과거 시행일·경과조치가 섞인 부칙은 현행 일반 배출 기준으로 일괄 적용하지 않는다.

첨부 추출에는 pyhwp 0.1b15, six, setuptools가 있는 Python 3.13 환경과
hwp5proc 명령이 필요하다. 팀 pyproject/uv.lock은 변경하지 않았다.
수집된 첨부의 원본 경로도 같은 수집 실행 폴더 기준이다.

```zsh
python -m src.ingestion.annexes --manifest data/raw/documents/law_runs/e783d23192ac49dc82ba05f5b31b0667/attachments/manifest.json --output-dir data/processed/documents/new_annex_review --review-overlays data/processed/documents/e783d23192ac49dc82ba05f5b31b0667_review/human_review_overlays.json
```

검수 재적용 파일은 사람이 확인한 분류·그림 요약을 원본 해시와 함께 저장한 자료다.
부모 MST·첨부 ID·SHA256이 모두 일치할 때만 허용한 검수 필드를 적용한다.
중복·미일치·잘못된 값은 오류로 중단한다. 원본이 바뀌면 재검수한다.
검수 파일을 지정하지 않으면 새 추출 결과는 검수 대기다.
그림 자체는 원본 HWP에 보존하며 그림의 의미를 무조건 자동 추출하지 않는다.

## 사람 검수와 현재 제한

이정은 확인 범위는 로컬 review_status.json에 항목별로 기록했다.

- 서대문구 조례 별표6: 판매소 표지판 분류, 품목별 배출방법 검색에서 제외.
- 서대문구 시행규칙 별표1: 공동주택 일반용기 품목·색상 6개 일치 확인.
- 송파구 일반주택 음식물 시간: 시행규칙18~23시와 구청 안내18~22시의 차이 확인.
- 위례동 일반주택 일정: 공식 자료 간 충돌 처리 방침 동의. 현장 요일 확정 아님.

화목일 권역의 재활용 요일도 공식 웹/PDF와 지도 표시 코드에 차이가 있어
사용자 확인을 진행 중이다. 이를 확인 완료로 기록하지 않았다.
전체 2,643개 셀을 사람이 개별 승인한 상태로 표현하지 않는다.
HOP 미리보기는 공식 배포 PDF가 아니며 대형 표 일부에 겹침 경고가 있었다.
공식 포털의 권리·운영 정보는 조례 원문과 구분해 기록한다.
로더 연결·청킹·색인·외부 모델 입력·검색 검증은 미실행이다.

## 검사와 인계

```zsh
.venv/bin/python -m pytest tests -q
.venv/bin/python -m compileall -q src scripts app.py
git diff --check
```

단위 테스트37개, 문법·공백 검사 통과. 테스트는 합성 XML과 모의 외부 응답을
사용하며 실제 API 실행과 구분한다. 실제 첨부19개를 오프라인으로 재추출했고
사람 검수2건을 같은 원본 해시에 재적용하여 분류·색상6개 보존을 확인했다.
Ruff 0.14.10 임시 도구로 담당 Python 14개 파일의 검사와 포맷 검사를 통과했다.
검사 옵션은 `--select E4,E7,E9,F,I --target-version py313 --line-length 88`이다.
대상은 수집 진입점1개·ingestion 담당 모듈5개·관련 테스트8개다.
uv 0.13.9도 임시 도구로 사용했다. 전역 uv 0.13.5와 팀 의존성·잠금 파일은 바꾸지 않았다.
합성 문서3개로 구성한 로컬 BM25 예제1건은 용어 복원 후 질의 매칭을 확인한
검사다. 실제 팀 B/C 검색·재정렬·전체 검색 품질 검증으로 해석하지 않는다.
수정 후 본문 결과는 수집 실행ID 뒤 _body_v4, 첨부는 _annex_search_v3 폴더에 새로 저장했다.
본문·첨부 원본, 전처리 JSON, 출처·변경·검수 기록을 함께 인계할 계획이다.
기존 data/raw·data/processed 원본과 생성물은 계속 Git 제외 상태다.
사용자 요청에 따라 PR 공유용 XML·HWP·JSON·검수 스냅샷을 저장소 경로
`data/handoff/jungeun/p04-2026-11-24/`에 별도로 준비했다.
해당 브랜치에 포함한 공유 스냅샷이며, 원격 반영 후 같은 저장소 경로에서 확인한다.
기존 공유본·문서는 로컬 커밋으로 구분했다. 리뷰 수정본의 코드는 bundle_manifest의 파일별 해시로 확인한다.
원격 반영과 PR 발행은 사용자가 직접 진행한다.
이정은 작업 가이드와 실습 파일은 상위 개인 폴더에 보존했다.

PR 초안은 [석호 PR 스타일 기준](pr_style_reference.md)을 따른다.
PR 발행은 사용자가 직접 한다. 커밋·푸시·외부 전달 상태를 별도로 보고한다.

공유 검색응답 XML4건의 상세 링크에는 API가 되돌려 넣은 OC가 있어 공유본에서 가렸다.
개인 원본은 Git 제외 경로에 보존하고 원본·공유본 해시와 가림 기록을 함께 남긴다.
공개 브랜치는 해당 인증값이 담긴 이전 로컬 이력을 포함하지 않는다.
