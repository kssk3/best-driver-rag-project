"""교체 가능한 임베딩 연결. 기본 예시는 외부 호출 없는 흐름 검증용이다."""

import hashlib
from importlib.metadata import version
import json
import math
import os
from pathlib import Path
import re
from typing import Protocol


class EmbeddingProvider(Protocol):
    # 모델, 차원, 전처리 등 벡터에 영향을 주는 설정이 바뀌면 identity도 바꾼다.
    identity: str

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class DemoHashEmbeddings:
    """문자 쌍을 해시한 결정적 데모 벡터. 의미 검색 품질 평가에 사용하지 않는다."""

    def __init__(self, dimensions: int = 64):
        if type(dimensions) is not int or dimensions < 1:
            raise ValueError("dimensions는 양의 정수여야 합니다.")
        self.dimensions = dimensions
        self.identity = (
            f"demo-hash-character-bigrams-v1:dimensions={dimensions}"
            ":casefold=1:whitespace=collapse:normalization=l2"
        )

    def embed_query(self, text: str) -> list[float]:
        text = " ".join(text.casefold().split())
        vector = [0.0] * self.dimensions
        parts = [text] if len(text) < 2 else [text[i:i + 2] for i in range(len(text) - 1)]
        for part in parts:
            if part:
                bucket = int.from_bytes(hashlib.sha256(part.encode()).digest()[:8])
                vector[bucket % self.dimensions] += 1.0
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector] if norm else vector

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]


class LangChainEmbeddingsAdapter:
    """이미 설정한 LangChain 임베더를 주입한다. 생성만으로 요청하지 않는다."""

    def __init__(self, client, identity: str):
        if not isinstance(identity, str) or not identity.strip():
            raise ValueError("모델과 설정을 구분하는 identity가 필요합니다.")
        self.client = client
        self.identity = identity

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.client.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        return self.client.embed_query(text)


def create_openai_embeddings(
    model: str, dimensions: int | None = None
) -> LangChainEmbeddingsAdapter:
    """호출자가 모델을 선택한 경우만 생성. API 키는 라이브러리가 환경에서 읽는다."""
    if not isinstance(model, str) or not model.strip():
        raise ValueError("OpenAI 임베딩 모델을 명시해야 합니다.")
    if dimensions is not None and (type(dimensions) is not int or dimensions < 1):
        raise ValueError("dimensions는 양의 정수여야 합니다.")
    from langchain_openai import OpenAIEmbeddings

    client = OpenAIEmbeddings(model=model, dimensions=dimensions)
    identity = json.dumps(
        {"provider": "openai", "model": model, "dimensions": dimensions,
         "base_url": client.openai_api_base or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1",
         "adapter": "langchain-openai:" + version("langchain-openai")},
        sort_keys=True, ensure_ascii=False,
    )
    return LangChainEmbeddingsAdapter(client, identity)


def configure_key_file(path: Path | None) -> None:
    """명시된 로컬 키를 프로세스에서만 사용한다. 파일/키 내용을 출력하지 않는다."""
    if path is None:
        return
    text = path.read_text(encoding="utf-8-sig")
    keys = set(re.findall(r"(?<![A-Za-z0-9_-])sk-[A-Za-z0-9_-]{20,}", text))
    if len(keys) != 1:
        raise ValueError("키 파일에는 구분 가능한 OpenAI 키 한 개가 필요합니다.")
    os.environ["OPENAI_API_KEY"] = keys.pop()
    # 키 파일 방식은 OpenAI 공식 임베딩 실행용이다. 별도 프록시로 보내지 않는다.
    os.environ["OPENAI_BASE_URL"] = "https://api.openai.com/v1"
    os.environ["OPENAI_API_BASE"] = "https://api.openai.com/v1"
    os.environ.pop("OPENAI_LOG", None)


class BoundedEmbeddings:
    """청크를 토큰 한도 안에서만 전송한다. SDK의 자동 분할/평균을 사용하지 않는다."""

    def __init__(self, provider, *, max_tokens: int = 8191):
        import tiktoken

        self.provider = provider
        self.identity = provider.identity
        self.encoding = tiktoken.get_encoding("cl100k_base")
        self.max_tokens = max_tokens

    def counts(self, texts: list[str]) -> list[int]:
        counts = [len(self.encoding.encode(text, disallowed_special=())) for text in texts]
        if any(count > self.max_tokens or count == 0 for count in counts):
            raise ValueError("빈 입력 또는 임베딩 토큰 한도를 넘는 청크가 있습니다. 청킹을 조정하세요.")
        return counts

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        counts = self.counts(texts)
        result = []
        batch, tokens = [], 0
        for text, count in zip(texts, counts, strict=True):
            if batch and (len(batch) >= 64 or tokens + count > 100_000):
                result.extend(self.provider.embed_documents(batch))
                batch, tokens = [], 0
            batch.append(text)
            tokens += count
        if batch:
            result.extend(self.provider.embed_documents(batch))
        return result

    def embed_query(self, text: str) -> list[float]:
        self.counts([text])
        return self.provider.embed_query(text)
