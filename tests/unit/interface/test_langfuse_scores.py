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


def root(
    variant,
    dataset="dataset-1",
    start="2026-11-26T05:00:00Z",
    rewrite=False,
    eligible=True,
    run_id=None,
) -> dict:
    return {
        "variant": variant,
        "dataset_id": dataset,
        "rewrite_enabled": rewrite,
        "comparison_eligible": eligible,
        "run_id": run_id,
        "start": start,
    }


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
            score("y", 1, name="answer_relevancy"),
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
    }
    result = build_scores([score("t1", 1), score("t2", 0)], roots)

    assert [g.dataset_id for g in result.groups] == ["new", "old"]
    assert faithfulness(result.groups[0])["A"].mean == 0.0


def test_rewrite_off_and_on_of_the_same_dataset_are_not_mixed() -> None:
    roots = {"t1": root("C", "d1", rewrite=False), "t2": root("C", "d1", rewrite=True)}
    result = build_scores([score("t1", 1), score("t2", 0)], roots)

    assert {(g.dataset_id, g.rewrite_enabled) for g in result.groups} == {
        ("d1", False),
        ("d1", True),
    }
    by_rewrite = {g.rewrite_enabled: faithfulness(g)["C"] for g in result.groups}
    assert (by_rewrite[False].mean, by_rewrite[True].mean) == (1.0, 0.0)


def test_scores_without_verifiable_dataset_or_rewrite_are_counted_apart() -> None:
    roots = {
        "t1": root("A", None),  # 평가 세트를 모른다
        "t2": {
            "variant": "A",
            "dataset_id": "d",
            "comparison_eligible": True,
        },  # 리라이트 여부를 모른다
        "t3": {
            "variant": "A",
            "dataset_id": "d",
            "rewrite_enabled": False,
        },  # 비교 자격을 모른다
    }
    result = build_scores([score("t1", 1), score("t2", 1), score("t3", 1)], roots)

    assert result.groups == []  # 확인 못 한 평가가 한 그룹으로 섞이지 않는다.
    assert result.unverified["faithfulness"] == 3
    assert result.unlinked["faithfulness"] == 0


def test_scores_marked_not_eligible_are_left_out_and_counted() -> None:
    result = build_scores(
        [score("t1", 1), score("t2", 0)],
        {"t1": root("A"), "t2": root("A", eligible=False)},
    )

    [group] = result.groups
    assert faithfulness(group)["A"].count == 1
    assert result.ineligible["faithfulness"] == 1


def test_score_metadata_groups_a_score_on_an_existing_root_without_local_records() -> (
    None
):
    # 새 점수는 기존 루트에 붙고 비교용 값은 점수 metadata에만 있다. 로컬 CSV 없이도 확인 불가가 아니다.
    bare_root = {"variant": "C", "start": "2026-11-27T00:00:00Z"}
    new_score = score("t1", 1) | {
        "metadata": '{"dataset_id": "d7", "rewrite_enabled": "true", "comparison_eligible": "true"}'
    }
    nested = score("t2", 0) | {
        "details": {
            "metadata": {
                "dataset_id": "d7",
                "rewrite_enabled": "true",
                "comparison_eligible": "true",
            }
        }
    }

    result = build_scores([new_score, nested], {"t1": bare_root, "t2": bare_root})

    [group] = result.groups
    assert (group.dataset_id, group.rewrite_enabled) == ("d7", True)
    assert faithfulness(group)["C"].count == 2
    assert result.unverified["faithfulness"] == 0


def test_score_metadata_not_eligible_is_counted_as_excluded() -> None:
    bare_root = {"variant": "A"}
    meta = {
        "dataset_id": "d7",
        "rewrite_enabled": "false",
        "comparison_eligible": "false",
    }

    result = build_scores([score("t1", 1) | {"metadata": meta}], {"t1": bare_root})

    assert result.groups == []
    assert (
        result.ineligible["faithfulness"] == 1
        and result.unverified["faithfulness"] == 0
    )


