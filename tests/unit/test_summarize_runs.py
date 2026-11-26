from scripts.summarize_runs import format_rows, summarize


def row(variant, status, ms, error_code=""):
    return {
        "variant": variant,
        "rewrite_enabled": "False",
        "status": status,
        "duration_ms": ms,
        "error_code": error_code,
    }


def test_summarize_counts_success_errors_and_times_per_variant() -> None:
    rows = [
        row("A", "answered", "1000"),
        row("A", "insufficient_evidence", "3000"),
        row("A", "error", "", "pipeline.generate_failed"),
        row("C", "answered", "5000"),
    ]
    a, c = summarize(rows)
    assert (a["variant"], a["total"], a["succeeded"], a["errors"]) == ("A", 3, 2, 1)
    assert (a["n_timed"], a["mean_ms"], a["median_ms"]) == (2, 2000, 2000)
    assert (c["variant"], c["succeeded"], c["mean_ms"]) == ("C", 1, 5000)


def test_summarize_shows_a_dash_when_no_run_has_a_time() -> None:
    (only,) = summarize([row("B", "error", "", "x")])
    assert only["mean_ms"] is None
    assert "—" in format_rows([only])
