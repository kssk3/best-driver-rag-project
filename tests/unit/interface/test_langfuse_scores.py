"""Langfuse 점수 집계와 비교 패널 테스트. 가짜 응답만 쓰고 외부 호출은 하지 않는다."""

import pytest
import streamlit as st
from screen_helpers import button, new_app

from src.interface import langfuse_scores
from src.interface.langfuse_scores import (
    DatasetGroup,
    LangfuseReadError,
    LangfuseScores,
    build_scores,
)


def score(trace_id: str, value: float, kind: str = "trace") -> dict:
    return {"value": value, "subject": {"kind": kind, "id": trace_id}}


def root(variant, dataset="dataset-1", start="2026-11-26T05:00:00Z") -> dict:
    return {"variant": variant, "dataset_id": dataset, "start": start}


def test_scores_are_grouped_by_dataset_and_variant() -> None:
    roots = {"t1": root("A"), "t2": root("A"), "t3": root("B"), "t4": root("C")}
    result = build_scores(
        [score("t1", 1), score("t2", 0), score("t3", 1), score("t4", 0.5)], roots
    )

    [group] = result.groups
    assert [(s.variant, s.count, s.mean) for s in group.summaries] == [
        ("A", 2, 0.5),
        ("B", 1, 1.0),
        ("C", 1, 0.5),
    ]
    assert result.unlinked == 0


def test_a_variant_without_scores_has_no_mean_not_zero() -> None:
    result = build_scores([score("t1", 1)], {"t1": root("A")})

    summaries = {s.variant: s for s in result.groups[0].summaries}
    assert (summaries["B"].count, summaries["B"].mean) == (0, None)


def test_a_zero_score_is_a_valid_mean() -> None:
    result = build_scores([score("t1", 0)], {"t1": root("A")})

    assert result.groups[0].summaries[0].mean == 0.0


def test_unknown_variant_missing_root_and_non_trace_scores_are_left_out() -> None:
    roots = {"t1": root(None), "t2": root("X"), "t3": root("A")}
    result = build_scores(
        [
            score("t1", 1),  # variant 없음(보관본 루트)
            score("t2", 1),  # A/B/C가 아닌 값
            score("missing", 1),  # 루트를 못 찾음
            score("t3", 1, kind="observation"),  # trace 점수가 아님
        ],
        roots,
    )

    assert result.groups == []
    assert result.unlinked == 4


@pytest.mark.parametrize("value", [None, "1", float("nan"), float("inf")])
def test_non_numeric_values_are_left_out(value) -> None:
    result = build_scores([score("t1", value)], {"t1": root("A")})

    assert result.groups == [] and result.unlinked == 1


def test_datasets_are_not_mixed_and_newest_comes_first() -> None:
    roots = {
        "t1": root("A", "old", "2026-11-25T00:00:00Z"),
        "t2": root("A", "new", "2026-11-26T00:00:00Z"),
        "t3": root("B", None, "2026-11-24T00:00:00Z"),
    }
    result = build_scores([score("t1", 1), score("t2", 0), score("t3", 1)], roots)

    assert [g.dataset_id for g in result.groups] == ["new", "old", "알 수 없음"]
    assert result.groups[0].summaries[0].mean == 0.0


def test_loader_joins_scores_to_root_variant(monkeypatch) -> None:
    def fake_pages(path, params):
        if path == langfuse_scores.SCORES_PATH:
            assert params["name"] == "faithfulness"
            assert params["environment"] == "rag"
            return [score("t1", 1)]
        return [
            {"isRootObservation": True, "traceId": "t1", "startTime": "s",
             "metadata": {"variant": "B", "dataset_id": "d"}},
            {"isRootObservation": False, "traceId": "t1", "metadata": {"variant": "C"}},
        ]  # fmt: skip

    monkeypatch.setattr(langfuse_scores, "_pages", fake_pages)

    [group] = langfuse_scores.load_langfuse_scores().groups
    assert [(s.variant, s.count) for s in group.summaries] == [
        ("A", 0),
        ("B", 1),
        ("C", 0),
    ]


@pytest.mark.parametrize(
    "base",
    [
        "",
        "http://example.org",
        "https://user:pw@example.org",
        "https://example.org?x=1",
    ],
)
def test_unconfigured_or_unsafe_base_url_is_rejected(monkeypatch, base) -> None:
    monkeypatch.setenv("LANGFUSE_BASE_URL", base)
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")

    with pytest.raises(LangfuseReadError) as error:
        langfuse_scores._connect()
    assert error.value.code == "not_configured"


def test_error_never_contains_keys_or_address(monkeypatch) -> None:
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://secret-host.invalid")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-secret")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-secret")

    class Boom:
        def request(self, *args, **kwargs):
            raise OSError("secret-host.invalid pk-secret")

        def close(self):
            pass

    monkeypatch.setattr(
        langfuse_scores, "HTTPSConnection", lambda *args, **kwargs: Boom()
    )

    with pytest.raises(LangfuseReadError) as error:
        langfuse_scores._get("/x", {})
    assert error.value.code == "unreachable"
    assert "secret" not in str(error.value)


# --- 화면 ---


@pytest.fixture(autouse=True)
def _clear_cache():
    st.cache_data.clear()
    yield
    st.cache_data.clear()


def open_panel(monkeypatch, loader):
    monkeypatch.setattr(langfuse_scores, "load_langfuse_scores", loader)
    return new_app().run()


def test_panel_shows_count_and_mean_per_variant_and_unlinked(monkeypatch) -> None:
    result = LangfuseScores(
        [
            DatasetGroup(
                "abcdef123456",
                "2026-11-26T05:00:00Z",
                build_scores(
                    [score("t1", 1), score("t2", 0), score("t3", 1)],
                    {"t1": root("A"), "t2": root("A"), "t3": root("B")},
                )
                .groups[0]
                .summaries,
            )
        ],
        3,
    )
    app = open_panel(monkeypatch, lambda: result)

    assert not app.exception
    assert [(m.label, m.value) for m in app.metric] == [
        ("방식 A", "2건 · 평균 0.500"),
        ("방식 B", "1건 · 평균 1.000"),
        ("방식 C", "0건 · 평균 —"),
    ]
    assert any("abcdef12" in m.value for m in app.markdown)
    assert any("3건" in c.value for c in app.caption)
    assert any("Hit@k" in c.value for c in app.caption)


def test_panel_without_scores_says_so(monkeypatch) -> None:
    app = open_panel(monkeypatch, lambda: LangfuseScores([], 0))

    assert not app.exception
    assert any("아직 없습니다" in i.value for i in app.info)


def test_panel_explains_missing_settings_without_an_error(monkeypatch) -> None:
    def failing():
        raise LangfuseReadError("not_configured")

    app = open_panel(monkeypatch, failing)

    assert not app.exception
    assert not app.error
    assert any("LANGFUSE_BASE_URL" in i.value for i in app.info)


@pytest.mark.parametrize("code", ["unreachable", "http_401"])
def test_panel_shows_only_the_error_kind(monkeypatch, code) -> None:
    def failing():
        raise LangfuseReadError(code)

    app = open_panel(monkeypatch, failing)

    assert not app.exception
    [error] = app.error
    assert "pk-" not in error.value and "sk-" not in error.value
    assert ("연결하지 못했습니다" in error.value) == (code == "unreachable")


def test_refresh_button_reloads_scores(monkeypatch) -> None:
    calls = []

    def loader():
        calls.append(1)
        return LangfuseScores([], 0)

    app = open_panel(monkeypatch, loader)
    button(app, "새로고침").click().run()

    assert len(calls) == 2
