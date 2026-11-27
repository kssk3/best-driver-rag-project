import json

from scripts.score_quality import (
    check_inputs,
    cited_texts_by_run,
    fill_failed_rows,
    load_grading,
    run_config,
)
from src.evaluation.answer_quality import (
    SAFE_REFUSAL,
    parse_verdict,
    score_run,
    summarize,
)

ANSWERABLE = {"required_facts": ["10ℓ는 250원이다."], "reference_answer": "250원"}
NO_EVIDENCE = {"absence_reason": "문서에 없다."}


def run(status, answer="답", variant="A"):
    return {
        "run_id": "r1",
        "case_id": "c1",
        "variant": variant,
        "rewrite_enabled": "False",
        "status": status,
        "answer": answer,
    }


def verdict(value, reason="ok"):
    return lambda prompt: json.dumps({"verdict": value, "reason": reason})


def never_called(prompt):
    raise AssertionError("판정 모델을 부르면 안 된다")


def test_answerable_scores_correctness_and_citation_with_the_judge() -> None:
    row = score_run(run("answered"), ANSWERABLE, "질문", ["근거 본문"], verdict(1))
    assert (row["answer_correct"], row["citation_valid"], row["absence_ok"]) == (
        1,
        1,
        None,
    )


def test_refusing_an_answerable_question_is_zero_without_calling_the_judge() -> None:
    row = score_run(run("insufficient_evidence"), ANSWERABLE, "질문", [], never_called)
    assert (row["answer_correct"], row["citation_valid"]) == (0, 0)


def test_answer_without_a_retrieved_citation_has_invalid_citation() -> None:
    row = score_run(run("answered"), ANSWERABLE, "질문", [], verdict(1))
    assert row["answer_correct"] == 1
    assert row["citation_valid"] == 0
    assert "없음" in row["citation_valid_reason"]


def test_standard_refusal_message_counts_without_the_judge() -> None:
    row = score_run(
        run("insufficient_evidence", SAFE_REFUSAL),
        NO_EVIDENCE,
        "질문",
        [],
        never_called,
    )
    assert row["absence_ok"] == 1


def test_a_refusal_status_with_other_text_is_still_judged() -> None:
    hallucinated = run("insufficient_evidence", "수거 전화번호는 02-123-4567입니다.")
    assert (
        score_run(hallucinated, NO_EVIDENCE, "질문", [], verdict(0))["absence_ok"] == 0
    )


def test_no_evidence_answer_text_is_judged_and_an_error_is_never_a_correct_refusal() -> (
    None
):
    judged = score_run(
        run("answered", "알 수 없습니다"), NO_EVIDENCE, "질문", [], verdict(1)
    )
    assert judged["absence_ok"] == 1
    failed = score_run(run("error"), NO_EVIDENCE, "질문", [], never_called)
    assert failed["absence_ok"] == 0


def test_unreadable_judge_response_is_no_score_not_zero_and_is_counted_separately() -> (
    None
):
    bad = score_run(run("answered"), ANSWERABLE, "질문", ["근거"], lambda p: "not json")
    assert bad["answer_correct"] is None
    assert bad["answer_correct_reason"].startswith("judge_")
    (summary,) = summarize([bad])
    assert summary["answer_correct"] == "0/0"
    assert summary["answer_correct_no_score"] == 1


def test_a_judge_that_raises_value_error_is_a_call_failure_and_is_counted() -> None:
    def broken(prompt):
        raise ValueError("malformed provider response")

    row = score_run(run("answered"), ANSWERABLE, "질문", ["근거"], broken)
    assert row["answer_correct"] is None
    assert row["answer_correct_reason"] == "judge_call_failed:ValueError"
    (summary,) = summarize([row])
    assert summary["answer_correct_no_score"] == 1


def test_a_judge_that_raises_is_no_score() -> None:
    def broken(prompt):
        raise TimeoutError

    row = score_run(run("answered"), ANSWERABLE, "질문", ["근거"], broken)
    assert row["answer_correct"] is None
    assert row["answer_correct_reason"] == "judge_call_failed:TimeoutError"


