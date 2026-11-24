"""제공 자료 연결의 무결성, 부모 관계와 두 표현의 비교 범위를 검증한다."""

import copy
import hashlib
import json
from html import unescape
from pathlib import Path

import pytest

from src.ingestion.preprocessed_bundle import PreprocessedBundleError, load_preprocessed_bundle


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


def put_json(root, relative, data):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(data, ensure_ascii=False, indent=2) + "\r\n").encode("utf-8"))


def read_json(root, relative):
    return json.loads((root / relative).read_bytes())


def refresh_manifest(root):
    files = [
        {"path": path.relative_to(root).as_posix(), "size_bytes": path.stat().st_size, "sha256": digest(path.read_bytes())}
        for path in root.rglob("*") if path.is_file() and path.name != "bundle_manifest.json"
    ]
    # ZIP 선택 추출과 동일하게 사용하지 않는 원본 파일이 존재하지 않아도 된다.
    files.append({"path": "code/not-extracted.py", "size_bytes": 2, "sha256": "0" * 64})
    put_json(root, "bundle_manifest.json", {"schema_version": "jungeun-handoff-bundle-v2", "files": files})


@pytest.fixture
def bundle(tmp_path):
    root = tmp_path / "input"
    (root / "raw/sample").mkdir(parents=True)
    body_xml = """<LawService><자치법규기본정보><자치법규일련번호>100</자치법규일련번호>
    <자치법규명>합성 조례</자치법규명><시행일자>20260101</시행일자></자치법규기본정보>
    <조문><조><조문번호>000100</조문번호><조문여부>Y</조문여부><조제목>배출</조제목>
    <조내용>제1조 종이팩은 헹군다. 다만 오염된 것은 제외한다.</조내용></조></조문>
    <부칙><부칙내용>부칙 공포한 날부터 시행한다.</부칙내용></부칙></LawService>""".encode()
    (root / "raw/sample/body.xml").write_bytes(body_xml)
    body = {
        "schema_version": "jungeun-body-draft-v2", "document_id": "sample", "title": "합성 조례",
        "district": "서대문구", "mst": "100", "effective_date": "20260101",
        "source_url": "https://www.law.go.kr/LSW/ordinInfoP.do?ordinSeq=100",
        "raw_path": "sample/body.xml", "raw_sha256": digest(body_xml), "attachments": [],
        "units": [{"unit_id": "unit-1", "unit_type": "article", "raw_text": "종이팩은 헹군다.", "text": "종이팩은 헹군다."}],
        "supplementary_provisions": [], "usage_status": "index_and_model_use_unreviewed",
    }
    annex_records, raw_annex_records, overlays = [], [], []
    for attachment_id, role in [("200", "annex"), ("201", "administrative_form"), ("202", "signage_specification"), ("203", "deleted")]:
        listing = {
            "parent_mst": "100", "attachment_id": attachment_id, "annex_key": "key-" + attachment_id,
            "title": "합성 별표 " + attachment_id,
            "source_url": "https://www.law.go.kr/flDownload.do?flSeq=" + attachment_id,
            "deleted_marker": role == "deleted",
        }
        body["attachments"].append(listing)
        record = listing | {
            "document_id": "sample", "district": body["district"], "effective_date": body["effective_date"],
            "schema_version": "jungeun-annex-draft-v2", "content_role": role,
            "human_review_status": "pending", "processing_status": "structure_extracted_pending_review",
            "download_status": "downloaded", "usage_status": "index_and_model_use_unreviewed",
        }
        if role == "deleted":
            record.update(processing_status="excluded_deleted", download_status="skipped_deleted")
            annex_records.append(record)
            raw_annex_records.append(copy.deepcopy(record))
            continue
        raw_path = "attachments/100_" + attachment_id + ".hwp"
        raw_bytes = b"original-hwp-test-data-" + attachment_id.encode()
        (root / "raw/attachments").mkdir(exist_ok=True)
        (root / "raw" / raw_path).write_bytes(raw_bytes)
        xml_name = "100_" + attachment_id + ".xml"
        xml = """<HwpDoc><BodyText><SectionDef><Paragraph><Text>별표 안내와 비고</Text></Paragraph>
        <TableControl><TableBody rows="1" cols="1"><TableRow>
        <TableCell row="0" col="0" rowspan="1" colspan="1"><Paragraph><Text>종이팩을 헹군다</Text></Paragraph></TableCell>
        </TableRow></TableBody></TableControl></SectionDef></BodyText></HwpDoc>""".encode()
        (root / "processed/annex").mkdir(parents=True, exist_ok=True)
        (root / "processed/annex" / xml_name).write_bytes(xml)
        record.update(raw_path=raw_path, raw_sha256=digest(raw_bytes), extracted_xml=xml_name,
                      extracted_xml_sha256=digest(xml), blocks=[], tables=[])
        if role == "annex":
            updates = {"content_role": role, "human_review_status": "image_colors_confirmed",
                       "human_review": {"parent_mst": "100", "attachment_id": attachment_id, "scope": "그림 색상만"},
                       "structured_image_summary": {"applicability": "공동주택", "colors": [{"item": "종이팩", "color": "녹색"}],
                                                    "literal": "</aside><script>그림 설명</script>"}}
            record.update(updates)
            overlays.append({"parent_mst": "100", "attachment_id": attachment_id,
                             "raw_sha256": digest(raw_bytes), "updates": updates})
        json_name = "100_" + attachment_id + ".json"
        put_json(root, "processed/annex/" + json_name, record)
        annex_records.append(record | {"output_file": json_name})
        raw_annex_records.append(copy.deepcopy(record))
    put_json(root, "processed/body/sample.json", body)
    put_json(root, "raw/manifest.json", {"run_id": "run-1", "records": [body]})
    put_json(root, "raw/attachments/manifest.json", {"source_run_id": "run-1", "records": raw_annex_records})
    put_json(root, "processed/body/processing_manifest.json", {"source_run_id": "run-1", "documents": [
        {"document_id": "sample", "output_file": "sample.json", "raw_sha256": body["raw_sha256"]}
    ]})
    put_json(root, "processed/annex/annex_manifest.json", {"source_run_id": "run-1", "records": annex_records})
    put_json(root, "review/human_review_overlays.json", {"records": overlays})
    refresh_manifest(root)
    return root


