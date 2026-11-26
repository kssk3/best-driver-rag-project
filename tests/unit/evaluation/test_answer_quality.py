import json

from scripts.score_quality import cited_texts_by_run
from src.evaluation.answer_quality import (
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


def test_no_evidence_refusal_state_counts_without_the_judge() -> None:
    row = score_run(run("insufficient_evidence"), NO_EVIDENCE, "질문", [], never_called)
    assert row["absence_ok"] == 1


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
            "district": "서대문구",
            "title": "조례 별표",
            "source_location": "table-1/row[2]",
            "text": "본문",
        },
        {
            "run_id": "r1",
            "citation_position": "",
            "district": "송파구",
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
