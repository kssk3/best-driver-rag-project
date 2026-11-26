import json

import pytest

from scripts import exp_posthoc_final
from scripts.exp_embed_input import (
    TRANSFORM_VERSION,
    VARIANT_ID_MARKER,
    variant_index_id,
)


def test_variant_index_id_changes_with_texts_identity_and_is_stable() -> None:
    v = [[0.1, 0.2], [0.3, 0.4]]
    base = variant_index_id("index-1", "emb-a", ["가", "나"], v)
    assert base == variant_index_id("index-1", "emb-a", ["가", "나"], v)
    assert base != variant_index_id("index-1", "emb-a", ["가", "다"], v)
    assert base != variant_index_id("index-1", "emb-b", ["가", "나"], v)
    # 같은 입력이라도 제공자가 다른 벡터를 돌려주면 다른 색인이다.
    assert base != variant_index_id(
        "index-1", "emb-a", ["가", "나"], [[0.1, 0.2], [0.3, 0.5]]
    )
    assert base.startswith("index-1" + VARIANT_ID_MARKER)
    assert TRANSFORM_VERSION  # 변환 버전이 해시에 들어간다


def settings_file(tmp_path, index_path: str):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"index_path": index_path}), encoding="utf-8")
    return path


def test_posthoc_runner_rejects_an_untransformed_index(tmp_path, monkeypatch) -> None:
    fake = type("I", (), {"metadata": type("M", (), {"index_id": "index-plain"})()})()
    monkeypatch.setattr(exp_posthoc_final, "load_index", lambda path: fake)
    with pytest.raises(SystemExit):
        exp_posthoc_final.require_variant_index(settings_file(tmp_path, "x.json"))


def test_posthoc_runner_accepts_a_transformed_index(tmp_path, monkeypatch) -> None:
    transformed = "index-1" + VARIANT_ID_MARKER + "abc"
    fake = type("I", (), {"metadata": type("M", (), {"index_id": transformed})()})()
    monkeypatch.setattr(exp_posthoc_final, "load_index", lambda path: fake)
    exp_posthoc_final.require_variant_index(settings_file(tmp_path, "x.json"))


def test_posthoc_runner_rejects_an_index_from_another_transform_version(
    tmp_path, monkeypatch
) -> None:
    old = "index-1-embed-input-exp"  # v1 색인의 실제 ID 형식
    fake = type("I", (), {"metadata": type("M", (), {"index_id": old})()})()
    monkeypatch.setattr(exp_posthoc_final, "load_index", lambda path: fake)
    with pytest.raises(SystemExit):
        exp_posthoc_final.require_variant_index(settings_file(tmp_path, "x.json"))