def test_pairs_preserve_json_source_and_metadata_while_reporting_exclusions(bundle, tmp_path):
    before = (bundle / "processed/annex/100_200.json").read_bytes()
    prepared = load_preprocessed_bundle(bundle, project_root=tmp_path, version="v7")
    assert len(prepared.documents) == 8
    assert len(prepared.report["sources"]) == 4
    assert len(prepared.report["skipped"]) == 1
    assert sum(item["index_eligible"] for item in prepared.report["sources"]) == 2
    assert prepared.report["skipped"][0]["reason"] == "deleted"
    assert {item["role"] for item in prepared.report["sources"]} == {"body", "annex", "administrative_form", "signage_specification"}
    for json_doc, html_doc in zip(prepared.documents[::2], prepared.documents[1::2], strict=True):
        assert (json_doc.content_format, html_doc.content_format) == ("json", "html")
        for field in ("document_id", "version", "effective_date", "source_url", "raw_path", "districts", "parent_document_id", "parent_document_version"):
            assert getattr(json_doc, field) == getattr(html_doc, field)
        assert json_doc.version == "v7"
        assert str(json_doc.effective_date) == "2026-01-01"
        assert json_doc.raw_path.startswith("input/raw/")
        assert json_doc.districts == ["서대문구"]
        if json_doc.document_id != "sample":
            assert json_doc.parent_document_id == "sample"
            assert json_doc.parent_document_version == "v7"
    annex_json, annex_html = prepared.documents[2:4]
    assert annex_json.content == before.decode()
    assert (bundle / "processed/annex/100_200.json").read_bytes() == before
    assert '<aside data-review-overlay="image-summary">' in annex_html.content
    summary_text = annex_html.content.split('<aside data-review-overlay="image-summary">')[1].split("</aside>")[0]
    assert json.loads(unescape(summary_text)) == json.loads(annex_json.content)["structured_image_summary"]
    assert "<script>" not in annex_html.content
    assert "<table" in annex_html.content


def test_explicit_existing_ids_rewire_parent_without_guessing_version(bundle, tmp_path):
    prepared = load_preprocessed_bundle(bundle, project_root=tmp_path, version="explicit-revision",
                                       identities={"sample": "existing-body", "sample:attachment:200": "existing-annex"})
    assert prepared.documents[0].document_id == "existing-body"
    assert prepared.documents[2].document_id == "existing-annex"
    assert prepared.documents[2].parent_document_id == "existing-body"
    assert prepared.documents[2].version == "explicit-revision"
    assert prepared.report["sources"][1]["source_key"] == "sample:attachment:200"


def test_raw_path_is_none_if_original_is_outside_project(bundle, tmp_path):
    project = tmp_path / "separate-project"
    project.mkdir()
    assert all(document.raw_path is None for document in load_preprocessed_bundle(bundle, project_root=project, version="v1").documents)


