"""화면용 말투 변환 테스트. 원문 의미와 평가 기록은 바꾸지 않는다."""

import pytest
from screen_helpers import fixture_app

from src.interface.tone import raccoon_tone


def test_only_first_and_last_sentences_get_the_tone() -> None:
    text = "라벨을 떼세요. 페트병은 비우세요. 수거함에 버리세요."

    assert raccoon_tone(text) == (
        "라벨을 떼세요구리. 페트병은 비우세요. 수거함에 버리세요구리."
    )


def test_a_single_sentence_is_toned_once() -> None:
    assert raccoon_tone("월요일에 내놓으세요.") == "월요일에 내놓으세요구리."
    assert raccoon_tone("대형폐기물은 신고합니다.") == "대형폐기물은 신고합니다구리."


def test_numbers_and_negation_are_untouched() -> None:
    text = "아니요, 반대입니다. 수수료는 3,000원입니다."

    toned = raccoon_tone(text)

    assert "3,000원입니다구리." in toned and "아니요, 반대입니다구리." in toned


@pytest.mark.parametrize(
    "text",
    [
        "어느 구인가요?",  # 물음표
        "<article><h2>안내</h2></article>",  # HTML
        "| 품목 | 안내 |",  # 표
        "- 항목입니다.",  # 목록
        "근거가 없음",  # 표준 끝맺음이 아님
        "",
    ],
)
def test_sentences_that_are_not_plain_prose_are_left_alone(text) -> None:
    assert raccoon_tone(text) == text


def test_line_breaks_between_sentences_are_kept() -> None:
    assert raccoon_tone("첫째입니다.\n둘째입니다.\n셋째입니다.") == (
        "첫째입니다구리.\n둘째입니다.\n셋째입니다구리."
    )


def test_result_screen_shows_toned_answer_and_the_original_on_demand() -> None:
    app = fixture_app("answered", question="가상 질문")

    assert not app.exception
    assert any("구리." in s.value for s in app.success)
    [expander] = [e for e in app.expander if e.label == "원문 보기"]
    assert "구리" not in expander.text[0].value  # 원문 그대로
