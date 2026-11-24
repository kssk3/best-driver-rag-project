"""벡터 재사용과 출처 분리, 실패 시 기존 색인 보존을 검증한다."""

import json
import math
from pathlib import Path
import sys

import pytest

from src.contracts import Chunk
from src.infrastructure.embeddings import DemoHashEmbeddings, LangChainEmbeddingsAdapter
from src.infrastructure.stores import load_index, save_index
from src.ingestion.indexing import MemoryEmbeddingCache, build_index


def chunk(name="one", content="<p>합성 안내</p>", version="v1"):
    return Chunk(
        chunk_id=f"{name}-{version}", source_document_id=name,
        source_document_version=version, title="합성 자료", content_format="html",
        content=content, source_url=f"https://example.org/{name}",
        source_location="문서 전체", scope_type="district", districts=["송파구"],
        chunking_version="whole-document-v1",
    )


class RecordingEmbeddings(DemoHashEmbeddings):
    def __init__(self, dimensions=8):
        super().__init__(dimensions)
        self.calls = []

    def embed_documents(self, texts):
        self.calls.append(texts[:])
        return super().embed_documents(texts)


def test_reuse_keeps_each_source_and_exact_provider_settings_separate():
    provider, cache = RecordingEmbeddings(), MemoryEmbeddingCache()
    first, second = chunk("one"), chunk("two")
    snapshot = build_index([first, second], provider, cache=cache)
    assert provider.calls == [[first.content]]
    assert [entry.chunk.source_document_id for entry in snapshot.entries] == ["one", "two"]
    assert snapshot.entries[0].vector == snapshot.entries[1].vector
    assert len(snapshot.metadata.source_document_versions) == 2
    build_index([chunk("one", version="v2")], provider, cache=cache)
    assert len(provider.calls) == 1
    build_index([chunk(content=first.content + " ")], provider, cache=cache)
    assert provider.calls[-1] == [first.content + " "]
    changed = RecordingEmbeddings(16)
    assert build_index([first], changed, cache=cache).metadata.dimension == 16
    assert changed.calls == [[first.content]]


def test_snapshot_round_trip_and_rebuild_remove_old_chunks(tmp_path):
    path = tmp_path / "index.json"
    provider = DemoHashEmbeddings(8)
    save_index(build_index([chunk("old"), chunk("kept")], provider), path)
    latest = build_index([chunk("kept", version="v2")], provider)
    save_index(latest, path)
    restored = load_index(path)
    assert restored == latest
    assert [entry.chunk.chunk_id for entry in restored.entries] == ["kept-v2"]
    assert restored.metadata.embedding_identity == provider.identity
    assert restored.metadata.source_document_versions[0].version == "v2"


@pytest.mark.parametrize("vectors", [[], [[1.0]], [[1.0], [1.0, 2.0]],
    [[math.nan], [0.0]], [[math.inf], [0.0]], [[True], [0.0]], [["1"], [0.0]],
    [[10**1000], [0.0]]])
def test_bad_embedding_batch_is_rejected_without_polluting_cache(vectors):
    provider = LangChainEmbeddingsAdapter(
        type("BadClient", (), {"embed_documents": lambda self, texts: vectors})(), "bad:model=v1"
    )
    cache = MemoryEmbeddingCache()
    with pytest.raises(ValueError):
        build_index([chunk("one", "one"), chunk("two", "two")], provider, cache=cache)
    assert cache.vectors == {}


def test_invalid_write_and_replace_failure_preserve_existing_file(tmp_path, monkeypatch):
    path = tmp_path / "index.json"
    snapshot = build_index([chunk()], DemoHashEmbeddings())
    save_index(snapshot, path)
    original = path.read_bytes()
    snapshot.entries[0].vector[0] = math.nan
    with pytest.raises(ValueError):
        save_index(snapshot, path)
    assert path.read_bytes() == original
    snapshot = load_index(path)
    def fail_replace(*args):
        raise OSError("합성 교체 실패")
    monkeypatch.setattr("src.infrastructure.stores.os.replace", fail_replace)
    with pytest.raises(OSError, match="합성 교체 실패"):
        save_index(snapshot, path)
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("corruption", ["dimension", "nan", "source_version"])
def test_load_rejects_corrupted_snapshot(tmp_path, corruption):
    path = tmp_path / "index.json"
    data = build_index([chunk()], DemoHashEmbeddings(8)).model_dump()
    if corruption == "dimension":
        data["entries"][0]["vector"] = [1.0]
    elif corruption == "nan":
        data["entries"][0]["vector"][0] = math.nan
    else:
        data["metadata"]["source_document_versions"][0]["version"] = "wrong"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        load_index(path)


def test_demo_and_adapter_use_the_same_query_document_vector_contract():
    provider = DemoHashEmbeddings(8)
    adapter = LangChainEmbeddingsAdapter(provider, provider.identity)
    assert adapter.embed_query("종이팩") == adapter.embed_documents(["종이팩"])[0]
    assert adapter.embed_query("종이팩") == DemoHashEmbeddings(8).embed_query("종이팩")


def test_duplicate_chunk_ids_fail_before_embedding():
    provider = RecordingEmbeddings()
    with pytest.raises(ValueError, match="chunk_id"):
        build_index([chunk(), chunk()], provider)
    assert provider.calls == []


def test_cli_format_filter_and_empty_selection_preserve_existing_index(
    tmp_path, monkeypatch, capsys
):
    from scripts.index import main

    fixture = Path(__file__).parents[1] / "fixtures" / "preprocessing_variants.json"
    documents = json.loads(fixture.read_text(encoding="utf-8"))["documents"]
    source, output = tmp_path / "documents.json", tmp_path / "index.json"
    source.write_text(json.dumps(documents), encoding="utf-8")
    arguments = ["index", "--documents", str(source), "--output", str(output), "--demo"]
    monkeypatch.setattr(sys, "argv", arguments + ["--content-format", "html"])
    main()
    assert {entry.chunk.content_format for entry in load_index(output).entries} == {"html"}
    original = output.read_bytes()
    source.write_text(json.dumps([doc for doc in documents if doc["content_format"] == "html"]), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", arguments + ["--content-format", "json"])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert "json 형식의 문서가 없습니다" in capsys.readouterr().err
    assert output.read_bytes() == original
