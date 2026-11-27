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


def _archive(tmp_path, status="ok", count=2, top_k=5, ranks=(1, 2)):
    import csv

    def write(name, header, rows):
        with (tmp_path / name).open("w", encoding="utf-8", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(header)
            writer.writerows(rows)

    write(
        "cases.csv",
        ["dataset_id", "case_id", "allowed_chunk_ids_json"],
        [["d", "c1", '["a"]']],
    )
    write(
        "runs.csv",
        [
            "run_id",
            "dataset_id",
            "case_id",
            "configuration",
            "rewrite_enabled",
            "status",
            "retrieval_status",
            "top_k",
            "candidate_count",
        ],
        [["r1", "d", "c1", "A", "False", "answered", status, top_k, count]],
    )
    write(
        "candidates.csv",
        ["run_id", "rank", "chunk_id"],
        [["r1", r, f"x{r}"] for r in ranks],
    )
    return tmp_path


def test_failed_retrieval_is_undefined_not_zero(tmp_path) -> None:
    from src.evaluation.comparison import run_scores

    (row,) = run_scores(_archive(tmp_path, status="error", count=0, ranks=()))
    assert (row["precision"], row["recall"]) == (None, None)
    (ok,) = run_scores(_archive(tmp_path, count=0, ranks=()))  # 정상 검색의 후보 0건
    assert (ok["precision"], ok["recall"]) == (None, 0.0)


def test_run_scores_rejects_missing_candidate_rows_and_too_deep_k(tmp_path) -> None:
    import pytest

    from src.evaluation.comparison import run_scores

    with pytest.raises(ValueError, match="후보 행"):
        run_scores(_archive(tmp_path, count=2, ranks=(1,)))
    with pytest.raises(ValueError, match="top_k"):
        run_scores(_archive(tmp_path), k=10)


def test_run_scores_rejects_non_positive_k_and_duplicate_ranks(tmp_path) -> None:
    import pytest

    from src.evaluation.comparison import run_scores

    with pytest.raises(ValueError, match="1 이상"):
        run_scores(_archive(tmp_path), k=0)
    archive = _archive(tmp_path, count=2, ranks=(1, 1, 2))
    with pytest.raises(ValueError, match="두 번"):
        run_scores(archive)
