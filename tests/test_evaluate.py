from src.evaluate import run_benchmark


def test_benchmark_regression_thresholds(tmp_path):
    report = run_benchmark(
        db_path=tmp_path / "bench_audit.duckdb",
        report_dir=tmp_path / "reports",
    )
    assert report["benchmark_size"] == 25
    assert report["compliance_triage_accuracy"] == 1.0
    assert report["field_level_f1"] == 1.0
    assert report["operational_metrics"]["stp_rate"] == 0.72
    assert report["operational_metrics"]["vlm_escalation_rate"] == 0.24
