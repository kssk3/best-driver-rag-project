"""합성 XML로 조건 보존·원본 대조·덮어쓰기 차단 검사."""

import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from src.ingestion.clean import extract_document, preprocess_run


def source(tmp_path: Path) -> tuple[Path, dict]:
    raw = """<LawService><자치법규기본정보>
<자치법규명>테스트 조례</자치법규명><자치법규일련번호>123</자치법규일련번호>
<시행일자>20260101</시행일자></자치법규기본정보><조문>
<조><조문번호>000000</조문번호><조문여부>N</조문여부><조제목/>
<조내용>제1장 총칙</조내용></조>
<조><조문번호>000100</조문번호><조문여부>Y</조문여부><조제목>배출</조제목>
<조내용>  ① 종이 또는 종이팩\n② 다만, 단독주택은 예외. &lt;개정 2026. 1. 1.&gt;\n</조내용></조>
<조><조문번호>000000</조문번호><조문여부>N</조문여부><조제목/>
<조내용>제2장 처리</조내용></조></조문></LawService>""".encode()
    path = tmp_path / "body.xml"
    path.write_bytes(raw)
    record = {
        "document_id": "test",
        "collection_status": "body_saved",
        "title": "테스트 조례",
        "mst": "123",
        "district": "테스트구",
        "effective_date": "20260101",
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "source_url": "https://example.org/ordinance",
        "raw_path": "body.xml",
        "review": {},
        "usage_status": "index_and_model_use_unreviewed",
        "attachments": [],
    }
    return path, record


def test_preserves_conditions_headings_and_distinct_sources(tmp_path):
    path, record = source(tmp_path)
    result = extract_document(path, record)
    assert len({u["unit_id"] for u in result["units"]}) == 3
    article = result["units"][1]
    assert article["text"] == article["raw_text"].strip()
    assert "또는 종이팩\n② 다만, 단독주택은 예외." in article["text"]
    assert "<개정 2026. 1. 1.>" in article["text"]
    other = extract_document(
        path, {**record, "document_id": "other", "district": "다른구"}
    )
    assert other["units"][1]["unit_id"] != article["unit_id"]
    assert other["district"] == "다른구"
    assert result["usage_status"] == record["usage_status"]


def test_rejects_tampered_bytes_and_mismatched_version(tmp_path):
    path, record = source(tmp_path)
    with pytest.raises(ValueError, match="mst"):
        extract_document(path, {**record, "mst": "999"})
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="해시"):
        extract_document(path, record)


def test_run_preserves_original_and_rejects_overwrite(tmp_path):
    path, record = source(tmp_path)
    original = path.read_bytes()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"run_id": "test-run", "records": [record]}), encoding="utf-8"
    )
    output = tmp_path / "processed"
    summary = preprocess_run(manifest, output)
    assert summary["documents"][0]["article_count"] == 1
    assert path.read_bytes() == original
    with pytest.raises(FileExistsError):
        preprocess_run(manifest, output)


def test_supplements_preserve_historical_transition_separately(tmp_path):
    path, record = source(tmp_path)
    raw = (
        path.read_text(encoding="utf-8")
        .replace(
            "</LawService>",
            """<부칙>
<부칙공포일자>20260101</부칙공포일자><부칙공포번호>1</부칙공포번호>
<부칙내용>부칙 &lt;1997. 1. 1.&gt; 종전 규정 적용.\n다만, 재고 소진까지 사용.</부칙내용>
</부칙></LawService>""",
        )
        .encode()
    )
    path.write_bytes(raw)
    record["raw_sha256"] = hashlib.sha256(raw).hexdigest()
    result = extract_document(path, record)
    supplement = result["supplementary_provisions"][0]
    assert "1997. 1. 1." in supplement["text"]
    assert "다만, 재고 소진까지 사용." in supplement["text"]
    assert (
        supplement["applicability_status"]
        == "historical_and_current_mixed_review_required"
    )
    assert not any("재고 소진" in u["text"] for u in result["units"])


@pytest.mark.parametrize(
    "content",
    [
        "제43조 삭제 <2015. 11. 11.>",
        "제12조 <삭제 2015.4.2>",
        "제5조 (과태료 부과기준) <삭제 2015.10.22.>",
        "제12조의2(대상) 삭제 <2025. 1. 1.>",
    ],
)
def test_marks_whole_deleted_article_with_empty_or_existing_title(tmp_path, content):
    path, record = source(tmp_path)
    root = ET.parse(path).getroot()
    article = root.findall("./조문/조")[1]
    article.find("조제목").text = "과태료 부과기준" if "과태료" in content else ""
    article.find("조내용").text = content
    raw = ET.tostring(root, encoding="utf-8")
    path.write_bytes(raw)
    record["raw_sha256"] = hashlib.sha256(raw).hexdigest()
    result = extract_document(path, record)
    assert result["units"][1]["deleted_article"] is True
    assert result["units"][1]["text"] == content
    assert result["units"][0]["deleted_article"] is False


@pytest.mark.parametrize(
    "content",
    [
        "제11조(사업장 폐기물의 처리) \n① <삭제 2015.4.2>\n② 구청장은 수집한다.",
        "제19조(규격봉투의 공급 및 구입 등) \n① 삭제<2000·6·8>\n② 공공용봉투를 사용한다.",
        "제1조(배출) 해당하지 않는 항목은 삭제한다.",
    ],
)
def test_partial_deletion_does_not_delete_active_article(tmp_path, content):
    path, record = source(tmp_path)
    root = ET.parse(path).getroot()
    article = root.findall("./조문/조")[1]
    article.find("조내용").text = content
    raw = ET.tostring(root, encoding="utf-8")
    path.write_bytes(raw)
    record["raw_sha256"] = hashlib.sha256(raw).hexdigest()
    result = extract_document(path, record)
    assert result["units"][1]["deleted_article"] is False
    assert result["units"][1]["text"] == content
