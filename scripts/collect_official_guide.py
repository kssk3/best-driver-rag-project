"""서대문구 생활쓰레기 안내를 증빙용 HTML과 표 JSON으로 저장한다."""

import argparse
import json
import re
from datetime import UTC, datetime
from hashlib import sha256
from html.parser import HTMLParser
from importlib.util import find_spec
from os import X_OK, access
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal, NotRequired, TypedDict
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.robotparser import RobotFileParser

SOURCE_URL = "https://www.sdm.go.kr/civil/type/household.do"
ROBOTS_URL = "https://www.sdm.go.kr/robots.txt"
POLICY_URL = "https://www.sdm.go.kr/user/copyright.do"
LICENSE_URL = "https://www.kogl.or.kr/info/licenseType1.do"
USER_AGENT = "TeamB-Recycling-RAG/1.0"
TABLE_CAPTIONS = {"배출요일", "배출방법", "수거대행업체현황"}


class _Artifact(TypedDict):
    sha256: str
    bytes: int


class _GuideManifest(TypedDict):
    document_id: str
    title: str
    district: str
    publisher: str
    source_url: str
    robots_url: str
    robots_user_agent: str
    copyright_url: str
    usage_status: Literal["local_review_only"]
    requested_at: str
    collection_status: Literal["saved", "failed"]
    files: dict[str, _Artifact]
    robots_sha256: NotRequired[str]
    robots_checked_at: NotRequired[str]
    robots_status: NotRequired[Literal["allowed", "denied"]]
    source_fetched_at: NotRequired[str]
    http_last_modified: NotRequired[str | None]
    collected_at: NotRequired[str]
    license: NotRequired[str]
    license_url: NotRequired[str]
    license_scope: NotRequired[str]
    browser_version: NotRequired[str]
    table_count: NotRequired[int]
    error_type: NotRequired[str]


class _GuideCaptureError(RuntimeError):
    """로컬 브라우저 렌더링 실패."""


class _RejectRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(req.full_url, code, "리다이렉트 대상 확인 필요", headers, fp)


def _fetch(url: str, content_type: str, limit: int) -> tuple[bytes, str | None]:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with build_opener(_RejectRedirect()).open(request, timeout=15) as response:
        if (
            response.status != 200
            or response.headers.get_content_type() != content_type
        ):
            raise ValueError(f"HTTP 200 {content_type} 응답이 아닙니다.")
        payload = response.read(limit + 1)
        if not payload or len(payload) > limit:
            raise ValueError("응답이 비어 있거나 크기 한도를 초과했습니다.")
        return payload, response.headers.get("Last-Modified")


class _PageText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _check_license(html: str) -> None:
    parser = _PageText()
    parser.feed(html)
    parser.close()
    text = " ".join(" ".join(parser.parts).split())
    if not re.search(
        r"서대문구청이\(가\)\s*창작한.{0,12}생활쓰레기\s*배출.{0,12}"
        r"저작물은\s*공공누리.{0,8}제\s*1\s*유형\s*:\s*출처\s*표시",
        text,
    ):
        raise ValueError(
            "생활쓰레기 배출 본문의 공공누리 제1유형 표시를 찾지 못했습니다."
        )


def _capture(source: Path, driver_path: Path) -> tuple[str, str, list[dict]]:
    try:
        from selenium import webdriver
        from selenium.common.exceptions import WebDriverException
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as ec
        from selenium.webdriver.support.ui import WebDriverWait
    except ModuleNotFoundError as error:
        raise _GuideCaptureError(
            "uv run --locked --group selenium으로 실행하세요."
        ) from error

    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--disable-background-networking")
    options.add_argument("--proxy-server=http://127.0.0.1:9")
    options.add_argument("--proxy-bypass-list=<-loopback>")
    try:
        service = Service(executable_path=str(driver_path.resolve()))
        with webdriver.Chrome(service=service, options=options) as driver:
            driver.execute_cdp_cmd("Network.enable", {})
            driver.execute_cdp_cmd(
                "Network.setBlockedURLs", {"urls": ["http://*", "https://*"]}
            )
            driver.set_page_load_timeout(15)
            driver.get(source.resolve().as_uri())
            WebDriverWait(driver, 10).until(
                ec.presence_of_element_located((By.CSS_SELECTOR, "table > caption"))
            )
            tables = driver.execute_script("""
                for (const old of document.head.querySelectorAll(
                    'meta[charset], meta[http-equiv="content-type" i]'
                )) old.remove();
                const charset = document.createElement('meta');
                charset.setAttribute('charset', 'utf-8');
                document.head.prepend(charset);
                return [...document.querySelectorAll('table:has(> caption)')].map(table => ({
                    caption: table.caption.textContent.trim(),
                    rows: [...table.rows].map(row => [...row.cells].map(cell => ({
                        raw_text: cell.textContent,
                        kind: cell.tagName.toLowerCase(),
                        row_span: cell.rowSpan,
                        col_span: cell.colSpan,
                    }))),
                }));
            """)
            return driver.page_source, driver.capabilities["browserVersion"], tables
    except (RuntimeError, WebDriverException) as error:
        raise _GuideCaptureError(
            f"Chrome 실행 또는 표 대기 실패 ({type(error).__name__})"
        ) from error


