"""점수 파일이 실제 A/B/C 검색 결과와 진단용 실행을 구분하는지 확인한다."""

import asyncio
import csv
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from scripts.score_answers import main
from src.evaluation.answer_metrics import score_archive
from src.evaluation.csv_export import write_evaluation_csv
from src.evaluation.runner import load_evaluation_cases

STAMP = "2026-11-25T064832Z"
ARCHIVE = Path("results/team-a") / STAMP / "evaluation.json"
CASES = Path("eval/snapshots") / STAMP / "cases.csv"


def attempt(
    variant, case_index=0, configuration="configured", *, rewrite_enabled=False
):
    item = json.loads(ARCHIVE.read_text(encoding="utf-8"))[case_index]
    record = item["record"]
    run_id = f"{item['run_id']}-{variant}-{rewrite_enabled}"
    item["run_id"] = record["run_id"] = run_id
    item["response"]["run_id"] = record["response"]["run_id"] = run_id
    item["configuration"] = configuration
    record["options"]["variant"] = variant
    record["options"]["rewrite_enabled"] = rewrite_enabled
    if rewrite_enabled:
        rewrite = next(
            stage for stage in record["stages"] if stage["name"] == "rewrite"
        )
        rewrite["status"] = "ok"
    return item


def export(directory, attempts):
    cases = load_evaluation_cases(CASES.with_suffix(".json"))
    write_evaluation_csv(directory, cases, attempts)
    archive = directory / "evaluation.json"
    archive.write_text(json.dumps(attempts, ensure_ascii=False), encoding="utf-8")
    return archive


