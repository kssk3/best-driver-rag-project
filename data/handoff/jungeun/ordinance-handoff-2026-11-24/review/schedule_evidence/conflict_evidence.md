# 공식 일정 충돌 검수 근거

2026-11-24 읽기 전용 확인. 사용자가 차이가 보이는지 확인받기 위한 자료이며,
사용자에게 어느 쪽이 사실인지 결정하도록 요구하지 않는다.

| 검수 항목 | 공식 HTML·PDF | 공식 지도 | 처리 |
| --- | --- | --- | --- |
| 위례동 일반주택 일반·음식물 | HTML 월수금 / 링크PDF 화목일 | 월수금 | 공식채널 차이 확인 후 conflict_detected |
| 화목일권역 기타재활용·비닐투명PET | 기타 화일 / 비닐투명PET 목 | UI코드: 기타 화목 / 비닐투명PET 일 | 공식채널 차이 확인 후 conflict_detected |

## 증거

- 3153-wirye-dom-excerpt.html: 이전 실제 응답의 HTMLParser 출력에서 보존한 정규화DOM. colspan포함. HTTP원본바이트가 아님.
- 6275-map-recycling-code-excerpt.js: 이전 실제 지도 응답에서 확인한 JS 발췌.
- map-trash-data-excerpt.js: 공개data 응답에서 확인한 위례동MWF·데이터생성시각.
- official-20261014.pdf: 링크된공식PDF원문, SHA256은 conflict_evidence.json에 기재.
- page3.png: PDF3쪽(인쇄4~5쪽) 원문이미지. 위례동 행 확인 가능.

정확한 URL·관찰방식·날짜 의미는 conflict_evidence.json 참조.
HTML 최종수정표시2026-11-19, 지도data생성표시2026-11-23 15:32,
PDF 인쇄발행2025-09와 파일 생성·수정2026-10-14는 각각 의미가 다르다. 동일한 시행일로 취급하지 않는다.

## robots

robots.txt와 robots_review.json 보관.
해당 /www/contents.do, /www/resourceCirculationMap.do,
/www/resourceCirculationMapData.do, /common/downloadAttch2.jsp 경로는 차단목록에 없다.
User-agent:* Crawl-delay:3600. 확인 후 추가 콘텐츠 요청은 하지 않았다.
이전조사에서는 이crawl-delay를 확인하기 전에 여러 페이지를 요청했으므로
이전요청까지crawl-delay준수라고 소급해 기록하지 않는다. 차단우회는 하지 않았다.

현재 보고에는 초기 중간보고의 잘못된 마천2동요일값을 포함하지 않는다.


## 날짜 확인 반영

사용자 지시 ‘적용해’에 따라 날짜의 의미와 출처 시점을 구분했다. 요일 사실을 확정한 승인은 아니다.

| 근거 | 확인한 날짜 | 의미 |
| --- | --- | --- |
| 공식 PDF 목차 발행정보 | 2025-09 | 인쇄 발행일. PDF 2쪽에서 시각 확인 |
| 공식 PDF 메타데이터 | 2026-10-14 09:11:41 KST | 파일 생성·수정일. 발행일과 구분 |
| 송파구 배출안내 HTML3153 | 2026-11-19 | 페이지 최종수정 표시. 2026-11-24 재조회 확인 |
| 공식 지도 공개 데이터 | 2026-11-23 15:32 | 기존 저장 응답의 데이터 생성표시. 화면 코드 수정일·정책 시행일 아님 |

PDF는 2025-09에 발행된 이전 자료다. 그러나 웹·지도 우선순위나 실제 배출요일은
서로 다른 날짜 유형만으로 확정하지 않는다. 요일 변경의 적용일·자료 대체 관계 확인이 남아 있다.
각 출처의 원래 요일 값과 확인한 사람 검수4개 항목은 그대로 보존했다.
날짜 근거: [date_check.json](date_check.json), [공식 PDF 2쪽 발행정보](official-20261014.pdf#page=2).
