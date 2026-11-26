"""공식 안내 수집의 파일 계약을 네트워크와 브라우저 없이 확인한다."""

import json
from hashlib import sha256
from pathlib import Path
from unittest.mock import Mock, call

import pytest

from scripts import collect_official_guide as guide

_ALLOWED_ROBOTS = b"\xef\xbb\xbfUser-agent: *\r\nDisallow: /admin/\r\n"
_DENIED_ROBOTS = b"User-agent: *\r\nDisallow: /civil/\r\n"
_RAW_HTML = '<meta charset="euc-kr"><table><caption>배출요일</caption></table>'.encode(
    "euc-kr"
)
_RENDERED_HTML = (
    '<meta charset="utf-8"><p>서대문구청이(가) 창작한 생활쓰레기 배출 저작물은 '
    "공공누리 제1유형: 출처표시 조건에 따라 이용할 수 있습니다.</p>"
)


def _cell(raw: str, *, kind: str = "td", row_span: int = 1, col_span: int = 1) -> dict:
    return {"raw_text": raw, "kind": kind, "row_span": row_span, "col_span": col_span}


def _tables() -> list[dict]:
    return [
        {
            "caption": "배출요일    열 설명",
            "rows": [
                [_cell(" 배출요일 ", kind="th", col_span=2)],
                [_cell("월·수·금", row_span=2), _cell("연희동")],
                [_cell("천연동")],
            ],
        },
        {
            "caption": "배 출 방 법   열 설명",
            "rows": [[_cell("구분", kind="th")], [_cell("배출 방법")]],
        },
        {
            "caption": "수거 대행업체 현황   열 설명",
            "rows": [[_cell("업체", kind="th")], [_cell("수거 업체")]],
        },
    ]


def test_preprocess_preserves_cell_text_and_merged_spans():
    first_table = guide._preprocess(_tables())[0]

    assert first_table["caption"] == "배출요일 열 설명"
    header = first_table["rows"][0]
    assert header["source_location"] == '표 "배출요일 열 설명" / 행 1'
    assert header["cells"] == [
        {
            "raw_text": " 배출요일 ",
            "text": "배출요일",
            "kind": "th",
            "row_span": 1,
            "col_span": 2,
        }
    ]
    assert first_table["rows"][1]["cells"][0]["row_span"] == 2
    assert [cell["text"] for cell in first_table["rows"][2]["cells"]] == ["천연동"]


def test_collect_records_robots_and_reproducible_artifacts(tmp_path, monkeypatch):
    output = tmp_path / "capture"
    driver_path = tmp_path / "chromedriver"
    fetch = Mock(side_effect=[(_ALLOWED_ROBOTS, None), (_RAW_HTML, None)])
    monkeypatch.setattr(guide, "_fetch", fetch)

    def capture(path: Path, driver: Path) -> tuple[str, str, list[dict]]:
        assert path.read_bytes() == _RAW_HTML
        assert driver == driver_path
        return _RENDERED_HTML, "test-browser", _tables()

    monkeypatch.setattr(guide, "_capture", capture)
    manifest_path = guide.collect(output, driver_path)

    assert fetch.call_args_list == [
        call(guide.ROBOTS_URL, "text/plain", 100_000),
        call(guide.SOURCE_URL, "text/html", 2_000_000),
    ]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["collection_status"] == "saved"
    assert manifest["source_url"] == guide.SOURCE_URL
    assert manifest["robots_status"] == "allowed"
    assert manifest["robots_user_agent"] == guide.USER_AGENT
    assert manifest["robots_sha256"] == sha256(_ALLOWED_ROBOTS).hexdigest()
    assert manifest["browser_version"] == "test-browser"
    assert manifest["table_count"] == 3
    assert manifest["http_last_modified"] is None
    assert set(manifest["files"]) == {
        "robots.txt",
        "source.html",
        "rendered.html",
        "processed.json",
    }
    for name, record in manifest["files"].items():
        payload = (output / name).read_bytes()
        assert record == {"sha256": sha256(payload).hexdigest(), "bytes": len(payload)}
    assert (output / "robots.txt").read_bytes() == _ALLOWED_ROBOTS
    assert (output / "source.html").read_bytes() == _RAW_HTML
    assert (output / "rendered.html").read_text(encoding="utf-8") == _RENDERED_HTML
    processed = json.loads((output / "processed.json").read_text(encoding="utf-8"))
    assert processed["source_url"] == manifest["source_url"]
    assert processed["source_fetched_at"] == manifest["source_fetched_at"]
    assert processed["tables"] == guide._preprocess(_tables())


def test_denied_robots_is_recorded_before_any_content_request(tmp_path, monkeypatch):
    output = tmp_path / "denied"
    fetch = Mock(return_value=(_DENIED_ROBOTS, None))
    capture = Mock()
    monkeypatch.setattr(guide, "_fetch", fetch)
    monkeypatch.setattr(guide, "_capture", capture)

    with pytest.raises(ValueError, match="robots.txt"):
        guide.collect(output, tmp_path / "chromedriver")

    fetch.assert_called_once_with(guide.ROBOTS_URL, "text/plain", 100_000)
    capture.assert_not_called()
    assert (output / "robots.txt").read_bytes() == _DENIED_ROBOTS
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["collection_status"] == "failed"
    assert manifest["robots_status"] == "denied"
    assert manifest["error_type"] == "ValueError"
    assert manifest["files"] == {
        "robots.txt": {
            "sha256": sha256(_DENIED_ROBOTS).hexdigest(),
            "bytes": len(_DENIED_ROBOTS),
        }
    }
    assert {path.name for path in output.iterdir()} == {"robots.txt", "manifest.json"}


def test_existing_output_is_rejected_before_requests(tmp_path, monkeypatch):
    output = tmp_path / "existing"
    output.mkdir()
    original = output / "manifest.json"
    original.write_bytes(b"previous run")
    fetch = Mock()
    monkeypatch.setattr(guide, "_fetch", fetch)

    with pytest.raises(FileExistsError):
        guide.collect(output, tmp_path / "chromedriver")

    fetch.assert_not_called()
    assert original.read_bytes() == b"previous run"