def read_csv(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def score(archive, output, scorer, cases=None):
    ok = asyncio.run(
        score_archive(
            archive, cases or archive.with_name("cases.csv"), output, scorer=scorer
        )
    )
    return ok, read_csv(output / "scores.csv")


def test_variant_c_rewrite_off_and_on_keep_separate_scores(tmp_path):
    """동일 문항을 실행한 C+리라이트의 점수는 보존하고 기본 비교에는 C OFF만 넣는다."""
    archive = export(tmp_path, [attempt("C"), attempt("C", rewrite_enabled=True)])
    scorer = AsyncMock(
        side_effect=[SimpleNamespace(value=0.0), SimpleNamespace(value=1.0)]
    )
    ok, rows = score(archive, tmp_path / "scored", scorer)
    assert ok and scorer.await_count == 2
    assert [
        (
            r["variant"],
            r["rewrite_enabled"],
            r["score"],
            r["comparison_eligible"],
            r["comparison_exclusion_reason"],
        )
        for r in rows
    ] == [
        ("C", "false", "0.0", "true", ""),
        ("C", "true", "1.0", "false", "rewrite_enabled"),
    ]


def test_original_rewrite_option_conflicts_with_run_table(tmp_path):
    """공식 CSV와 원본 옵션의 리라이트 값이 충돌하면 채점기에 입력을 보내지 않는다."""
    item = attempt("C", rewrite_enabled=True)
    archive = export(tmp_path, [item])
    item["record"]["options"]["rewrite_enabled"] = False
    archive.write_text(json.dumps([item], ensure_ascii=False), encoding="utf-8")
    scorer = AsyncMock()
    ok, (row,) = score(archive, tmp_path / "scored", scorer)
    assert not ok
    scorer.assert_not_awaited()
    assert (row["status"], row["score"], row["reason"]) == (
        "input_error",
        "",
        "run_rewrite_mismatch",
    )
    assert (row["comparison_eligible"], row["comparison_exclusion_reason"]) == (
        "false",
        "run_rewrite_mismatch",
    )


def test_missing_archived_rewrite_is_not_inferred_from_exporter_default(tmp_path):
    """원본 옵션에 리라이트가 생략된 경우 내보내기의 기본값 false를 비교에 쓰지 않는다."""
    item = attempt("C")
    del item["record"]["options"]["rewrite_enabled"]
    archive = export(tmp_path, [item])
    assert read_csv(archive.with_name("runs.csv"))[0]["rewrite_enabled"] == "false"
    scorer = AsyncMock(return_value=SimpleNamespace(value=0.5))
    ok, (row,) = score(archive, tmp_path / "scored", scorer)
    assert ok and (row["rewrite_enabled"], row["status"], row["score"]) == (
        "",
        "scored",
        "0.5",
    )
    assert (row["comparison_eligible"], row["comparison_exclusion_reason"]) == (
        "false",
        "missing_recorded_rewrite",
    )


def test_real_search_variants_are_comparable_even_at_zero(tmp_path):
    """실험 설정명과 검색 variant를 구분하고 유효한 0점도 비교에 포함한다."""
    attempts = [
        attempt("A"),
        attempt("B"),
        attempt("C", configuration="실험-3"),
    ]
    archive = export(tmp_path, attempts)
    scorer = AsyncMock(return_value=SimpleNamespace(value=0.0))
    ok, rows = score(archive, tmp_path / "scored", scorer)
    assert ok and scorer.await_count == 3
    for row, item in zip(rows, attempts, strict=True):
        assert row["configuration"] == item["configuration"]
        assert row["variant"] == item["record"]["options"]["variant"]
        assert (row["status"], row["score"]) == ("scored", "0.0")
        assert row["comparison_eligible"] == "true"
        assert row["comparison_exclusion_reason"] == ""


@pytest.mark.parametrize(
    ("changed", "reason"),
    [
        ("configuration", "run_configuration_mismatch"),
        ("blank_configuration", "run_configuration_mismatch"),
        ("blank_retrieval", "retrieval_status_mismatch"),
        ("variant", "run_variant_mismatch"),
        ("run_kind", "run_kind_mismatch"),
        ("options_run_kind", "run_kind_mismatch"),
        ("retrieve_status", "retrieval_status_mismatch"),
        ("duplicate_retrieve", "ambiguous_retrieval_stage"),
    ],
)
def test_mixed_run_metadata_is_rejected_before_judging(tmp_path, changed, reason):
    """원본 표와 충돌한 행은 채점하지 않고 다음 실행의 정상 점수를 보존한다."""
    attempts = [attempt("A"), attempt("A", case_index=1)]
    record = attempts[0]["record"]
    retrieve = next(stage for stage in record["stages"] if stage["name"] == "retrieve")
    if changed == "blank_configuration":
        attempts[0]["configuration"] = ""
    elif changed == "blank_retrieval":
        record["stages"].remove(retrieve)
    archive = export(tmp_path, attempts)
    if changed == "configuration":
        attempts[0]["configuration"] = "B"
    elif changed == "blank_configuration":
        attempts[0]["configuration"] = "configured"
    elif changed == "blank_retrieval":
        record["stages"].append(retrieve)
    elif changed == "variant":
        record["options"]["variant"] = "C"
    elif changed == "run_kind":
        record["run_kind"] = record["options"]["run_kind"] = "demo"
    elif changed == "options_run_kind":
        record["options"]["run_kind"] = "demo"
    elif changed == "retrieve_status":
        retrieve["status"] = "error"
    else:
        record["stages"].append(dict(retrieve))
    archive.write_text(json.dumps(attempts, ensure_ascii=False), encoding="utf-8")
    scorer = AsyncMock(return_value=SimpleNamespace(value=0.5))
    ok, (bad, good) = score(archive, tmp_path / "scored", scorer)
    assert not ok
    assert (bad["status"], bad["reason"], bad["score"]) == ("input_error", reason, "")
    assert (bad["comparison_eligible"], bad["comparison_exclusion_reason"]) == (
        "false",
        reason,
    )
    assert (good["status"], good["score"], good["comparison_eligible"]) == (
        "scored",
        "0.5",
        "true",
    )
    eligible = [
        row["variant"] for row in (bad, good) if row["comparison_eligible"] == "true"
    ]
    assert {variant: eligible.count(variant) for variant in ("A", "B", "C")} == {
        "A": 1,
        "B": 0,
        "C": 0,
    }
    scorer.assert_awaited_once()
    assert (
        scorer.await_args.kwargs["user_input"]
        == attempts[1]["record"]["request"]["question"]
    )


@pytest.mark.parametrize(
    ("variant", "kind", "retrieval", "reason"),
    [
        ("B", "fixed_evidence", "skipped", "fixed_evidence"),
        ("C", "fixed_evidence", "ok", "fixed_evidence"),
        ("A", "demo", "ok", "demo"),
        ("A", "rag", "skipped", "retrieval_skipped"),
        ("B", "rag", "error", "retrieval_error"),
        ("C", "rag", None, "missing_retrieval_stage"),
    ],
)
def test_diagnostic_run_keeps_its_score_outside_comparison(
    tmp_path, variant, kind, retrieval, reason
):
    """고정 근거·데모·검색 미완료 기록은 점수가 있어도 실검색 비교에서 제외한다."""
    item = attempt(variant)
    record = item["record"]
    record["run_kind"] = record["options"]["run_kind"] = kind
    stage = next(s for s in record["stages"] if s["name"] == "retrieve")
    if retrieval is None:
        record["stages"].remove(stage)
    else:
        stage["status"] = retrieval
    archive = export(tmp_path, [item])
    scorer = AsyncMock(return_value=SimpleNamespace(value=0.5))
    ok, (row,) = score(archive, tmp_path / "scored", scorer)
    assert ok and (row["status"], row["score"], row["variant"]) == (
        "scored",
        "0.5",
        variant,
    )
    assert (row["comparison_eligible"], row["comparison_exclusion_reason"]) == (
        "false",
        reason,
    )


def test_legacy_team_a_snapshot_is_diagnostic_only(tmp_path):
    """설정명 열이 없는 과거 팀 A 원본은 임의의 설정명을 부여하지 않고 채점한다."""
    runs = read_csv(ARCHIVE.with_name("runs.csv"))
    assert all("configuration" not in run for run in runs)
    scorer = AsyncMock(return_value=SimpleNamespace(value=0.25))
    ok, rows = score(ARCHIVE, tmp_path / "scored", scorer, cases=CASES)
    assert ok and len(rows) == 2 and scorer.await_count == 2
    for row in rows:
        assert (row["status"], row["score"]) == ("scored", "0.25")
        assert (row["configuration"], row["variant"]) == ("", "A")
        assert (row["comparison_eligible"], row["comparison_exclusion_reason"]) == (
            "false",
            "missing_run_configuration",
        )


def test_missing_archived_variant_is_not_inferred_from_exporter_default(tmp_path):
    """원본 옵션에서 생략한 variant의 기본값 A는 비교 근거로 사용할 수 없다."""
    item = attempt("A")
    del item["record"]["options"]["variant"]
    archive = export(tmp_path, [item])
    assert read_csv(archive.with_name("runs.csv"))[0]["variant"] == "A"
    scorer = AsyncMock(return_value=SimpleNamespace(value=0.5))
    ok, (row,) = score(archive, tmp_path / "scored", scorer)
    assert ok and (row["status"], row["score"], row["variant"]) == ("scored", "0.5", "")
    assert (row["comparison_eligible"], row["comparison_exclusion_reason"]) == (
        "false",
        "missing_recorded_variant",
    )


def test_unscored_and_error_rows_do_not_enter_comparison(tmp_path):
    """검증 전용 CLI, 점수 미반환, 채점기 예외 모두 비교용 숫자를 남기지 않는다."""
    archive = export(tmp_path, [attempt("A"), attempt("B", case_index=1)])
    output = tmp_path / "checked"
    main(
        [
            "--evaluation",
            str(archive),
            "--cases-csv",
            str(tmp_path / "cases.csv"),
            "--output-dir",
            str(output),
        ]
    )
    checked = read_csv(output / "scores.csv")
    assert [(r["status"], r["reason"]) for r in checked] == [
        ("skipped", "validate_only")
    ] * 2
    scorer = AsyncMock(
        side_effect=[SimpleNamespace(value=float("nan")), RuntimeError("채점 실패")]
    )
    ok, failed = score(archive, tmp_path / "scored", scorer)
    assert not ok
    assert [(r["status"], r["reason"]) for r in failed] == [
        ("no_score", "non_finite_value"),
        ("scorer_error", "judge_failed"),
    ]
    for row in checked + failed:
        assert row["score"] == ""
        assert (row["comparison_eligible"], row["comparison_exclusion_reason"]) == (
            "false",
            row["reason"],
        )


def test_answered_json_cannot_override_error_in_run_table(tmp_path):
    """원본 표의 실패 실행이 JSON에서 답변 완료로 바뀌어도 채점하지 않는다."""
    item = attempt("A")
    item["status"] = item["response"]["status"] = item["record"]["response"][
        "status"
    ] = "error"
    archive = export(tmp_path, [item])
    assert read_csv(archive.with_name("runs.csv"))[0]["status"] == "error"
    item["status"] = item["response"]["status"] = item["record"]["response"][
        "status"
    ] = "answered"
    archive.write_text(json.dumps([item], ensure_ascii=False), encoding="utf-8")
    scorer = AsyncMock()
    ok, (row,) = score(archive, tmp_path / "scored", scorer)
    assert not ok
    scorer.assert_not_awaited()
    assert (row["status"], row["reason"], row["score"]) == (
        "input_error",
        "run_status_mismatch",
        "",
    )
    assert (row["comparison_eligible"], row["comparison_exclusion_reason"]) == (
        "false",
        "run_status_mismatch",
    )


def test_missing_record_preserves_only_reported_configuration(tmp_path):
    """실행이 저장되지 않은 시도는 검증된 설정명 열을 비우고 보고된 설정명을 보존한다."""
    item = attempt("C", configuration="실험-미저장")
    item.update(
        record=None, response=None, run_id=None, status="error", error="실행 기록 없음"
    )
    archive = export(tmp_path, [item])
    scorer = AsyncMock()
    ok, (row,) = score(archive, tmp_path / "scored", scorer)
    assert not ok
    scorer.assert_not_awaited()
    assert (row["reported_configuration"], row["configuration"]) == ("실험-미저장", "")
    assert (row["status"], row["reason"], row["score"]) == (
        "skipped",
        "no_run_record",
        "",
    )
    assert (row["comparison_eligible"], row["comparison_exclusion_reason"]) == (
        "false",
        "no_run_record",
    )