def test_score_metadata_wins_over_root_metadata() -> None:
    result = build_scores(
        [score("t1", 1) | {"metadata": {"rewrite_enabled": "true"}}],
        {"t1": root("C", "d1", rewrite=False)},
    )

    [group] = result.groups
    assert group.rewrite_enabled is True


def test_scores_are_requested_with_details_so_their_metadata_comes_back(
    monkeypatch,
) -> None:
    seen = {}

    def fake_pages(path, params):
        if path == langfuse_scores.SCORES_PATH:
            seen.update(params)
        return []

    monkeypatch.setattr(langfuse_scores, "_pages", fake_pages)
    langfuse_scores.load_langfuse_scores()

    assert "details" in seen["fields"] and "subject" in seen["fields"]


def test_eligibility_applies_only_to_faithfulness_not_to_the_other_metrics() -> None:
    # 근거 없는 답변은 Faithfulness만 비교 대상이 아니다. 같은 실행의 다른 지표는 포함한다.
    runs = {"r1": {"dataset_id": "d1", "rewrite_enabled": False, "eligible": False}}
    result = build_scores(
        [
            score("t1", 1, name="faithfulness"),
            score("t1", 0.7, name="answer_relevancy"),
        ],
        {"t1": {"variant": "A", "run_id": "r1"}},
        runs,
    )

    [group] = result.groups
    assert result.ineligible["faithfulness"] == 1
    assert group.metrics["answer_relevancy"][0].count == 1
    assert group.metrics["faithfulness"][0].count == 0


def test_a_run_scored_twice_counts_once_with_the_latest_score() -> None:
    old = score("t1", 0.0) | {"timestamp": "2026-11-26T01:00:00Z"}
    new = score("t1", 1.0) | {"timestamp": "2026-11-27T01:00:00Z"}

    for order in ([old, new], [new, old]):
        [group] = build_scores(order, {"t1": root("A")}).groups
        assert faithfulness(group)["A"].count == 1
        assert faithfulness(group)["A"].mean == 1.0


def test_run_index_finds_nested_folders_and_skips_local(tmp_path) -> None:
    nested = tmp_path / "errata" / "abc"
    nested.mkdir(parents=True)
    (nested / "runs.csv").write_text(
        "run_id,dataset_id,rewrite_enabled" + chr(10) + "r-nested,d1,false" + chr(10),
        encoding="utf-8",
    )
    (tmp_path / "local").mkdir()
    (tmp_path / "local" / "runs.csv").write_text(
        "run_id,dataset_id,rewrite_enabled" + chr(10) + "r-local,d1,false" + chr(10),
        encoding="utf-8",
    )

    runs = langfuse_scores.load_run_index(tmp_path)

    assert "r-nested" in runs and "r-local" not in runs


def test_a_trace_with_two_roots_is_left_out_as_unverified(monkeypatch) -> None:
    def fake_pages(path, params):
        if path == langfuse_scores.SCORES_PATH:
            return [score("t1", 1)]
        meta = {
            "variant": "A",
            "dataset_id": "d",
            "rewrite_enabled": False,
            "comparison_eligible": True,
        }
        return [
            {"isRootObservation": True, "traceId": "t1", "metadata": meta},
            {"isRootObservation": True, "traceId": "t1", "metadata": meta},
        ]

    monkeypatch.setattr(langfuse_scores, "_pages", fake_pages)
    result = langfuse_scores.load_langfuse_scores()

    assert result.groups == [] and result.unverified["faithfulness"] == 1


def test_only_rows_that_are_really_roots_are_used(monkeypatch) -> None:
    def fake_pages(path, params):
        if path == langfuse_scores.SCORES_PATH:
            return [score("t1", 1)]
        return [
            {"isRootObservation": "true", "traceId": "t1", "metadata": {"variant": "A"}}
        ]

    monkeypatch.setattr(langfuse_scores, "_pages", fake_pages)
    result = langfuse_scores.load_langfuse_scores()

    assert result.groups == [] and result.unlinked["faithfulness"] == 1


def _fake_connection(response_factory):
    class Connection:
        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            return response_factory()

        def close(self):
            pass

    return Connection


