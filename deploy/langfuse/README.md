# 팀 서버에서 랭퓨즈 점수 보기

팀 서버 한 곳에 [compose.yaml](compose.yaml)을 배포한다. 팀원은 같은 HTTPS 주소로 로그인해 프로젝트에 올라온 점수를 본다. 웹과 워커는 Langfuse 4.86.0을 사용하고 Caddy가 HTTPS를 처리한다. 데이터베이스와 객체 저장소는 Compose 내부에서만 접근한다. [공식 배포 안내](https://langfuse.com/self-hosting/deployment/docker-compose) · [기준 버전의 구성](https://github.com/langfuse/langfuse/blob/v4.86.0/docker-compose.yml)

## 서버 준비와 기동

1. Docker Engine과 Compose 플러그인이 있는 팀 서버를 준비한다. 팀 도메인의 DNS를 서버로 연결하고 Caddy가 인증서를 발급받도록 TCP 80·443을 연결한다. 이 구성은 두 포트를 Caddy가 직접 사용할 수 있다고 가정한다.
2. 저장소 루트에서 아래 명령으로 서버용 `.env`를 최초 한 번 생성한다. 스크립트는 OpenSSL로 서로 다른 비밀값 7개를 만들고 파일 권한을 `0600`으로 설정한다. 이미 `.env`가 있으면 기존 파일을 사용한다.

```sh
cd deploy/langfuse
sh init-env.sh
```

3. `deploy/langfuse/.env`의 `LANGFUSE_HOST=`에 실제 도메인을 입력한다(예: `LANGFUSE_HOST=langfuse.example.org`). 도메인이 미정이면 이 값은 비워 두고, 도메인이 준비되면 같은 폴더에서 아래 명령을 실행한다. 서버 비밀값은 재기동 때도 유지하며 `.env`와 Docker 볼륨을 백업한다.

```sh
docker compose config --quiet
docker compose up -d
docker compose ps
docker compose logs --tail=50 langfuse-web langfuse-worker proxy
```

4. `https://팀도메인/api/public/health`와 웹 로그인 화면을 확인한다. 관리자가 조직과 프로젝트를 만들고 팀원에게 해당 프로젝트 조회 권한을 부여한다. 점수 조회는 각자의 계정으로 한다. 업로드용 API 키는 해당 서버의 대상 프로젝트에서 발급한 쌍을 사용한다. 기존 키의 발급 서버·프로젝트가 다르면 새 프로젝트에서 발급한다.

## 점수 전송과 확인

업로드를 수행할 컴퓨터의 프로젝트 루트 `.env`에 `LANGFUSE_BASE_URL=https://팀도메인`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`를 설정한다. 서버의 `deploy/langfuse/.env`는 인프라용이다. 아래 예시는 [채점 절차](../../results/README.md)에 따라 숫자 점수가 저장된 폴더를 사용한다.

```sh
uv run --locked --env-file .env python -m scripts.upload_scores \
  --scores results/local/faithfulness-smoke/scores.csv \
  --report results/local/faithfulness-smoke/team-upload-1.csv --upload
```

보고서에서 `accepted`를 확인한 뒤 팀 프로젝트의 **Scores**에서 `faithfulness`와 원래 채점 날짜로 필터링한다. 새로 전송한 점수와 trace에는 실행 유형이 Langfuse의 `environment`로 기록된다. 실제 검색 결과를 비교할 때는 환경 필터에서 `rag`를 선택한다. 고정 근거 실험은 `fixed_evidence`, 합성 데모는 `demo`에서 조회한다. 기존에 환경 없이 업로드한 점수는 기본 환경에서 조회한다. **Score Analytics**에서 선택한 환경의 점수 분포를 확인한다. 개별 값은 보고서의 `trace_id` 및 `score_id`로 대조한다. 입력 검증만 수행해 점수가 비어 있으면 업로드를 건너뛴다. [점수 분석 화면 안내](https://langfuse.com/docs/evaluation/scores/score-analytics)

일시 정지는 서버의 `deploy/langfuse`에서 `docker compose stop`, 재기동은 `docker compose up -d`로 한다. 데이터는 이름 있는 볼륨에 보존된다.
