"""Offline retrieval adapters for personal answer experiments."""

import re
import unicodedata
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from math import log
from typing import ClassVar, Protocol

from langchain_classic.retrievers.ensemble import EnsembleRetriever
from langchain_community.retrievers.bm25 import BM25Retriever
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.retrievers import BaseRetriever
from langchain_core.vectorstores import InMemoryVectorStore

from src.generation.answer import Evidence

from .csv_export import Candidate


_DOCUMENT_KEY = "experiment_document_id"
_WORD = re.compile(r"[^\W_]+")


@dataclass(frozen=True, kw_only=True)
class RetrievalDocument:
    """A versioned source passage with its own unique key in this corpus."""

    document_key: str
    district: str | None  # None is an explicit cross-district document.
    evidence: Evidence
    eligible_for_disposal: bool = True


class RetrievalPort(Protocol):
    """Return ranked candidates within a previously prepared district scope."""

    name: str

    def search(self, query: str, *, district: str, k: int) -> list[Candidate]:
        """Return up to k candidates, with k within the prepared depth."""
        ...


def _word_tokens(text: str) -> list[str]:
    """BM25 tokens are NFKC-normalized Unicode words, without punctuation."""
    return _WORD.findall(unicodedata.normalize("NFKC", text).casefold())


def _character_ngrams(text: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    for word in _word_tokens(text):
        if len(word) == 1:
            counts[word] += 1
        for size in (2, 3):
            counts.update(word[start:start + size] for start in range(len(word) - size + 1))
    return counts


class CharacterTfidf(Embeddings):
    """Represent text using corpus-fitted, within-word character n-grams."""

    def __init__(self, texts: Sequence[str]):
        document_frequencies: Counter[str] = Counter()
        for text in texts:
            document_frequencies.update(_character_ngrams(text).keys())
        self.vocabulary = tuple(sorted(document_frequencies))
        self.idf = {
            term: log((1 + len(texts)) / (1 + frequency)) + 1
            for term, frequency in document_frequencies.items()
        }

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        counts = _character_ngrams(text)
        return [counts[term] * self.idf[term] for term in self.vocabulary]


@dataclass(frozen=True)
class _ScopedAdapter:
    indexes: dict[str, BaseRetriever | None]
    depth: int
    name: ClassVar[str]

    def search(self, query: str, *, district: str, k: int) -> list[Candidate]:
        if type(k) is not int or not 1 <= k <= self.depth:
            raise ValueError(f"k must be between 1 and {self.depth}")
        if district not in self.indexes:
            raise ValueError(f"District index has not been prepared: {district}")
        if not _word_tokens(query):
            raise ValueError("Query must contain text")

        retriever = self.indexes[district]
        if retriever is None:
            return []

        # LangChain's retriever interface returns documents in rank order.
        return [
            Candidate(
                rank=rank,
                evidence={
                    "source": dict(document.metadata["source"]),
                    "text": document.page_content,
                    "chunk_id": document.metadata["chunk_id"],
                },
            )
            for rank, document in enumerate(retriever.invoke(query)[:k], start=1)
        ]


class VectorOnlyAdapter(_ScopedAdapter):
    name = "vector"


class BM25VectorEnsembleAdapter(_ScopedAdapter):
    name = "ensemble"


def prepare_adapters(
    documents: Sequence[RetrievalDocument],
    *,
    districts: Sequence[str],
    depth: int = 5,
) -> tuple[VectorOnlyAdapter, BM25VectorEnsembleAdapter]:
    """Build both search methods over the same eligible pool per district."""
    if type(depth) is not int or depth < 1:
        raise ValueError("Search depth must be a positive integer")
    keys = [item.document_key for item in documents]
    if any(not key.strip() for key in keys) or len(set(keys)) != len(keys):
        raise ValueError("Document keys must be nonempty and unique")

    scopes = tuple(dict.fromkeys(districts))
    eligible = sorted(
        (
            item for item in documents
            if item.eligible_for_disposal and (item.district is None or item.district in scopes)
        ),
        key=lambda item: item.document_key,
    )
    embeddings = CharacterTfidf([item.evidence["text"] for item in eligible])
    vector_indexes = {}
    ensemble_indexes = {}
    for district in scopes:
        pool = [
            Document(
                id=item.document_key,
                page_content=item.evidence["text"],
                metadata={
                    _DOCUMENT_KEY: item.document_key,
                    "source": {**item.evidence["source"], _DOCUMENT_KEY: item.document_key},
                    "chunk_id": item.evidence["chunk_id"],
                },
            )
            for item in eligible
            if item.district is None or item.district == district
        ]
        if not pool:
            vector_indexes[district] = None
            ensemble_indexes[district] = None
            continue

        vector_store = InMemoryVectorStore(embeddings)
        vector_store.add_documents(pool)
        vector = vector_store.as_retriever(
            search_type="similarity", search_kwargs={"k": depth}
        )
        lexical = BM25Retriever.from_documents(
            pool, preprocess_func=_word_tokens, k=depth
        )
        vector_indexes[district] = vector
        ensemble_indexes[district] = EnsembleRetriever(
            retrievers=[vector, lexical], weights=[0.5, 0.5], c=60, id_key=_DOCUMENT_KEY
        )

    return VectorOnlyAdapter(vector_indexes, depth), BM25VectorEnsembleAdapter(
        ensemble_indexes, depth
    )