def test_a_truncated_response_body_becomes_a_read_error(monkeypatch) -> None:
    import http.client

    class Truncated:
        status = 200

        def read(self):
            raise http.client.IncompleteRead(b"{", 100)

    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://slow.invalid")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    monkeypatch.setattr(
        langfuse_scores,
        "HTTPSConnection",
        lambda *a, **k: _fake_connection(Truncated)(),
    )

    with pytest.raises(LangfuseReadError) as error:
        langfuse_scores._get("/x", {})
    assert error.value.code == "bad_response"


def test_panel_shows_an_error_and_refresh_when_the_body_is_cut_off(monkeypatch) -> None:
    import http.client

    class Truncated:
        status = 200

        def read(self):
            raise http.client.IncompleteRead(b"{", 100)

    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://slow.invalid")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    monkeypatch.setattr(
        langfuse_scores,
        "HTTPSConnection",
        lambda *a, **k: _fake_connection(Truncated)(),
    )
    app = new_app().run()
    button(app, "점수 불러오기").click().run()

    assert not app.exception  # Streamlit 예외가 아니라 안내로 보인다
    [error] = app.error
    assert "끊겼습니다" in error.value
    assert any(b.label == "새로고침" for b in app.button)


def test_a_newer_text_annotation_does_not_hide_the_numeric_score() -> None:
    numeric = score("t1", 1.0) | {
        "dataType": "NUMERIC",
        "timestamp": "2026-11-26T01:00:00Z",
    }
    text = score("t1", "검토 필요") | {
        "dataType": "TEXT",
        "timestamp": "2026-11-27T01:00:00Z",
    }
    boolean_like = score("t1", True) | {"timestamp": "2026-11-28T01:00:00Z"}

    [group] = build_scores([numeric, text, boolean_like], {"t1": root("A")}).groups

    assert faithfulness(group)["A"].count == 1
    assert faithfulness(group)["A"].mean == 1.0


def test_a_root_without_run_id_is_matched_through_the_trace_id() -> None:
    from src.observability.tracing import trace_id_for_run

    trace = trace_id_for_run("run-r1")
    runs = {"run-r1": {"dataset_id": "d3", "rewrite_enabled": True, "eligible": True}}
    repaired_root = {
        "variant": "C",
        "start": "2026-11-26T00:00:00Z",
    }  # 보관본 복구 루트: variant만 있다.

    result = build_scores([score(trace, 1)], {trace: repaired_root}, runs)

    [group] = result.groups
    assert (group.dataset_id, group.rewrite_enabled) == ("d3", True)


def test_a_run_recorded_with_conflicting_datasets_is_left_out_as_unverified(
    tmp_path,
) -> None:
    for folder, dataset in (("a", "d1"), ("b", "d2")):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "runs.csv").write_text(
            "run_id,dataset_id,rewrite_enabled"
            + chr(10)
            + f"r1,{dataset},false"
            + chr(10),
            encoding="utf-8",
        )
    runs = langfuse_scores.load_run_index(tmp_path)

    result = build_scores(
        [score("t1", 1)], {"t1": {"variant": "A", "run_id": "r1"}}, runs
    )

    assert result.groups == [] and result.unverified["faithfulness"] == 1


def _run(case, dataset="d1", rewrite=False):
    return {
        "dataset_id": dataset,
        "rewrite_enabled": rewrite,
        "eligible": True,
        "case_id": case,
    }


def test_the_same_case_rerun_under_another_run_id_counts_once() -> None:
    # 같은 데이터셋·문항·방식을 다시 실행하면 run_id(trace)가 달라도 가장 최근 점수 하나만 쓴다.
    runs = {"r1": _run("c1"), "r2": _run("c1")}
    roots = {
        "t1": {"variant": "A", "run_id": "r1", "start": "2026-11-26T00:00:00Z"},
        "t2": {"variant": "A", "run_id": "r2", "start": "2026-11-27T00:00:00Z"},
    }
    old = score("t1", 0.0) | {"timestamp": "2026-11-26T01:00:00Z"}
    new = score("t2", 1.0) | {"timestamp": "2026-11-27T01:00:00Z"}

    [group] = build_scores([old, new], roots, runs).groups

    assert faithfulness(group)["A"].count == 1
    assert faithfulness(group)["A"].mean == 1.0


