"""수집 전에 사람이 확인한 접근·이용조건 기록을 검사한다."""

from datetime import date
from urllib.parse import urlparse


def validate_review(review: dict) -> None:
    """미확인·제한 기록이나 근거가 빠진 승인은 수집 전에 중단한다."""
    if review.get("collection_status") != "approved":
        raise ValueError("수집 검토가 승인되지 않았어요.")
    for field in ("reviewer", "evidence", "scope", "conditions"):
        if not isinstance(review.get(field), str) or not review[field].strip():
            raise ValueError(f"검토 기록의 {field}가 필요해요.")
    parsed = urlparse(review.get("evidence_url", ""))
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        raise ValueError("정책 근거 URL이 필요해요.")
    checked = date.fromisoformat(review.get("checked_at", ""))
    expires = date.fromisoformat(review.get("expires_at", ""))
    if not checked <= date.today() <= expires:
        raise ValueError("검토일 또는 재검토 기한을 확인하세요.")
