"""청크 집합의 지문.

담당: 이승주
기준선 CSV(results/chunking/chunk_stats.csv의 chunks_sha256)와 평가 기록이 같은 값을 쓰도록 한 곳에 둔다.
chunk_id에는 제목·범위·구 목록·조건이 섞이지 않으므로 ID가 아니라 청크의 모든 필드를 해시한다.
"""

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any

from src.contracts import Chunk


def chunks_fingerprint(chunks: Iterable[Chunk | Mapping[str, Any]]) -> str:
    """청크 집합의 SHA-256. 순서와 무관하고 Chunk와 그 JSON 표현(dict)에서 같은 값이 나온다."""
    rows = [
        c.model_dump(mode="json") if isinstance(c, Chunk) else dict(c) for c in chunks
    ]
    rows.sort(key=lambda row: row["chunk_id"])
    text = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