def test_rerunning_only_one_variant_does_not_change_the_others() -> None:
    runs = {"a1": _run("c1"), "b1": _run("c1"), "a2": _run("c1")}
    roots = {
        "ta1": {"variant": "A", "run_id": "a1"},
        "tb1": {"variant": "B", "run_id": "b1"},
        "ta2": {"variant": "A", "run_id": "a2"},
    }
    stamps = {"ta1": "2026-11-26", "tb1": "2026-11-26", "ta2": "2026-11-27"}
    scores = [
        score(trace, 0.5) | {"timestamp": stamp} for trace, stamp in stamps.items()
    ]

    [group] = build_scores(scores, roots, runs).groups

    assert (faithfulness(group)["A"].count, faithfulness(group)["B"].count) == (1, 1)


def test_different_cases_and_rewrite_settings_are_not_merged_by_the_dedup() -> None:
    runs = {
        "r1": _run("c1"),
        "r2": _run("c2"),
        "r3": _run("c1", rewrite=True),
    }
    roots = {
        "t1": {"variant": "C", "run_id": "r1"},
        "t2": {"variant": "C", "run_id": "r2"},
        "t3": {"variant": "C", "run_id": "r3"},
    }

    result = build_scores([score("t1", 1), score("t2", 0), score("t3", 1)], roots, runs)

    counts = {g.rewrite_enabled: faithfulness(g)["C"].count for g in result.groups}
    assert counts == {False: 2, True: 1}


def test_scores_without_a_known_case_stay_one_per_trace_and_are_counted() -> None:
    bare = {
        "variant": "A",
        "dataset_id": "d",
        "rewrite_enabled": False,
        "comparison_eligible": True,
    }
    result = build_scores([score("t1", 1), score("t2", 0)], {"t1": bare, "t2": bare})

    [group] = result.groups
    assert faithfulness(group)["A"].count == 2
    assert result.case_unknown["faithfulness"] == 2


def test_score_metadata_supplies_case_and_variant_for_deduplication() -> None:
    meta = {
        "dataset_id": "d1",
        "rewrite_enabled": "false",
        "comparison_eligible": "true",
        "case_id": "c1",
        "variant": "B",
    }
    bare_root = {"start": "2026-11-27T00:00:00Z"}  # 복구 루트: variant도 run_id도 없다.
    first = score("t1", 0.0) | {"metadata": meta, "timestamp": "2026-11-26T00:00:00Z"}
    second = score("t2", 1.0) | {"metadata": meta, "timestamp": "2026-11-27T00:00:00Z"}

    [group] = build_scores([first, second], {"t1": bare_root, "t2": bare_root}).groups

    assert faithfulness(group)["B"].count == 1 and faithfulness(group)["B"].mean == 1.0


def test_extra_result_folders_link_runs_only_when_configured(
    tmp_path, monkeypatch
) -> None:
    shared, extra = tmp_path / "results", tmp_path / "local-results"
    (shared / "a").mkdir(parents=True)
    (extra / "b").mkdir(parents=True)
    (shared / "a" / "runs.csv").write_text(
        "run_id,dataset_id,rewrite_enabled" + chr(10) + "r-shared,d1,false" + chr(10),
        encoding="utf-8",
    )
    (extra / "b" / "runs.csv").write_text(
        "run_id,dataset_id,rewrite_enabled" + chr(10) + "r-local,d1,false" + chr(10),
        encoding="utf-8",
    )

    monkeypatch.delenv("RAG_RESULTS_INDEX_DIRS", raising=False)
    assert "r-local" not in langfuse_scores.load_run_index(shared)

    monkeypatch.setenv("RAG_RESULTS_INDEX_DIRS", str(extra))
    runs = langfuse_scores.load_run_index(shared)
    assert "r-local" in runs and "r-shared" in runs


