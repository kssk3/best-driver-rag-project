#!/bin/sh
set -eu
export LC_ALL=C

invalid_host() {
  echo 'LANGFUSE_HOST에는 프로토콜·포트·경로 없이 DNS 호스트 이름만 입력하세요.' >&2
  exit 1
}

host=${LANGFUSE_HOST:-}
# 절대 도메인 이름의 마지막 점은 레이블 길이에 포함하지 않는다.
name=${host%.}
case "$name" in
  ''|*[!A-Za-z0-9.-]*|.*|*.|*..*) invalid_host ;;
esac
[ "${#name}" -le 253 ] || invalid_host

IFS=.
for label in $name; do
  case "$label" in -*|*-) invalid_host ;; esac
  [ "${#label}" -le 63 ] || invalid_host
done
