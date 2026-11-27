"""Langfuse 점수 집계와 비교 패널 테스트. 가짜 응답만 쓰고 외부 호출은 하지 않는다."""

import pytest
import streamlit as st
from screen_helpers import button, new_app

from src.interface import langfuse_scores
from src.interface.comparison import VariantSummary
from src.interface.langfuse_scores import (
    METRIC_NAMES,
    DatasetGroup,
    LangfuseReadError,
    LangfuseScores,
    build_scores,
)


def score(
    trace_id: str, value, kind: str = "trace", name: str = "faithfulness"
) -> dict:
    return {"name": name, "value": value, "subject": {"kind": kind, "id": trace_id}}


def root(variant, dataset="dataset-1", start="2026-11-26T05:00:00Z") -> dict:
    return {"variant": variant, "dataset_id": dataset, "start": start}


def faithfulness(group: DatasetGroup) -> dict[str, VariantSummary]:
    return {s.variant: s for s in group.metrics["faithfulness"]}


def test_scores_are_grouped_by_dataset_and_variant() -> None:
    roots = {"t1": root("A"), "t2": root("A"), "t3": root("B"), "t4": root("C")}
    result = build_scores(
        [score("t1", 1), score("t2", 0), score("t3", 1), score("t4", 0.5)], roots
    )

    [group] = result.groups
    assert [(s.variant, s.count, s.mean) for s in group.metrics["faithfulness"]] == [
        ("A", 2, 0.5),
        ("B", 1, 1.0),
        ("C", 1, 0.5),
    ]
    assert result.unlinked["faithfulness"] == 0


def test_the_four_ragas_metrics_are_kept_apart_and_other_scores_ignored() -> None:
    roots = {"t1": root("A")}
    result = build_scores(
        [
            score("t1", 1, name="faithfulness"),
            score("t1", 0.4, name="answer_relevancy"),
            score("t1", 0.2, name="context_precision_id_at_5"),
            score("t1", 0.6, name="context_recall_id_at_5"),
            score("t1", 1, name="hit_at_5"),  # 다른 지표는 섞지 않는다.
        ],
        roots,
    )

    [group] = result.groups
    assert set(group.metrics) == set(METRIC_NAMES)
    means = {m: group.metrics[m][0].mean for m in METRIC_NAMES}
    assert means == {
        "faithfulness": 1.0,
        "answer_relevancy": 0.4,
        "context_precision_id_at_5": 0.2,
        "context_recall_id_at_5": 0.6,
    }
    assert sum(result.unlinked.values()) == 0


def test_unlinked_scores_are_counted_per_metric() -> None:
    result = build_scores(
        [
            score("x", 1, name="answer_relevancy"),
            score("x", 1, name="answer_relevancy"),
        ],
        {},
    )

    assert result.groups == []
    assert result.unlinked["answer_relevancy"] == 2
    assert result.unlinked["faithfulness"] == 0


def test_a_variant_without_scores_has_no_mean_not_zero() -> None:
    result = build_scores([score("t1", 1)], {"t1": root("A")})

    summaries = faithfulness(result.groups[0])
    assert (summaries["B"].count, summaries["B"].mean) == (0, None)


def test_a_zero_score_is_a_valid_mean() -> None:
    result = build_scores([score("t1", 0)], {"t1": root("A")})

    assert faithfulness(result.groups[0])["A"].mean == 0.0


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
    assert result.unlinked["faithfulness"] == 4


@pytest.mark.parametrize("value", [None, "1", float("nan"), float("inf")])
def test_non_numeric_values_are_left_out(value) -> None:
    result = build_scores([score("t1", value)], {"t1": root("A")})

    assert result.groups == [] and result.unlinked["faithfulness"] == 1


def test_datasets_are_not_mixed_and_newest_comes_first() -> None:
    roots = {
        "t1": root("A", "old", "2026-11-25T00:00:00Z"),
        "t2": root("A", "new", "2026-11-26T00:00:00Z"),
        "t3": root("B", None, "2026-11-24T00:00:00Z"),
    }
    result = build_scores([score("t1", 1), score("t2", 0), score("t3", 1)], roots)

    assert [g.dataset_id for g in result.groups] == ["new", "old", "알 수 없음"]
    assert faithfulness(result.groups[0])["A"].mean == 0.0


def test_missing_dataset_id_groups_by_evaluation_id() -> None:
    old = root("B", None, "2026-11-24T00:00:00Z") | {"evaluation_id": "e5321726abc"}
    result = build_scores([score("t1", 1)], {"t1": old})

    assert [(g.dataset_id, g.by_evaluation) for g in result.groups] == [
        ("e5321726abc", True)
    ]


def test_loader_joins_scores_to_root_variant(monkeypatch) -> None:
    def fake_pages(path, params):
        if path == langfuse_scores.SCORES_PATH:
            assert params["environment"] == "rag"
            assert "name" not in params  # 4개 지표를 한 번에 읽고 이름으로 거른다.
            return [score("t1", 1)]
        return [
            {"isRootObservation": True, "traceId": "t1", "startTime": "s",
             "metadata": {"variant": "B", "dataset_id": "d"}},
            {"isRootObservation": False, "traceId": "t1", "metadata": {"variant": "C"}},
        ]  # fmt: skip

    monkeypatch.setattr(langfuse_scores, "_pages", fake_pages)

    [group] = langfuse_scores.load_langfuse_scores().groups
    assert [(s.variant, s.count) for s in group.metrics["faithfulness"]] == [
        ("A", 0),
        ("B", 1),
        ("C", 0),
    ]