def test_an_unlinked_score_says_how_to_connect_it_in_the_panel(monkeypatch) -> None:
    unverified = {**{m: 0 for m in METRIC_NAMES}, "faithfulness": 2}
    app = open_panel(
        monkeypatch,
        lambda: LangfuseScores([], {m: 0 for m in METRIC_NAMES}, unverified),
    )

    text = " ".join(c.value for c in app.caption)
    assert "비교 정보" in text and "RAG_RESULTS_INDEX_DIRS" in text


def test_old_scores_are_confirmed_through_the_run_id_in_local_records() -> None:
    old_root = {"variant": "B", "run_id": "r1", "start": "2026-11-26T00:00:00Z"}
    runs = {"r1": {"dataset_id": "d9", "rewrite_enabled": False, "eligible": True}}

    result = build_scores([score("t1", 1)], {"t1": old_root}, runs)

    [group] = result.groups
    assert (group.dataset_id, group.rewrite_enabled) == ("d9", False)
    assert result.unverified["faithfulness"] == 0


def test_run_index_reads_dataset_rewrite_and_eligibility_from_results(tmp_path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "runs.csv").write_text(
        "run_id,dataset_id,rewrite_enabled\nr1,d1,false\nr2,d1,true\n",
        encoding="utf-8",
    )
    (tmp_path / "a" / "scores.csv").write_text(
        "run_id,dataset_id,rewrite_enabled,comparison_eligible\n"
        "r1,d1,false,true\nr1,d1,false,false\n",
        encoding="utf-8",
    )

    runs = langfuse_scores.load_run_index(tmp_path)

    assert runs["r1"] == {
        "dataset_id": "d1",
        "rewrite_enabled": False,
        "eligible": False,
        "case_id": None,
    }
    assert runs["r2"]["eligible"] is None  # runs.csv에는 비교 자격이 없다.


def test_loader_joins_scores_to_root_variant(monkeypatch) -> None:
    def fake_pages(path, params):
        if path == langfuse_scores.SCORES_PATH:
            assert params["environment"] == "rag"
            # 4개 지표만 서버에서 거른다(모르는 이름의 점수가 페이지 상한을 채우지 않게).
            assert params["name"].split(",") == list(METRIC_NAMES)
            return [score("t1", 1)]
        return [
            {"isRootObservation": True, "traceId": "t1", "startTime": "s",
             "metadata": {"variant": "B", "dataset_id": "d", "rewrite_enabled": False, "comparison_eligible": True}},
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
        monkeypatch,
        '{"variant": "B", "dataset_id": "d", "rewrite_enabled": false, "comparison_eligible": true}',
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


def test_uploaded_score_metadata_lets_a_rerun_count_once_without_local_csv() -> None:
    from src.observability import tracing

    def uploaded(run_id: str, value: float, scored_at: str) -> tuple[str, dict]:
        row = {
            "evaluation_id": f"evaluation-{run_id}",
            "dataset_id": "d1",
            "case_id": "c1",
            "rewrite_enabled": "false",
            "comparison_eligible": "true",
            "run_id": run_id,
            "run_kind": "rag",
            "metric": "faithfulness",
            "score": str(value),
            "scored_at_utc": scored_at,
            "run_started_at_utc": "2026-11-26T00:00:00+00:00",
        }
        _, payload = tracing._payloads(row)  # 업로드하는 점수 형식 그대로
        trace = payload["traceId"]
        return trace, score(trace, value) | {
            "metadata": payload["metadata"],
            "timestamp": payload["timestamp"],
        }

    first_trace, first = uploaded("run-a", 0.0, "2026-11-26T01:00:00+00:00")
    second_trace, second = uploaded("run-b", 1.0, "2026-11-27T01:00:00+00:00")
    bare_root = {"variant": "B", "start": "2026-11-27T00:00:00Z"}  # 보관본 루트

    [group] = build_scores(
        [first, second], {first_trace: bare_root, second_trace: bare_root}
    ).groups

    assert faithfulness(group)["B"].count == 1 and faithfulness(group)["B"].mean == 1.0
