import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import Mock, patch

from scripts import collect as command
from src.ingestion import collect as collector


class ConfigurableCollectorTests(unittest.TestCase):
    def test_unknown_api_blocks_without_prompt_or_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "config.json"
            config.write_text(
                '{"api_access": {"collection_status": "unknown"}, "targets": '
                '[{"document_id": "test", "title": "test", "district": "test"}]}',
                encoding="utf-8",
            )
            with patch("sys.argv", ["collector", "--config", str(config), "--check"]):
                with patch.object(collector, "urlopen") as network:
                    with patch.object(command, "getpass") as prompt:
                        self.assertEqual(command.main(), 1)
                        network.assert_not_called()
                        prompt.assert_not_called()

    def test_changed_version_never_fetches_body(self):
        row = ET.fromstring("<row><자치법규일련번호>222</자치법규일련번호></row>")
        client = Mock()
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(collector, "find_document", return_value=row):
                with self.assertRaises(ValueError):
                    collector.collect_document(
                        client,
                        {"title": "조례", "reviewed_mst": "111"},
                        Path(temporary) / "doc",
                    )
        client.fetch.assert_not_called()

    def test_pagination_selects_exact_title(self):
        first = b"<root><totalCnt>101</totalCnt><row><name>other</name></row></root>"
        first_root = ET.fromstring(
            "<root><totalCnt>101</totalCnt><row>"
            "<자치법규일련번호>1</자치법규일련번호>"
            "<자치법규명>다른 조례</자치법규명></row></root>"
        )
        second_root = ET.fromstring(
            "<root><totalCnt>101</totalCnt><row>"
            "<자치법규일련번호>2</자치법규일련번호>"
            "<자치법규명>대상 조례</자치법규명></row></root>"
        )
        client = Mock()
        client.fetch.side_effect = [(first, first_root), (b"<root/>", second_root)]
        with tempfile.TemporaryDirectory() as temporary:
            row = collector.find_document(client, "대상조례", Path(temporary))
        self.assertEqual(row.findtext("자치법규일련번호"), "2")
        self.assertEqual(client.fetch.call_count, 2)


if __name__ == "__main__":
    unittest.main()