def _preprocess(tables: list[dict]) -> list[dict]:
    selected = []
    captions = set()
    for table in tables:
        caption = " ".join(table["caption"].split())
        # 원문 캡션에는 제목 뒤에 접근성용 열 설명이 포함된다.
        label = "".join(caption.split())
        key = next((name for name in TABLE_CAPTIONS if label.startswith(name)), None)
        if key is None:
            continue
        if (
            key in captions
            or len(table["rows"]) < 2
            or any(not row for row in table["rows"])
        ):
            raise ValueError(f"본문 표 구조 확인 필요: {caption}")
        captions.add(key)
        rows = [
            {
                "source_location": f'표 "{caption}" / 행 {position}',
                "cells": [
                    {**cell, "text": " ".join(cell["raw_text"].split())} for cell in row
                ],
            }
            for position, row in enumerate(table["rows"], start=1)
        ]
        selected.append({"caption": caption, "rows": rows})
    if captions != TABLE_CAPTIONS:
        raise ValueError("안내 본문의 대상 표 세 개를 확인하지 못했습니다.")
    return selected


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _write_artifact(output: Path, name: str, payload: bytes) -> _Artifact:
    (output / name).write_bytes(payload)
    return {"sha256": sha256(payload).hexdigest(), "bytes": len(payload)}


def collect(output: Path, driver_path: Path) -> Path:
    output.mkdir(parents=True, exist_ok=False)
    manifest: _GuideManifest = {
        "document_id": "seodaemun-household-waste-guide",
        "title": "생활쓰레기 배출",
        "district": "서대문구",
        "publisher": "서대문구청",
        "source_url": SOURCE_URL,
        "robots_url": ROBOTS_URL,
        "robots_user_agent": USER_AGENT,
        "copyright_url": POLICY_URL,
        "usage_status": "local_review_only",
        "requested_at": datetime.now(UTC).isoformat(),
        "collection_status": "failed",
        "files": {},
    }
    manifest_path = output / "manifest.json"
    try:
        robots_payload, _ = _fetch(ROBOTS_URL, "text/plain", 100_000)
        robots_artifact = _write_artifact(output, "robots.txt", robots_payload)
        manifest["files"]["robots.txt"] = robots_artifact
        manifest["robots_sha256"] = robots_artifact["sha256"]
        robots = RobotFileParser()
        robots.parse(robots_payload.decode("utf-8-sig").splitlines())
        allowed = robots.can_fetch(USER_AGENT, SOURCE_URL)
        manifest["robots_checked_at"] = datetime.now(UTC).isoformat()
        manifest["robots_status"] = "allowed" if allowed else "denied"
        if not allowed:
            raise ValueError("robots.txt에서 대상 경로 수집을 허용하지 않습니다.")

        raw_html, last_modified = _fetch(SOURCE_URL, "text/html", 2_000_000)
        manifest["source_fetched_at"] = datetime.now(UTC).isoformat()
        manifest["http_last_modified"] = last_modified
        with TemporaryDirectory(prefix="guide-render-") as folder:
            source = Path(folder) / "source.html"
            source.write_bytes(raw_html)
            rendered, browser_version, source_tables = _capture(source, driver_path)
        _check_license(rendered)
        tables = _preprocess(source_tables)

        files = {
            "source.html": raw_html,
            "rendered.html": rendered.encode("utf-8"),
            "processed.json": _json(
                {
                    "source_url": SOURCE_URL,
                    "district": manifest["district"],
                    "source_fetched_at": manifest["source_fetched_at"],
                    "tables": tables,
                }
            ),
        }
        for name, payload in files.items():
            manifest["files"][name] = _write_artifact(output, name, payload)
        manifest["collected_at"] = datetime.now(UTC).isoformat()
        manifest["license"] = "공공누리 제1유형"
        manifest["license_url"] = LICENSE_URL
        manifest["license_scope"] = "생활쓰레기 배출 안내 본문"
        manifest["browser_version"] = browser_version
        manifest["table_count"] = len(tables)
        manifest["collection_status"] = "saved"
    except (OSError, ValueError, _GuideCaptureError) as error:
        manifest["error_type"] = type(error).__name__
        raise
    finally:
        manifest_path.write_bytes(_json(manifest))
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path, help="새 로컬 증빙 폴더")
    parser.add_argument("--driver", type=Path, required=True, help="ChromeDriver 경로")
    args = parser.parse_args()
    if not args.driver.is_file() or not access(args.driver, X_OK):
        parser.error("실행 가능한 ChromeDriver를 지정하세요.")
    if find_spec("selenium") is None:
        parser.error("uv run --locked --group selenium으로 실행하세요.")

    try:
        manifest_path = collect(args.output_dir, args.driver)
    except (OSError, ValueError, _GuideCaptureError) as error:
        parser.exit(1, f"수집 실패 ({error})\n")
    print(f"수집 기록 {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
