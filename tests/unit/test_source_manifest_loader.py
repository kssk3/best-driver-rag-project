"""출처 목록의 부모/첨부 관계와 입력 오류 경계를 확인한다.

fixture는 사용자가 제공한 공개 출처 목록이다. 실제 원문을 내려받거나 읽지 않는다.
"""

import json
import socket
from copy import deepcopy
from datetime import date
from pathlib import Path
from urllib import request

import pytest

from src.ingestion.loaders import SourceManifestError, load_source_manifest

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "source_manifest.json"


@pytest.fixture
def manifest_data():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8-sig"))


def write_manifest(tmp_path, data):
    path = tmp_path / "sources.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def assert_manifest_error(path, key=None):
    with pytest.raises(SourceManifestError) as caught:
        load_source_manifest(path)
    message = str(caught.value)
    assert str(path) in message
    if key is not None:
        assert key in message
    return message


def test_public_manifest_preserves_parent_attachment_relationships(manifest_data):
    entries = load_source_manifest(FIXTURE_PATH)

    assert len(entries) == 4
    assert [len(entry.attachments) for entry in entries] == [9, 9, 2, 1]
    assert sum(len(entry.attachments) for entry in entries) == 21
    assert {entry.district for entry in entries} == {"서대문구", "송파구"}
    for entry, original in zip(entries, manifest_data, strict=True):
        assert entry.ordinance_serial == original["일련번호"]
        assert entry.title == original["자치법규명"]
        assert entry.district == original["구"]
        assert entry.source_url == original["원문_URL"]
        assert entry.body_file == original["본문_파일"]
        assert entry.attachment_status == original["별표_상태"]
        raw_date = original["시행일"]
        assert entry.effective_date == date(
            int(raw_date[:4]), int(raw_date[4:6]), int(raw_date[6:])
        )
        assert [
            (attachment.number, attachment.title, attachment.source_url)
            for attachment in entry.attachments
        ] == [
            (attachment["번호"], attachment["제목"], attachment["파일_URL"])
            for attachment in original["별표_링크"]
        ]

    attachments = [attachment for entry in entries for attachment in entry.attachments]
    # 이 단계는 목록을 읽는다. 삭제 표시나 서식을 임의로 걸러 인계 자료를 잃지 않는다.
    assert sum("삭제" in attachment.title for attachment in attachments) == 2
    assert sum("별지" in attachment.title for attachment in attachments) == 8
    assert entries[0].attachments[0].number == "000700"
    # 같은 첨부 번호라도 서로 다른 부모 아래에서는 서로 다른 항목이다.
    assert {attachment.number for attachment in entries[0].attachments} & {
        attachment.number for attachment in entries[1].attachments
    }


def test_manifest_load_does_not_fetch_urls_or_require_declared_body_files(
    tmp_path, manifest_data, monkeypatch
):
    path = write_manifest(tmp_path, manifest_data)
    assert not (tmp_path / manifest_data[0]["본문_파일"]).exists()

    def forbid_network(*args, **kwargs):
        raise AssertionError("출처 목록 로더는 네트워크에 접근하면 안 됩니다.")

    monkeypatch.setattr(request, "urlopen", forbid_network)
    monkeypatch.setattr(socket, "create_connection", forbid_network)

    assert len(load_source_manifest(str(path))) == 4


def test_empty_manifest_and_empty_attachment_list_are_valid(tmp_path, manifest_data):
    assert load_source_manifest(write_manifest(tmp_path, [])) == []
    manifest_data[0]["별표_링크"] = []
    entries = load_source_manifest(write_manifest(tmp_path, manifest_data[:1]))
    assert entries[0].attachments == []
    assert entries[0].ordinance_serial == "2101297"


def test_bom_and_declared_values_are_preserved(tmp_path, manifest_data):
    manifest_data[0]["본문_파일"] = r"ordinances\서대문구_2101297.xml"
    manifest_data[0]["원문_URL"] = "HTTP://example.org/a%2Fb?x=1&x=2#original"
    path = tmp_path / "sources.json"
    path.write_text(json.dumps(manifest_data, ensure_ascii=False), encoding="utf-8-sig")

    entry = load_source_manifest(path)[0]

    assert entry.body_file == manifest_data[0]["본문_파일"]
    assert entry.source_url == manifest_data[0]["원문_URL"]


@pytest.mark.parametrize("payload", [{}, {"records": []}, [None], [42], [[]]])
def test_wrong_manifest_shape_has_a_file_context(tmp_path, payload):
    assert_manifest_error(write_manifest(tmp_path, payload))