def test_cited_texts_carry_district_and_location_as_a_header() -> None:
    rows = [
        {
            "run_id": "r1",
            "citation_position": "1",
            "district": "송파구",  # 질문의 지역. 인용 청크의 자치구가 아니다.
            "document_id": "seodaemun-ordinance:attachment:1",
            "title": "조례 별표",
            "source_location": "table-1/row[2]",
            "text": "본문",
        },
        {
            "run_id": "r1",
            "citation_position": "",
            "district": "송파구",
            "document_id": "songpa-rules",
            "title": "x",
            "source_location": "y",
            "text": "인용 안 됨",
        },
    ]
    assert cited_texts_by_run(rows) == {
        "r1": ["[서대문구 | 조례 별표 | table-1/row[2]]\n본문"]
    }


def test_parse_verdict_rejects_non_binary_values() -> None:
    assert parse_verdict('{"verdict": 1, "reason": "좋음"}') == (1, "좋음")
    for raw in ('{"verdict": 2}', '{"verdict": true}', "[]", "{}"):
        try:
            parse_verdict(raw)
        except ValueError:
            continue
        raise AssertionError(raw)


def test_summarize_reports_sum_over_scored_per_variant() -> None:
    rows = [
        score_run(run("answered", variant="A"), ANSWERABLE, "q", ["e"], verdict(1)),
        score_run(run("answered", variant="A"), ANSWERABLE, "q", ["e"], verdict(0)),
        score_run(run("answered", variant="C"), ANSWERABLE, "q", ["e"], verdict(1)),
    ]
    a, c = summarize(rows)
    assert (a["variant"], a["answer_correct"]) == ("A", "1/2")
    assert (c["variant"], c["answer_correct"]) == ("C", "1/1")


def test_summarize_keeps_rewrite_on_and_off_separate() -> None:
    def row(rewrite, value):
        item = run("answered", variant="C")
        item["rewrite_enabled"] = rewrite
        return score_run(item, ANSWERABLE, "q", ["e"], verdict(value))

    off, on = summarize([row("False", 1), row("False", 1), row("True", 0)])
    assert (off["rewrite_enabled"], off["answer_correct"]) == ("False", "2/2")
    assert (on["rewrite_enabled"], on["answer_correct"]) == ("True", "0/1")


def inputs():
    base = {
        "dataset_id": "d",
        "variant": "A",
        "rewrite_enabled": "False",
        "citation_ranks_json": "[]",
    }
    runs = [
        {**base, "run_id": "r1", "case_id": "c1", "candidate_count": "1"},
        {**base, "run_id": "r2", "case_id": "c2", "candidate_count": "0"},  # 후보 0개
    ]
    candidates = [
        {"run_id": "r1", "dataset_id": "d", "rank": "1", "citation_position": ""}
    ]
    return runs, candidates, {"c1": "q1", "c2": "q2"}, {"c1": {}, "c2": {}}


def test_check_inputs_accepts_a_matching_bundle() -> None:
    assert check_inputs(*inputs()) == []


def test_check_inputs_stops_on_a_case_missing_from_the_grading() -> None:
    runs, candidates, questions, grading = inputs()
    del grading["c2"]
    assert any(
        "c2" in p and "채점 자료" in p
        for p in check_inputs(runs, candidates, questions, grading)
    )


def test_check_inputs_stops_on_mismatched_bundles_and_duplicates() -> None:
    runs, candidates, questions, grading = inputs()
    candidates[0]["dataset_id"] = "other"
    candidates.append({"run_id": "zzz", "dataset_id": "other"})
    runs.append(dict(runs[0], run_id="r3"))
    problems = " ".join(check_inputs(runs, candidates, questions, grading))
    assert "dataset_id" in problems and "중복" in problems and "없는 실행" in problems


def test_check_inputs_requires_every_graded_case_unless_subset_is_allowed() -> None:
    runs, candidates, questions, grading = inputs()
    grading["c3"], questions["c3"] = {}, "q3"
    assert any(
        "--allow-subset" in p
        for p in check_inputs(runs, candidates, questions, grading)
    )
    assert check_inputs(runs, candidates, questions, grading, allow_subset=True) == []


