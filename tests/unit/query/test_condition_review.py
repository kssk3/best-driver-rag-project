"""숫자·용도·시점·예외 조건이 사라진 변환을 검수 후보로 잡는다."""

import pytest

from scripts.review_rewrite_conditions import check_conditions, review_rows
from src.contracts import ResolvedQuery
from src.query.rewrite import expected_prompt_query, make_prompt_rewriter


@pytest.mark.parametrize(
    "question,rewritten,fragment",
    [
        ("50리터 생활폐기물용 봉투 가격?", "50리터 봉투 가격?", "생활폐기물용"),
        ("앞으로 가격이 오를 예정인가요?", "현재 가격은 얼마인가요?", "앞으로"),
        ("실제로 만들어 파나요?", "제작할 수 있나요?", "실제로"),
        ("분리되지 않는 보냉 상자는?", "상자는?", "분리되지 않는"),
        ("송파구 400리터 냉장고는?", "송파구 냉장고는?", "400리터"),
    ],
)
def test_missing_conditions_are_flagged(question, rewritten, fragment):
    result = check_conditions(question, rewritten, [fragment])
    assert result["missing_fragments"] == fragment
    assert result["automatic_status"] == "조건 누락 후보"


def test_appended_alias_preserves_question_but_is_not_human_approval():
    question = "서대문구 안 씻은 우유팩은?"
    result = check_conditions(question, question + " (종이팩)", ["안 씻은"])
    assert result["body_preserved"] == "true"
    assert result["automatic_status"] == "문자열 보존"
    assert "human_status" not in result


def test_multiline_review_matches_the_model_allowed_query():
    question = " 우유팩이랑\n두유팩  안 씻었어요. "
    expected = "우유팩이랑 두유팩 안 씻었어요. (종이팩)"
    assert expected_prompt_query(question) == expected
    rows = review_rows(
        [
            {
                "question": question,
                "required_fragments": ["우유팩", "두유팩", "안 씻었어요"],
            }
        ]
    )
    row = next(row for row in rows if row["route"] == "prompt-rule-expected")
    assert row["rewritten_question"] == expected
    assert row["body_preserved"] == "true"
    assert row["missing_fragments"] == ""
    query = ResolvedQuery(status="resolved", search_query=question, district="서대문구")
    assert make_prompt_rewriter(lambda *_: expected)(query) == row["rewritten_question"]
