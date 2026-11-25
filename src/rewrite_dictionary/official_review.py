"""이용 조건을 별도로 확인할 공식 기록의 로컬 검토 조회."""

import json
from pathlib import Path

from .aliases import item_key

OFFICIAL_SNAPSHOT_PATH = Path(__file__).with_name("official_source_snapshot.json")


def review_district_records(
    item: str, district: str, *, path: Path = OFFICIAL_SNAPSHOT_PATH
) -> list[dict]:
    """검토 전용 스냅샷의 지역 안내 중 일치하는 품목 기록을 반환한다."""
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    if snapshot.get("use") != "review_only":
        raise ValueError("검토 전용 공식 자료 스냅샷이 필요합니다.")

    key = item_key(item)
    records = []
    for record in snapshot["records"].values():
        if record["scope"] != "district_guidance":
            continue
        source = snapshot["sources"].get(record["source_id"], {})
        record_district = record.get("district", source.get("district"))
        keys = list(dict.fromkeys(map(item_key, record["items"])))
        if record_district == district and key in keys:
            records.append({**record, "district": record_district, "item_keys": keys})
    return records