@pytest.mark.parametrize(
    ("target", "key", "value"),
    [
        ("entry", "일련번호", 2101297),
        ("attachment", "번호", 700),
        ("entry", "별표_링크", {}),
        ("entry", "추가_메타데이터", "미지원"),
        ("attachment", "추가_메타데이터", "미지원"),
    ],
)
def test_unsupported_or_lossy_values_report_the_input_key(
    tmp_path, manifest_data, target, key, value
):
    row = manifest_data[0]
    container = row if target == "entry" else row["별표_링크"][0]
    container[key] = value
    message = assert_manifest_error(write_manifest(tmp_path, [row]), key)
    assert "0" in message


@pytest.mark.parametrize(
    ("target", "key"), [("entry", "시행일"), ("attachment", "파일_URL")]
)
def test_missing_required_values_report_the_input_key(
    tmp_path, manifest_data, target, key
):
    row = manifest_data[0]
    container = row if target == "entry" else row["별표_링크"][0]
    del container[key]
    assert_manifest_error(write_manifest(tmp_path, [row]), key)


@pytest.mark.parametrize(
    "value", ["20250229", "20251301", "2025-12-31", "2025123", 20251231]
)
def test_effective_date_requires_a_real_eight_digit_date(
    tmp_path, manifest_data, value
):
    manifest_data[0]["시행일"] = value
    assert_manifest_error(write_manifest(tmp_path, manifest_data), "시행일")


def test_leap_day_is_valid(tmp_path, manifest_data):
    manifest_data[0]["시행일"] = "20240229"
    entry = load_source_manifest(write_manifest(tmp_path, manifest_data))[0]
    assert entry.effective_date == date(2024, 2, 29)


@pytest.mark.parametrize(
    "value",
    [
        "../body.xml",
        r"data\..\body.xml",
        "/body.xml",
        r"C:\data\body.xml",
        "C:body.xml",
        r"\\server\share\body.xml",
    ],
)
def test_body_file_must_stay_a_relative_declared_path(tmp_path, manifest_data, value):
    manifest_data[0]["본문_파일"] = value
    assert_manifest_error(write_manifest(tmp_path, manifest_data), "본문_파일")


@pytest.mark.parametrize(
    ("target", "key", "value"),
    [
        ("entry", "원문_URL", "file:///body.xml"),
        ("entry", "원문_URL", "https:///missing-host"),
        ("attachment", "파일_URL", "/relative.hwp"),
        ("attachment", "파일_URL", "ftp://example.org/annex.hwp"),
    ],
)
def test_source_urls_require_http_and_a_host(
    tmp_path, manifest_data, target, key, value
):
    row = manifest_data[0]
    container = row if target == "entry" else row["별표_링크"][0]
    container[key] = value
    assert_manifest_error(write_manifest(tmp_path, [row]), key)


def test_duplicate_parent_serial_is_rejected_even_if_titles_differ(
    tmp_path, manifest_data
):
    manifest_data[1]["일련번호"] = manifest_data[0]["일련번호"]
    assert_manifest_error(write_manifest(tmp_path, manifest_data), "일련번호")


def test_duplicate_attachment_number_is_rejected_within_its_parent(
    tmp_path, manifest_data
):
    duplicate = deepcopy(manifest_data[0]["별표_링크"][0])
    duplicate["제목"] = "같은 번호의 다른 제목"
    manifest_data[0]["별표_링크"].append(duplicate)
    assert_manifest_error(write_manifest(tmp_path, manifest_data), "번호")


@pytest.mark.parametrize("level", ["entry", "attachment"])
def test_duplicate_json_keys_are_rejected_before_values_are_overwritten(
    tmp_path, manifest_data, level
):
    row = manifest_data[0]
    raw = json.dumps([row], ensure_ascii=False)
    key = "일련번호" if level == "entry" else "번호"
    value = row[key] if level == "entry" else row["별표_링크"][0][key]
    pair = json.dumps(key, ensure_ascii=False) + ": " + json.dumps(value)
    assert pair in raw
    raw = raw.replace(pair, pair + ", " + pair, 1)
    path = tmp_path / "sources.json"
    path.write_text(raw, encoding="utf-8")

    assert_manifest_error(path, key)


@pytest.mark.parametrize("raw", [b'[{"broken":', b"\xff\xfe\x00"])
def test_unreadable_json_is_reported_as_a_manifest_error(tmp_path, raw):
    path = tmp_path / "sources.json"
    path.write_bytes(raw)
    assert_manifest_error(path)


def test_missing_manifest_preserves_file_not_found_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_source_manifest(tmp_path / "missing.json")
