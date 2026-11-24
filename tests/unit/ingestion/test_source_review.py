import unittest
from datetime import date, timedelta

from src.ingestion.source_review import validate_review


class SourceReviewTests(unittest.TestCase):
    def test_approval_requires_evidence(self):
        with self.assertRaises(ValueError):
            validate_review({"collection_status": "approved"})

    def test_valid_review_and_expiry(self):
        today = date.today()
        record = {
            "collection_status": "approved",
            "reviewer": "test",
            "checked_at": today.isoformat(),
            "expires_at": (today + timedelta(days=1)).isoformat(),
            "evidence_url": "https://example.org/policy",
            "evidence": "test evidence",
            "scope": "test scope",
            "conditions": "test conditions",
        }
        validate_review(record)
        record["expires_at"] = (today - timedelta(days=1)).isoformat()
        with self.assertRaises(ValueError):
            validate_review(record)


if __name__ == "__main__":
    unittest.main()
