# 송파구 배출 일정 출처별 적용 범위 검수

2026-11-25 공식 웹 안내, 국가법령정보센터 시행규칙, 기존 PDF·지도 검수 자료를 대조했다. 아래 비교는 개별 출처의 관찰값이다. 배출일을 확정하는 용도로 쓰려면 해당 동과 주택 유형에 적용되는 변경 시행일 또는 안내를 대체한 공식 공지가 필요하다.

| 확인 대상 | 출처별 관찰 | 시행일 및 대체 관계 |
| --- | --- | --- |
| 위례동 **일반주택**, 일반·음식물 배출요일 | 구청 요일표와 기존 지도 공개 데이터는 월·수·금, 2025년 9월 발행 소책자는 화·목·일로 표기한다. 구청 요일표에는 위례동이 공동주택 열에도 별도로 나온다. [구청 배출요일표][guide] · [소책자 3쪽 원문 미리보기][booklet-page] · [원문 비교 기록][existing] | 위례동 일반주택의 요일 변경 시행일과 소책자 안내를 대체한 공지를 확인하지 못했다. 공동주택에 일반주택 값을 적용할 수 없다. |
| 화·목·일 권역 **일반주택**, 기타 재활용품과 폐비닐·투명 페트병 | 구청 요일표와 소책자는 기타 재활용품 화·일, 폐비닐·투명 페트병 목으로 구분한다. 기존 지도 화면 코드 발췌는 각각 화·목과 일이다. 구청 품목 안내도 가락본동·거여1·2동 등 명시된 동의 투명 페트병을 목으로 안내하며, 아파트에는 자체 배출일을 적용한다. [구청 배출요일표][guide] · [구청 재활용품 안내][recycling] · [지도 코드 확인 기록][existing] | 품목 안내는 명시된 동의 투명 페트병을 대조하는 자료다. 지도 화면과 안내의 차이를 해소하는 시행일·변경 공지는 확인하지 못했다. |
| 마천2동 **일반주택**, 음식물 배출시간 | 2020-03-19 시행 문서의 별표 4에서 `마천2`가 포함된 동 묶음은 월·수·금 18~23시다. 별표 제목의 마지막 개정 표시는 2017-04-06이다. 구청 음식물 안내의 일반주택 항목은 지정요일 18~22시로 안내한다. [시행규칙][rule] · [별표 4 원문 미리보기][annex-page] · [구청 음식물 안내][food] | 시행규칙 문서 시행일과 운영안내의 적용일은 따로 확인한다. 해당 주택에 적용되는 시간 변경 시행일과 대체 관계를 확인하지 못했다. |

송파구의회 통합지도 공개 안내의 등록일은 2026-09-14이며, 본문에서 거주지별 배출요일 조회 기능을 안내한다. 이 글에는 위 표의 동별 일정 시행일이나 다른 안내를 대체한다는 설명이 없다. 구청 요일표의 2026-11-19 수정 표시, 지도 공개일·저장 응답 생성 시각, 소책자 발행일·파일 수정일은 각각의 뜻으로 기록한다. [통합지도 공개 안내][launch] · [날짜 검증 기록][dates]

## 근거 재현 위치

- 별표 4와 5는 같은 첨부 `1481479_121237861`에 있다. 마천2동은 별표 4의 `table-2`에서 행 인덱스 2, 셀 `table-2-r2-c0`부터 `c2`까지 대조한다. 원문 검색어는 `마천2`다. 별표 5는 같은 파일의 `table-3`이다. [전처리 별표 JSON][annex-json] · [별표 4 원문 미리보기][annex-page] · [별표와 웹 비교][comparison]
- 소책자 PDF 2쪽 목차 왼쪽의 발행정보 상자에서 2025년 9월 발행 표시를 확인했다. PDF 3쪽(인쇄 4–5쪽) 표에서 위례동은 일반주택 화·목·일 묶음과 아파트 열에 각각 표시된다. [소책자 발행정보][booklet-publication] · [소책자 3쪽 원문 미리보기][booklet-page]
- 구청 재활용품 안내(3164)와 음식물 안내(3161)의 보관 사본은 공식 자료 검토본의 수집 해시와 일치했다. `checked_on`은 두 자료가 확인된 날짜인 2026-11-25다. 의회 안내(6723)는 웹 검색 도구에서 공식 페이지의 등록일과 소개 본문을 대조했다. 세 페이지의 HTML 원문은 이 묶음에 포함되지 않았다. [공식 자료 검토본 JSON][official-source-snapshot] · [의회 안내][launch]
- 11월 24일 검수에는 `robots.txt` 확인 후 해당 검수에서 콘텐츠 요청을 추가하지 않았다고 기록되어 있다. 11월 25일 로컬 사본에 표시된 파일 수정 시각은 3164가 17:34:34, 3161이 17:35:56(KST)이다. 정확한 HTTP 요청 시각은 기록에서 확인되지 않아 이날의 `Crawl-delay: 3600` 준수 여부는 미확인으로 남긴다. 이번 재검수에서 구청 안내는 저장 사본으로 대조했다. [11월 24일 수집 접근 기록][robots]

[guide]: https://www.songpa.go.kr/www/contents.do?key=3153
[recycling]: https://www.songpa.go.kr/www/contents.do?key=3164
[food]: https://www.songpa.go.kr/www/contents.do?key=3161
[rule]: https://www.law.go.kr/LSW/ordinInfoP.do?ordinSeq=1481479
[launch]: https://www.songpa.go.kr/tv/songpaTvList.do?categoryNo=99&key=3494&songpatvNo=6723
[existing]: ../../data/handoff/jungeun/ordinance-handoff-2026-11-24/review/schedule_evidence/conflict_evidence.md
[comparison]: ../../data/handoff/jungeun/ordinance-handoff-2026-11-24/review/schedule_evidence/comparison.md
[dates]: ../../data/handoff/jungeun/ordinance-handoff-2026-11-24/review/schedule_evidence/date_check.json
[annex-json]: ../../data/handoff/jungeun/ordinance-handoff-2026-11-24/processed/annex/1481479_121237861.json
[annex-page]: ../../data/handoff/jungeun/ordinance-handoff-2026-11-24/review/previews/1481479_121237861_p2_0.png
[booklet-page]: ../../data/handoff/jungeun/ordinance-handoff-2026-11-24/review/schedule_evidence/page3.png
[robots]: ../../data/handoff/jungeun/ordinance-handoff-2026-11-24/review/schedule_evidence/robots_review.json
[official-source-snapshot]: ../../src/rewrite_dictionary/official_source_snapshot.json
[booklet-publication]: ../../data/handoff/jungeun/ordinance-handoff-2026-11-24/review/schedule_evidence/official-20261014.pdf#page=2