def _load_with_root_metadata(monkeypatch, metadata):
    def fake_pages(path, params):
        if path == langfuse_scores.SCORES_PATH:
            return [score("t1", 1)]
        assert params["isRootObservation"] == "true"
        return [{"isRootObservation": True, "traceId": "t1", "metadata": metadata}]

    monkeypatch.setattr(langfuse_scores, "_pages", fake_pages)
    return langfuse_scores.load_langfuse_scores()


def test_root_metadata_json_string_is_decoded(monkeypatch) -> None:
    result = _load_with_root_metadata(
        monkeypatch, '{"variant": "B", "dataset_id": "d"}'
    )
    [group] = result.groups
    assert [(s.variant, s.count) for s in group.metrics["faithfulness"]][1] == ("B", 1)


@pytest.mark.parametrize("metadata", ["{깨진", "[1, 2]", "그냥 문자열", 3, None])
def test_unreadable_root_metadata_counts_as_unlinked(monkeypatch, metadata) -> None:
    result = _load_with_root_metadata(monkeypatch, metadata)
    assert result.groups == [] and result.unlinked["faithfulness"] == 1


def test_pages_past_the_limit_are_an_error_not_partial_data(monkeypatch) -> None:
    monkeypatch.setattr(
        langfuse_scores,
        "_get",
        lambda path, params: {"data": [{}], "meta": {"cursor": "next"}},
    )
    with pytest.raises(LangfuseReadError) as error:
        langfuse_scores._pages("/x", {})
    assert error.value.code == "too_many_pages"


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
    app = new_app().run()
    button(app, "점수 불러오기").click().run()  # 버튼을 누른 뒤에만 읽는다
    return app


def html_of(app) -> str:
    return " ".join(str(item.value) for item in app.get("html"))


def test_panel_shows_four_metric_cards_per_variant_and_unlinked(monkeypatch) -> None:
    built = build_scores(
        [score("t1", 1), score("t2", 0), score("t3", 1)],
        {"t1": root("A"), "t2": root("A"), "t3": root("B")},
    )
    result = LangfuseScores(
        [DatasetGroup("abcdef123456", "2026-11-26T05:00:00Z", built.groups[0].metrics)],
        {**built.unlinked, "answer_relevancy": 3},
    )
    app = open_panel(monkeypatch, lambda: result)
    html = html_of(app)

    assert not app.exception
    for title in ("근거 충실도", "답변 관련성", "근거 정밀도", "근거 재현율"):
        assert title in html
    assert "abcdef12" in html
    assert "0.500" in html and "1.000" in html  # 충실도 A 평균, B 평균
    assert "2건" in html
    assert "—" in html  # 점수 없는 방식은 0이 아니라 줄표
    assert any("답변 관련성 3건" in c.value for c in app.caption)
    assert any("Hit@k" in c.value for c in app.caption)


def test_scores_are_not_requested_until_the_button_is_pressed(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        langfuse_scores, "load_langfuse_scores", lambda: calls.append(1)
    )
    app = new_app().run()

    assert not app.exception
    assert (
        calls == []
    )  # 탭을 열지 않아도 실행되는 st.tabs가 느린 요청을 기다리지 않는다
    assert any(b.label == "점수 불러오기" for b in app.button)


def test_panel_without_scores_says_so(monkeypatch) -> None:
    app = open_panel(
        monkeypatch, lambda: LangfuseScores([], {m: 0 for m in METRIC_NAMES})
    )

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
        return LangfuseScores([], {m: 0 for m in METRIC_NAMES})

    app = open_panel(monkeypatch, loader)
    button(app, "새로고침").click().run()

    assert len(calls) == 2


def test_a_read_timeout_is_reported_as_slow_not_unreachable(monkeypatch) -> None:
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://slow.invalid")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")

    class Slow:
        def request(self, *args, **kwargs):
            raise TimeoutError("read timed out")

        def close(self):
            pass

    monkeypatch.setattr(
        langfuse_scores, "HTTPSConnection", lambda *args, **kwargs: Slow()
    )

    with pytest.raises(LangfuseReadError) as error:
        langfuse_scores._get("/x", {})
    assert error.value.code == "timeout"


def test_panel_explains_a_slow_server_and_remembers_the_failure(monkeypatch) -> None:
    calls = []

    def slow():
        calls.append(1)
        raise LangfuseReadError("timeout")

    app = open_panel(monkeypatch, slow)
    app.run()  # 다시 그려도 실패를 잠시 재사용해 또 기다리지 않는다.

    [error] = app.error
    assert "응답하지 않습니다" in error.value
    assert len(calls) == 1
    assert any(b.label == "새로고침" for b in app.button)
