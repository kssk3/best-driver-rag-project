"""ID 기준 정밀도·재현율과 구성별 평균을 확인한다."""

from src.evaluation.comparison import by_configuration, id_scores


def test_id_scores_use_distinct_ids():
    assert id_scores(["a", "a", "b"], ["a", "c"]) == (0.5, 0.5)


def test_id_scores_undefined_cases():
    assert id_scores(["a"], []) == (None, None)  # 허용 근거 없음
    assert id_scores([], ["a"]) == (None, 0.0)  # 후보 0개


def test_by_configuration_skips_undefined_but_counts_n():
    rows = [
        {
            "configuration": "A",
            "rewrite_enabled": "false",
            "precision": 1.0,
            "recall": 1.0,
        },
        {
            "configuration": "A",
            "rewrite_enabled": "false",
            "precision": None,
            "recall": 0.0,
        },
        {
            "configuration": "A",
            "rewrite_enabled": "false",
            "precision": None,
            "recall": None,
        },
    ]
    (row,) = by_configuration(rows)
    assert (row["precision"], row["precision_n"]) == (1.0, 1)
    assert (row["recall"], row["recall_n"]) == (0.5, 2)
