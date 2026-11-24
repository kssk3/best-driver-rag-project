"""응답 어댑터 단위 테스트. 합성 예시(fixtures)만 사용한다."""

import json
from pathlib import Path

import pytest

from src.interface.adapter import to_view_response

FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "sample_responses.json"


def load_samples() -> dict:
    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return {key: value for key, value in data.items() if not key.startswith("_")}


SAMPLES = load_samples()


@pytest.mark.parametrize("name", SAMPLES)
def test_status_is_preserved(name: str) -> None:
    view = to_view_response(SAMPLES[name], kind="fixture")
    assert view.status == name
    assert view.kind == "fixture"


def test_unknown_status_raises() -> None:
    with pytest.raises(ValueError):
        to_view_response({"status": "success"}, kind="fixture")


def test_missing_model_inputs_is_none_not_empty() -> None:
    view = to_view_response(SAMPLES["insufficient_evidence"], kind="fixture")
    assert view.model_inputs is None


def test_answered_keeps_candidates_inputs_and_citations() -> None:
    view = to_view_response(SAMPLES["answered"], kind="fixture")
    assert len(view.candidates) == 3
    assert view.model_inputs == ["fx-chunk-001", "fx-chunk-002"]
    assert [c.chunk_id for c in view.citations] == ["fx-chunk-001"]