@pytest.mark.parametrize("relative", ["processed/body/sample.json", "raw/sample/body.xml", "raw/attachments/100_200.hwp", "processed/annex/100_200.xml"])
def test_changed_files_fail_integrity_check(bundle, tmp_path, relative):
    path = bundle / relative
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(PreprocessedBundleError, match="크기 불일치|SHA256 불일치"):
        load_preprocessed_bundle(bundle, project_root=tmp_path, version="v1")


@pytest.mark.parametrize("relative", ["raw/sample/body.xml", "raw/attachments/100_200.hwp", "processed/annex/100_200.xml"])
def test_source_specific_hash_is_checked_even_if_bundle_manifest_is_updated(bundle, tmp_path, relative):
    path = bundle / relative
    path.write_bytes(path.read_bytes() + b" ")
    refresh_manifest(bundle)
    with pytest.raises(PreprocessedBundleError, match="SHA256 불일치"):
        load_preprocessed_bundle(bundle, project_root=tmp_path, version="v1")


@pytest.mark.parametrize("changed_value", ["../outside.json", "/absolute.json", "C:/absolute.json"])
def test_manifest_cannot_escape_its_directory(bundle, tmp_path, changed_value):
    name = "processed/body/processing_manifest.json"
    data = read_json(bundle, name)
    data["documents"][0]["output_file"] = changed_value
    put_json(bundle, name, data)
    refresh_manifest(bundle)
    with pytest.raises(PreprocessedBundleError, match="상대 경로"):
        load_preprocessed_bundle(bundle, project_root=tmp_path, version="v1")


@pytest.mark.parametrize("field,value", [("parent_mst", "999"), ("document_id", "wrong-parent"), ("effective_date", "20270101"), ("district", "송파구")])
def test_annex_metadata_and_parent_must_match(bundle, tmp_path, field, value):
    name = "processed/annex/annex_manifest.json"
    data = read_json(bundle, name)
    data["records"][0][field] = value
    put_json(bundle, name, data)
    refresh_manifest(bundle)
    with pytest.raises(PreprocessedBundleError):
        load_preprocessed_bundle(bundle, project_root=tmp_path, version="v1")


@pytest.mark.parametrize("mutation", ["hash", "duplicate", "parent", "value", "missing"])
def test_overlay_must_match_identity_hash_and_existing_json(bundle, tmp_path, mutation):
    name = "review/human_review_overlays.json"
    data = read_json(bundle, name)
    if mutation == "hash": data["records"][0]["raw_sha256"] = "0" * 64
    elif mutation == "duplicate": data["records"].append(copy.deepcopy(data["records"][0]))
    elif mutation == "parent": data["records"][0]["parent_mst"] = "999"
    elif mutation == "value": data["records"][0]["updates"]["structured_image_summary"]["colors"][0]["color"] = "빨강"
    else: data["records"] = []
    put_json(bundle, name, data)
    refresh_manifest(bundle)
    with pytest.raises(PreprocessedBundleError):
        load_preprocessed_bundle(bundle, project_root=tmp_path, version="v1")


@pytest.mark.parametrize("bad_json", ['{"records": [], "records": []}', '{"records": NaN}', '{"records": Infinity}'])
def test_json_duplicate_fields_and_nonstandard_numbers_are_rejected(bundle, tmp_path, bad_json):
    (bundle / "review/human_review_overlays.json").write_text(bad_json, encoding="utf-8")
    refresh_manifest(bundle)
    with pytest.raises(PreprocessedBundleError):
        load_preprocessed_bundle(bundle, project_root=tmp_path, version="v1")


@pytest.mark.parametrize("identities", [{"unknown": "id"}, {"sample": "collision", "sample:attachment:200": "collision"}, {"sample": " "}])
def test_identity_mappings_reject_unknown_duplicate_or_blank_ids(bundle, tmp_path, identities):
    with pytest.raises(PreprocessedBundleError):
        load_preprocessed_bundle(bundle, project_root=tmp_path, version="v1", identities=identities)


def test_missing_xml_is_not_silently_replaced_by_json(bundle, tmp_path):
    (bundle / "processed/annex/100_200.xml").unlink()
    with pytest.raises(PreprocessedBundleError, match="필수 파일"):
        load_preprocessed_bundle(bundle, project_root=tmp_path, version="v1")


def test_version_is_explicit_and_nonblank(bundle, tmp_path):
    with pytest.raises(TypeError):
        load_preprocessed_bundle(bundle, project_root=tmp_path)
    with pytest.raises(PreprocessedBundleError, match="version"):
        load_preprocessed_bundle(bundle, project_root=tmp_path, version=" ")
