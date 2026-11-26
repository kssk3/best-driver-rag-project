# 이정은 PR 작성 기준

2026-11-24 사용자 지시: 석호의 실제 GitHub PR을 읽고 같은 스타일 적용.
실제 참고한 PR은 작성자 Cocode96, feature/seokho/* 브랜치의 다음 2건이다.

- [PR #6: Python 3.13 환경과 담당별 파일 뼈대 준비](https://github.com/kssk3/best-driver-rag-project/pull/6)
- [PR #5: RAG 초기 폴더 구조 구성](https://github.com/kssk3/best-driver-rag-project/pull/5)

최신 PR #6을 중심으로 다음 구성을 따른다.

1. 한글 Conventional Commits 제목. 이번 범위의 제목 후보:
   `feat(ingestion): 자치법규 수집과 조건 보존 전처리 추가`
2. 요약: 문제와 결과를 한 문단으로 설명. 대상 브랜치 dev.
3. 주요 변경: 수집·전처리·검수·문서별 실제 변경과 영향.
4. 검증: 실행 환경과 실제 관찰 결과, 주요 명령은 한 번만 기재.
5. 남은 문제: 기능·현장 사실·팀 통합 검증의 미확인 범위를 구분.
6. 구분선 이후 Summary / Changes / Validation / Remaining work 순서의
   같은 의미 영어 번역. 코드와 명령 블록은 반복하지 않음.

PR #5의 표 형태 검증은 비교할 검사 항목이 많을 때 참고한다.
저장소 PR 템플릿과 대조했고 실제 석호 PR 구성에 맞춘다.
기존 PR의 담당자·작업량·검증 수치는 이번 작업의 사실로 복사하지 않는다.
확인 목록은 수행한 항목만 체크하고 관련 이슈가 없으면 빈 close 문구를 남기지 않는다.
외부 발행·push·병합 상태와 로컬 초안 상태를 구분한다.
