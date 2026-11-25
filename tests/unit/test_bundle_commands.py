"""자료 외 파일 배제, 손상 시 중단, 외부 호출 전 한도와 지역 제한을 검증한다."""

import json
from types import SimpleNamespace

import pytest

from scripts.prepare_data import prepare
from scripts.search_index import rank_entries
from src.contracts import Chunk
from src.infrastructure.embeddings import BoundedEmbeddings, DemoHashEmbeddings
from src.ingestion.indexing import build_index


class Provider:
    identity = "recording-only"

    def __init__(self):
        self.calls = []

    def embed_documents(self, texts):
        self.calls.append(texts)
        return [[1.0, 0.0] for _ in texts]


def test_over_limit_input_rejected_before_any_api_call():
    provider = Provider()
    bounded = BoundedEmbeddings(provider, max_tokens=4)
    with pytest.raises(ValueError):
        bounded.embed_documents(["a", "많은 내용 " * 30])
    assert provider.calls == []


def test_batching_preserves_input_order():
    provider = Provider()
    bounded = BoundedEmbeddings(provider)
    inputs = [str(i) for i in range(130)]
    assert len(bounded.embed_documents(inputs)) == 130
    assert [len(batch) for batch in provider.calls] == [64, 64, 2]
    assert sum(provider.calls, []) == inputs


def test_search_filters_region_before_ranking():
    chunks = [
        Chunk(
            chunk_id=scope,
            source_document_id=scope,
            source_document_version="v1",
            title=scope,
            content_format="json",
            content='{"text":"test"}',
            source_url="https://example.org/",
            source_location="test",
            scope_type=scope,
            districts=["송파구"] if scope == "district" else [],
            chunking_version="test",
        )
        for scope in ["district", "common", "unknown"]
    ]
    index = build_index(chunks, DemoHashEmbeddings(4))
    matches = rank_entries(index, index.entries[0].vector, "서대문구", 10)
    assert [m["chunk"]["chunk_id"] for m in matches] == ["common"]
    with pytest.raises(ValueError, match="차원"):
        rank_entries(index, [1.0], "서대문구", 1)


def test_input_failure_records_stage_and_does_not_claim_completion(tmp_path):
    args = SimpleNamespace(
        bundle=tmp_path / "missing",
        version="v1",
        output_dir=tmp_path / "output",
        openai_model="text-embedding-3-small",
        api_key_file=None,
        identities=None,
        max_characters=12000,
    )
    with pytest.raises(RuntimeError, match="load_documents"):
        prepare(args)
    report = json.loads((args.output_dir / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    assert report["stage"] == "load_documents"
    assert report["index_status"] == "failed"
    assert "error_type" in report


def _prepared_pair():
    from src.contracts import SourceDocument
    from src.ingestion.preprocessed_bundle import PreparedBundle
    from src.ingestion.xml_adapter import xml_to_html

    xml = "<LawService><조문><조><조문번호>000100</조문번호><조문여부>Y</조문여부><조제목>배출</조제목><조내용>종이팩은 별도로 배출한다.</조내용></조></조문></LawService>"
    data = {
        "schema_version": "jungeun-body-draft-v2",
        "units": [
            {
                "unit_type": "article",
                "raw_text": "종이팩은 별도로 배출한다.",
                "source_location": "조문/조[1] (조문번호 000100)",
            }
        ],
        "supplementary_provisions": [],
    }
    docs = [
        SourceDocument(
            document_id="body",
            version="v1",
            title="합성 단위 테스트",
            content_format=fmt,
            content=content,
            source_url="https://example.org/",
            scope_type="district",
            districts=["서대문구"],
        )
        for fmt, content in [
            ("html", xml_to_html(xml)),
            ("json", json.dumps(data, ensure_ascii=False)),
        ]
    ]
    return PreparedBundle(
        docs,
        {
            "sources": [
                {"document_id": "body", "source_key": "body", "index_eligible": True}
            ],
            "skipped": [],
        },
    )


def test_prepare_builds_separate_indexes_and_records_completion(tmp_path, monkeypatch):
    import scripts.prepare_data as command
    import src.ingestion.preprocessed_bundle as bundle
    from src.infrastructure.stores import load_index

    monkeypatch.setattr(
        bundle, "load_preprocessed_bundle", lambda *args, **kwargs: _prepared_pair()
    )
    monkeypatch.setattr(command, "create_openai_embeddings", lambda model: Provider())
    args = SimpleNamespace(
        bundle=tmp_path,
        version="v1",
        output_dir=tmp_path / "output",
        openai_model="text-embedding-3-small",
        api_key_file=None,
        identities=None,
        max_characters=12000,
    )
    report = prepare(args)
    assert report["status"] == report["index_status"] == "completed"
    for fmt in ["html", "json"]:
        index = load_index(args.output_dir / f"index-{fmt}.json")
        assert [e.chunk.content_format for e in index.entries] == [fmt]
        assert index.entries[0].chunk.source_document_id == "body"


def test_second_format_failure_marks_partial_outputs_failed(tmp_path, monkeypatch):
    import src.ingestion.preprocessed_bundle as bundle

    pair = _prepared_pair()
    pair.documents[1].content = '{"schema_version":"unknown"}'
    monkeypatch.setattr(
        bundle, "load_preprocessed_bundle", lambda *args, **kwargs: pair
    )
    args = SimpleNamespace(
        bundle=tmp_path,
        version="v1",
        output_dir=tmp_path / "output",
        openai_model=None,
        api_key_file=None,
        identities=None,
        max_characters=12000,
    )
    with pytest.raises(RuntimeError, match="chunking"):
        prepare(args)
    report = json.loads((args.output_dir / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    assert report["stage"] == "chunking"
    assert not (args.output_dir / "index-html.json").exists()


def test_embedding_failure_preserves_error_type_and_completed_format(
    tmp_path, monkeypatch
):
    import scripts.prepare_data as command
    import src.ingestion.preprocessed_bundle as bundle

    class FailingProvider(Provider):
        def embed_documents(self, texts):
            if self.calls:
                raise TypeError("provider detail must not be recorded")
            return super().embed_documents(texts)

    provider = FailingProvider()
    monkeypatch.setattr(
        bundle, "load_preprocessed_bundle", lambda *args, **kwargs: _prepared_pair()
    )
    monkeypatch.setattr(command, "create_openai_embeddings", lambda model: provider)
    args = SimpleNamespace(
        bundle=tmp_path,
        version="v1",
        output_dir=tmp_path / "output",
        openai_model="text-embedding-3-small",
        api_key_file=None,
        identities=None,
        max_characters=12000,
    )
    with pytest.raises(RuntimeError, match="embedding 단계 실패: TypeError") as caught:
        prepare(args)
    saved = (args.output_dir / "report.json").read_text(encoding="utf-8")
    report = json.loads(saved)
    assert report["status"] == report["index_status"] == "failed"
    assert report["stage"] == "embedding"
    assert report["error_type"] == "TypeError"
    assert report["formats"]["html"]["index_id"]
    assert (args.output_dir / "index-html.json").exists()
    assert not (args.output_dir / "index-json.json").exists()
    assert "provider detail" not in saved + str(caught.value)
