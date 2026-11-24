# Copyright (c) 2026 이정은 (Jungeun Lee)
"""이정은 담당 법령 수집 명령. python -m scripts.collect로 실행한다."""

import argparse
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from getpass import getpass
from pathlib import Path

from src.ingestion.collect import (
    LawClient,
    check_reviews,
    collect_document,
    read_config,
)

LOGGER = logging.getLogger(__name__)


# 1. 실행 옵션과 설정 확인
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--check", action="store_true", help="검토만 확인하고 요청·저장은 하지 않음"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    # 검토 통과 후 인증값 입력
    try:
        config = read_config(args.config.resolve())
        decisions = check_reviews(config)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        LOGGER.error("설정 또는 API 접근 검토 미통과. 근거·기한·필드를 확인하세요.")
        return 1
    for target, reason in decisions:
        LOGGER.info("%s: %s", target["document_id"], reason or "수집 검토 통과")
    # --check: 요청·저장 없이 검사 종료
    if args.check:
        return int(any(reason for _, reason in decisions))
    if not any(not reason for _, reason in decisions):
        LOGGER.error("검토를 통과한 문서가 없어 요청하지 않았어요.")
        return 1
    # 2. 인증값 입력
    oc = (os.getenv("LAW_OC") or getpass("법제처 API 인증값(OC): ")).strip()
    if not oc:
        LOGGER.error("인증값이 필요해요.")
        return 1
    # 3. 실행별 저장 폴더 준비
    started_at = datetime.now(timezone.utc).isoformat()
    run_id = uuid.uuid4().hex
    folder = config["output_path"] / run_id
    folder.mkdir(parents=True, exist_ok=False)
    client = LawClient(oc, config["timeout_seconds"], config["interval_seconds"])
    records = []
    # 4. 문서별 수집과 결과 기록
    for target, reason in decisions:
        started = time.monotonic()
        record = {"document_id": target["document_id"], "collection_status": "blocked"}
        if reason:
            record["reason"] = reason
        else:
            try:
                record = collect_document(
                    client, target, folder / target["document_id"]
                )
            except (ValueError, RuntimeError, OSError) as error:
                # 인증값 노출 방지를 위해 오류 종류만 기록
                record.update(
                    collection_status="error", error_type=type(error).__name__
                )
        record["elapsed_ms"] = round((time.monotonic() - started) * 1000)
        records.append(record)
        LOGGER.info("%s: %s", target["document_id"], record["collection_status"])
        # 문서별 실행 기록 갱신
        (folder / "manifest.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "started_at": started_at,
                    "api_access_review": config["api_access"],
                    "records": records,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    LOGGER.info("실행 기록: %s", folder / "manifest.json")
    # 종료코드: 전체 성공 0, 보류·실패 1
    return int(any(r["collection_status"] != "body_saved" for r in records))


# 직접 실행 시 시작
if __name__ == "__main__":
    raise SystemExit(main())
