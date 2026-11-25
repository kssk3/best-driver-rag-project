# 참조 자료

실행 코드가 읽는 작은 공식 참조표를 둔다. `data/raw`·`data/processed`와 달리 Git에 포함한다.

## seoul_dong_map.csv — 서울 행정동·법정동 매핑표

| 항목 | 값 |
| --- | --- |
| 담당 | 이명지 (지역 해석) |
| 출처 | 행정안전부 「행정기관(행정동) 및 관할구역(법정동) 변경내역(2026.10.23. 시행)」 게시물 첨부 `jscode20261111.zip`의 `KIKmix.20261111` |
| 게시물 | https://www.mois.go.kr/frt/bbs/type001/commonSelectBoardArticle.do?bbsId=BBSMSTR_000000000052&nttId=131063 |
| 기준일 | 2026-11-11 (말소코드 미포함본: 현재 유효한 동만) |
| 범위 | 서울특별시 746줄, 행정동 427개, 법정동 467개 |
| 원본 SHA-256 | zip `5b4493acbb3d2a130ffc5a9d8fc2b2e860d1386156a7faef918b065fef91dcde`, KIKmix `1ea170de2965841fe8c373e6a5a4e7e1e17b1ce6dbfdf4ed16c2c880cd462e20` |
| 생성 | `uv run --locked python -m scripts.build_dong_map data/raw/mois-codes/jscode20261111/KIKmix.20261111 data/reference/seoul_dong_map.csv` |

열: `district`(구), `admin_dong`(행정동), `admin_code`(행정동코드), `legal_dong`(법정동), `legal_code`(법정동코드).
한 줄은 행정동 하나와 그 관할 법정동 하나의 짝이다. 행정동 하나가 법정동 여러 개를 관할하면 여러 줄이 된다(예: 서대문구 천연동 → 냉천동·천연동·옥천동·영천동·현저동).

행정구역이 바뀌면 같은 게시판의 최신 `jscode<기준일>.zip`을 받아 위 명령으로 다시 만들고, 이 표의 기준일과 해시를 갱신한다.