def test_check_inputs_tells_a_missing_candidate_file_from_zero_candidates() -> None:
    runs, candidates, questions, grading = inputs()
    assert (
        check_inputs(runs, candidates, questions, grading) == []
    )  # r2의 후보 0개는 정상
    problems = check_inputs(runs, [], questions, grading)  # r1의 후보 행이 통째로 빠짐
    assert any("불완전" in p for p in problems)


def test_check_inputs_stops_when_a_cited_row_is_missing() -> None:
    runs, candidates, questions, grading = inputs()
    runs[0]["citation_ranks_json"] = "[1]"
    assert any(
        "인용 순위" in p for p in check_inputs(runs, candidates, questions, grading)
    )
    candidates[0]["citation_position"] = "1"
    assert check_inputs(runs, candidates, questions, grading) == []


def test_check_inputs_compares_an_explicit_empty_citation_list_but_not_a_missing_one() -> (
    None
):
    runs, candidates, questions, grading = inputs()
    candidates[0]["citation_position"] = "1"  # 후보 파일에만 인용 표시가 붙음
    problems = check_inputs(runs, candidates, questions, grading)
    assert any("인용 순위" in p for p in problems)  # 실행 기록은 명시적 []
    del runs[0]["citation_ranks_json"]  # 값이 없는 예전 기록은 건너뛴다
    assert check_inputs(runs, candidates, questions, grading) == []


def test_recordless_failures_are_told_apart_by_configuration() -> None:
    runs, candidates, questions, grading = inputs()
    failures = [
        {
            "run_id": f"f{c}",
            "dataset_id": "d",
            "case_id": "c1",
            "variant": "",  # 실행 기록 없이 실패하면 variant가 비어 있다
            "configuration": c,
            "rewrite_enabled": "",
            "status": "error",
            "candidate_count": "0",
        }
        for c in ("A", "B", "C")
    ]
    problems = check_inputs(failures, [], questions, {"c1": {}}, allow_subset=True)
    assert not any("중복" in p for p in problems)
    assert run_config(failures[0]) == "A"
    assert run_config({"variant": "B", "configuration": "x"}) == "B"


def test_a_recordless_failure_joins_its_configuration_in_a_mixed_bundle() -> None:
    runs, candidates, questions, grading = inputs()
    failure = {
        "run_id": "f2",
        "dataset_id": "d",
        "case_id": "c2",
        "variant": "",
        "configuration": "rewrite-off",
        "rewrite_enabled": "",
        "status": "error",
        "candidate_count": "0",
    }
    runs = [runs[0], failure]
    runs[0]["configuration"] = "rewrite-off"
    runs = fill_failed_rows(runs)
    assert (runs[1]["variant"], runs[1]["rewrite_enabled"]) == ("A", "False")
    assert check_inputs(runs, candidates, questions, grading) == []


def test_check_inputs_accepts_a_run_that_cites_the_same_candidate_twice() -> None:
    runs, candidates, questions, grading = inputs()
    runs[0]["citation_ranks_json"] = "[1, 1]"
    candidates[0]["citation_position"] = "1"
    assert check_inputs(runs, candidates, questions, grading) == []


def test_load_grading_rejects_a_case_id_that_appears_in_two_files(tmp_path) -> None:
    first, second = tmp_path / "a.json", tmp_path / "b.json"
    first.write_text('{"grading": {"c1": {}}}', encoding="utf-8")
    second.write_text('{"c1": {}}', encoding="utf-8")
    assert set(load_grading([first])) == {"c1"}
    try:
        load_grading([first, second])
    except SystemExit:
        return
    raise AssertionError("겹치는 문항 ID를 막아야 한다")


def test_load_grading_rejects_a_repeated_key_inside_one_file(tmp_path) -> None:
    path = tmp_path / "a.json"
    path.write_text('{"grading": {"c1": {"a": 1}, "c1": {"a": 2}}}', encoding="utf-8")
    try:
        load_grading([path])
    except ValueError:
        return
    raise AssertionError("한 파일 안의 중복 키를 막아야 한다")
