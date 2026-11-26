"""합성 HWP XML의 병합 셀·조건·삭제 구획 보존 검사."""

from pathlib import Path

from src.ingestion.annexes import extract_hwp_xml


def test_merged_cell_keeps_row_context_and_deleted_section(tmp_path: Path):
    path = tmp_path / "synthetic.xml"
    path.write_text(
        """<HwpDoc><BodyText><Paragraph><Text>[별표 2]</Text></Paragraph>
<TableControl><TableBody rows="2" cols="2"><TableRow>
<TableCell row="0" col="0" rowspan="2" colspan="1"><Paragraph>
<Text>종이팩</Text><Tab/><Text>살균팩</Text></Paragraph></TableCell>
<TableCell row="0" col="1" rowspan="1" colspan="1"><Paragraph>
<Text>전용함 또는 묶음</Text></Paragraph></TableCell></TableRow><TableRow>
<TableCell row="1" col="1" rowspan="1" colspan="1"><Paragraph>
<Text>다만, 단독주택 조건</Text></Paragraph></TableCell></TableRow></TableBody></TableControl>
<Paragraph><Text>비고 1. 예외 조건 보존</Text></Paragraph>
<Paragraph><Text>[별표 3] 삭제</Text></Paragraph></BodyText></HwpDoc>""",
        encoding="utf-8",
    )
    result = extract_hwp_xml(path)
    table = result["tables"][0]
    assert table["row_cell_ids"][0][0] == table["row_cell_ids"][1][0]
    assert table["cells"][0]["text"] == "종이팩\t살균팩"
    assert table["cells"][2]["text"] == "다만, 단독주택 조건"
    assert not table["deleted_section"]
    assert result["blocks"][-1]["deleted_section"]
    assert any("비고 1." in b.get("text", "") for b in result["blocks"])


def test_unreviewed_download_never_creates_folder(tmp_path):
    from unittest.mock import patch

    import pytest

    from src.ingestion.annexes import download_attachments

    with patch("src.ingestion.annexes.urlopen") as network:
        with pytest.raises(ValueError):
            download_attachments(
                tmp_path / "manifest.json", {"collection_status": "unknown"}
            )
        network.assert_not_called()
    assert not (tmp_path / "attachments").exists()
