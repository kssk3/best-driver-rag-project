#!/bin/sh
# 서버 전용 .env를 스크립트와 같은 디렉터리에 최초 한 번 생성한다.
set -eu
cd "$(dirname "$0")"
umask 077
if [ -e .env ] || [ -L .env ]; then
  echo '기존 .env를 사용하세요. 도메인은 LANGFUSE_HOST에 지정합니다.' >&2
  exit 1
fi

tmp=$(mktemp .env.tmp.XXXXXXXX)
trap 'rm -f "$tmp"' EXIT
trap 'exit 1' HUP INT TERM
{
  printf '%s\n' 'LANGFUSE_HOST='
  for key in NEXTAUTH_SECRET SALT ENCRYPTION_KEY POSTGRES_PASSWORD CLICKHOUSE_PASSWORD REDIS_AUTH MINIO_ROOT_PASSWORD; do
    value=$(openssl rand -hex 32)
    printf '%s=%s\n' "$key" "$value"
  done
} > "$tmp"
ln "$tmp" .env
echo '서버용 .env를 생성했습니다. LANGFUSE_HOST에 실제 도메인을 입력하세요.'
