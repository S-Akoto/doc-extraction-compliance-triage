from app import render_dashboard, resolve_human_review
from src.cord_loader import load_cord_v2_samples
from src.evaluate import run_benchmark
from src.warehouse import AuditWarehouse


def test_cord_v2_loader_and_dashboard_rendering(tmp_path, monkeypatch):
    samples = load_cord_v2_samples(limit=3)
    assert len(samples) == 3
    assert samples[0]["document_id"] == "CORD-001"

    test_db = tmp_path / "ui_test.duckdb"
    monkeypatch.setattr("app.DB_PATH", str(test_db))

    run_benchmark(db_path=test_db, report_dir=tmp_path / "reports")
    html_before = render_dashboard()
    assert "BENCH-019" in html_before
    assert "TOTAL_MISMATCH" in html_before

    resolve_human_review("BENCH-019", "APPROVE")
    wh = AuditWarehouse(db_path=test_db)
    row = wh.conn.execute(
        "SELECT decision FROM compliance_audit_log WHERE document_id = 'BENCH-019'"
    ).fetchone()
    wh.close()
    assert row[0] == "AUTO_APPROVE"
