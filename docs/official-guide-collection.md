# 공식 웹 안내 한 건 수집

로컬에 설치된 Chrome과 버전이 맞는 ChromeDriver를 지정한다. 저장소 루트에서 실행한다.

```sh
uv run --locked --group selenium python -m scripts.collect_official_guide \
  results/local/seodaemun-household-guide --driver /path/to/chromedriver
```

서대문구청의 [생활쓰레기 배출 안내](https://www.sdm.go.kr/civil/type/household.do) 한 건을 수집한다. 먼저 `robots.txt`의 대상 경로를 확인한다. 허용된 HTML 응답을 로컬 파일로 열고 Selenium으로 Chrome의 DOM을 읽는다. 브라우저의 HTTP·HTTPS 하위 리소스 요청을 차단한다. 안내 본문에 공공누리 제1유형이 표시되어 있는지 확인한다. [서대문구 저작권정책](https://www.sdm.go.kr/user/copyright.do)

새 출력 폴더에서 다음 파일을 확인한다.

- `robots.txt`는 접근 규칙의 HTTP 응답 바이트다. 경로가 차단된 실행에도 이 파일과 판정 기록을 남긴다.
- `source.html`은 페이지의 HTTP 원문 바이트다.
- `rendered.html`은 Selenium이 읽은 DOM이다. UTF-8로 저장하고 HTML 문자 인코딩 선언도 UTF-8로 정리한다.
- `processed.json`은 본문 표 세 개의 행별 위치, 셀 원문, 공백을 정리한 표현과 `rowspan`·`colspan` 값이다.
- `manifest.json`은 출처, 접근 판정, 수집 시각, 이용 조건과 네 파일의 크기·SHA-256을 기록한다. 성공은 `collection_status`가 `saved`이고 네 파일의 해시가 일치하는 경우다.

실제 검증 표본의 표 3개와 셀 28개는 HTTP 원문에 이미 있었으며 병합 셀은 0개였다. Selenium으로 이 정적 HTML의 로컬 렌더링과 DOM 추출을 확인했다. 브라우저의 HTTP·HTTPS 요청을 차단하므로 원격 AJAX 데이터는 이 수집 경로의 범위 밖이다. 병합 범위 보존은 별도의 오프라인 테스트 입력으로 확인한다. 기존 검증 기록의 `robots_sha256`은 당시 기록이며 `robots.txt` 원문 저장은 새 실행부터 적용한다.

수집물과 전처리 결과는 로컬 검토용이다. 조례 API·HWP 전처리와 별도 실행하며 기본 검색 및 모델 입력에는 연결하지 않는다.
