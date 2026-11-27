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
            "run_kind",
            "top_k",
            "candidate_count",
        ],
        [["r1", "d", "c1", "A", "False", "answered", status, "rag", top_k, count]],
    )
    write(
        "candidates.csv",
        ["run_id", "dataset_id", "case_id", "rank", "chunk_id"],
        [["r1", "d", "c1", r, f"x{r}"] for r in ranks],
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


def test_run_scores_rejects_candidates_owned_by_another_case(tmp_path) -> None:
    import pytest

    from src.evaluation.comparison import run_scores

    archive = _archive(tmp_path)
    text = (archive / "candidates.csv").read_text(encoding="utf-8")
    (archive / "candidates.csv").write_text(
        text.replace(",d,c1,2,", ",d,other,2,"), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="다릅니다"):
        run_scores(archive)


def test_run_scores_label_uses_the_recorded_variant(tmp_path) -> None:
    from src.evaluation.comparison import run_scores

    archive = _archive(tmp_path)
    text = (archive / "runs.csv").read_text(encoding="utf-8")
    text = text.replace("configuration,", "variant,configuration,").replace(
        ",A,False,", ",C,configured,False,"
    )
    (archive / "runs.csv").write_text(text, encoding="utf-8")
    (row,) = run_scores(archive)
    assert row["configuration"] == "C"


def test_run_scores_rejects_duplicate_run_ids_and_non_rag_runs(tmp_path) -> None:
    import pytest

    from src.evaluation.comparison import run_scores

    archive = _archive(tmp_path)
    runs = (archive / "runs.csv").read_text(encoding="utf-8").splitlines()
    duplicated = [*runs, runs[1]]
    (archive / "runs.csv").write_text(
        chr(10).join(duplicated) + chr(10), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="run_id"):
        run_scores(archive)
    archive = _archive(tmp_path)
    text = (archive / "runs.csv").read_text(encoding="utf-8").replace(",rag,", ",demo,")
    (archive / "runs.csv").write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="run_kind"):
        run_scores(archive)


def test_run_scores_rejects_duplicate_case_keys_and_blank_chunk_ids(tmp_path) -> None:
    import pytest

    from src.evaluation.comparison import run_scores

    archive = _archive(tmp_path)
    lines = (archive / "cases.csv").read_text(encoding="utf-8").splitlines()
    (archive / "cases.csv").write_text(
        chr(10).join([*lines, lines[1]]) + chr(10), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="cases.csv"):
        run_scores(archive)
    archive = _archive(tmp_path)
    text = (archive / "candidates.csv").read_text(encoding="utf-8").replace("x2", "")
    (archive / "candidates.csv").write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="chunk_id"):
        run_scores(archive)


def test_several_recordless_failures_with_blank_run_ids_are_allowed(tmp_path) -> None:
    from src.evaluation.comparison import run_scores

    archive = _archive(tmp_path)
    lines = (archive / "runs.csv").read_text(encoding="utf-8").splitlines()
    blank = ["", "d", "c1", "A", "False", "error", "", "", "", ""]
    text = chr(10).join([*lines, ",".join(blank), ",".join(blank)]) + chr(10)
    (archive / "runs.csv").write_text(text, encoding="utf-8")
    rows = run_scores(archive)
    assert len(rows) == 3 and rows[1]["precision"] is None


def test_blank_run_kind_is_only_for_the_recordless_failure_shape(tmp_path) -> None:
    import pytest

    from src.evaluation.comparison import run_scores

    archive = _archive(tmp_path)
    text = (archive / "runs.csv").read_text(encoding="utf-8").replace(",rag,", ",,")
    (archive / "runs.csv").write_text(
        text, encoding="utf-8"
    )  # run_id·검색 상태가 있는데 유형만 빔
    with pytest.raises(ValueError, match="run_kind"):
        run_scores(archive)
