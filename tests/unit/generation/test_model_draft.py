import json
from unittest.mock import patch

from langchain_core.messages import AIMessage

from src.generation.answer import GenerationInput
from src.generation.model_draft import SYSTEM_PROMPT, make_model_draft


def test_color_question_sends_evidence_and_returns_draft():
    # 모델에 보낼 값. 테스트용으로 색상표를 두 품목으로 줄였다.
    payload: GenerationInput = {
        "original_question": (
            "서대문구 공동주택 일반용기에서 유리병은 회색이고 캔은 주황색이 맞죠?"
        ),
        "conditions": {
            "district": "서대문구",
            "housing_type": "공동주택",
            "container_type": "일반용기",
        },
        "evidence": [
            {
                "chunk_id": "test-colors-0",
                "text": "서대문구 공동주택 일반용기 색상표\n캔: 회색\n유리병: 주황색",
                "source": {
                    "document_id": "seodaemun-rules:attachment:160561037",
                    "source_location": "table-1/row[0]",
                },
            }
        ],
    }

    # 함수가 반환해야 하는 Python 값. [0]은 위 evidence의 첫 번째 항목이다.
    expected = {
        "status": "answered",
        "message": "공동주택 일반용기 기준으로 캔은 회색이고 유리병은 주황색입니다.",
        "citation_indices": [0],
    }

    # 모델 응답만 준비하고, 직접 작성한 make_model_draft와 draft를 실행한다.
    with patch("src.generation.model_draft.ChatOpenAI") as chat_class:
        chat = chat_class.return_value.bind.return_value
        chat.invoke.return_value = AIMessage(
            content=json.dumps(expected, ensure_ascii=False)
        )

        draft = make_model_draft("test-model")
        actual = draft(payload)

    # 나가는 메시지와 돌아온 결과를 각각 확인한다.
    system, user = chat.invoke.call_args.args[0]
    assert system == ("system", SYSTEM_PROMPT)
    assert user[0] == "human"
    assert json.loads(user[1]) == payload
    assert actual == expected
