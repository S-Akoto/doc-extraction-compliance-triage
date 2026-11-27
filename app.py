from __future__ import annotations

import html
import json
from datetime import date
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs

from src.cord_loader import load_cord_v2_samples
from src.evaluate import run_benchmark
from src.router import HybridTriageRouter
from src.schemas import ExtractedDocument, ExtractionRoute, LineItem
from src.warehouse import AuditWarehouse

DB_PATH = "data/triage_audit.duckdb"


def _cord_local_extractor(doc_id: str, raw: dict) -> ExtractedDocument:
    return ExtractedDocument(
        document_id=doc_id,
        vendor_name=raw["vendor_name"],
        vendor_tax_id=raw.get("vendor_tax_id"),
        invoice_number=raw.get("invoice_number"),
        invoice_date=date.fromisoformat(raw["invoice_date"]),
        line_items=[
            LineItem(
                description=li["description"],
                quantity=Decimal(str(li["quantity"])),
                unit_price=Decimal(str(li["unit_price"])),
                line_total=Decimal(str(li["line_total"])),
                confidence=li["confidence"],
            )
            for li in raw["line_items"]
        ],
        subtotal=Decimal(str(raw["subtotal"])),
        tax_amount=Decimal(str(raw["tax_amount"])),
        tip_or_fee=Decimal(str(raw.get("tip_or_fee", "0.00"))),
        total_amount=Decimal(str(raw["total_amount"])),
        overall_confidence=raw["overall_confidence"],
        route_used=ExtractionRoute.LOCAL_OCR,
    )


def ingest_cord_batch(limit: int = 5) -> int:
    samples = load_cord_v2_samples(limit=limit)
    wh = AuditWarehouse(db_path=DB_PATH)
    router = HybridTriageRouter(warehouse=wh, local_extractor=_cord_local_extractor)
    for sample in samples:
        router.process_document(sample["document_id"], sample)
    wh.close()
    return len(samples)


def resolve_human_review(doc_id: str, resolution: str) -> None:
    wh = AuditWarehouse(db_path=DB_PATH)
    new_decision = "AUTO_APPROVE" if resolution == "APPROVE" else "REJECTED"
    wh.conn.execute(
        "UPDATE compliance_audit_log SET decision = ? WHERE document_id = ?",
        [new_decision, doc_id],
    )
    wh.close()


def render_dashboard() -> str:
    wh = AuditWarehouse(db_path=DB_PATH)
    metrics = wh.summary_metrics()
    rows = wh.conn.execute(
        """
        SELECT
            d.document_id, d.vendor_name, d.invoice_number, d.invoice_date,
            d.total_amount, d.overall_confidence, d.route_used,
            a.decision, a.flags_json, d.estimated_cost_usd
        FROM extracted_documents d
        JOIN compliance_audit_log a USING (document_id)
        ORDER BY
            CASE a.decision WHEN 'HUMAN_REVIEW' THEN 0 WHEN 'ESCALATE_VLM' THEN 1 ELSE 2 END,
            d.document_id
        """
    ).fetchall()
    wh.close()

    table_rows = []
    for r in rows:
        doc_id, vendor, inv_no, inv_dt, total, conf, route, decision, flags_json, cost = r
        flags = json.loads(flags_json)
        flag_str = ", ".join(flags) if flags else "NONE"
        badge_cls = (
            "badge-warn" if decision == "HUMAN_REVIEW"
            else "badge-ok" if decision == "AUTO_APPROVE"
            else "badge-err"
        )
        if decision == "HUMAN_REVIEW":
            action_html = (
                f'<form method="POST" action="/resolve" style="display:inline;">'
                f'<input type="hidden" name="document_id" value="{html.escape(doc_id)}"/>'
                f'<button name="resolution" value="APPROVE" class="btn-sm btn-approve">Approve</button> '
                f'<button name="resolution" value="REJECT" class="btn-sm btn-reject">Reject</button>'
                f'</form>'
            )
        else:
            action_html = "<span style='color:#64748b;'>Cleared</span>"

        table_rows.append(
            f"<tr>"
            f"<td><strong>{html.escape(doc_id)}</strong></td>"
            f"<td>{html.escape(vendor)}</td>"
            f"<td>{html.escape(str(inv_no or '-'))}</td>"
            f"<td>{inv_dt}</td>"
            f"<td>${total:,.2f}</td>"
            f"<td>{conf:.0%}</td>"
            f"<td><code>{html.escape(route)}</code></td>"
            f"<td><span class='badge {badge_cls}'>{html.escape(decision)}</span></td>"
            f"<td style='font-size:12px;'>{html.escape(flag_str)}</td>"
            f"<td>{action_html}</td>"
            f"</tr>"
        )

    rows_html = "\n".join(table_rows) if table_rows else "<tr><td colspan='10'>No records yet.</td></tr>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>Compliance Triage Queue | SR 26-2 Document Extraction</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 24px; background: #f8fafc; color: #0f172a; }}
    h1 {{ margin-bottom: 4px; font-size: 22px; }}
    .sub {{ color: #475569; margin-bottom: 20px; font-size: 14px; }}
    .kpis {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; margin-bottom: 20px; }}
    .card {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 14px; }}
    .card .lbl {{ font-size: 12px; color: #64748b; text-transform: uppercase; }}
    .card .val {{ font-size: 22px; font-weight: 700; margin-top: 4px; }}
    .toolbar {{ margin-bottom: 16px; display: flex; gap: 10px; }}
    button {{ cursor: pointer; border: none; border-radius: 6px; padding: 8px 14px; font-weight: 600; }}
    .btn-primary {{ background: #0f172a; color: #fff; }}
    .btn-secondary {{ background: #e2e8f0; color: #0f172a; }}
    .btn-sm {{ padding: 4px 8px; font-size: 12px; }}
    .btn-approve {{ background: #16a34a; color: #fff; }}
    .btn-reject {{ background: #dc2626; color: #fff; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #e2e8f0; font-size: 13px; }}
    th, td {{ padding: 10px; border-bottom: 1px solid #e2e8f0; text-align: left; }}
    th {{ background: #f1f5f9; font-weight: 600; }}
    .badge {{ padding: 3px 8px; border-radius: 999px; font-size: 11px; font-weight: 700; }}
    .badge-ok {{ background: #dcfce7; color: #166534; }}
    .badge-warn {{ background: #fef3c7; color: #92400e; }}
    .badge-err {{ background: #fee2e2; color: #991b1b; }}
  </style>
</head>
<body>
  <h1>Document Extraction & Compliance Triage Queue</h1>
  <div class="sub">Pydantic v2 Accounting Guardrails | Hybrid OCR &rarr; Gemini VLM Router | DuckDB Audit Warehouse</div>
  <div class="kpis">
    <div class="card"><div class="lbl">Total Documents</div><div class="val">{metrics['total_docs']}</div></div>
    <div class="card"><div class="lbl">Straight-Through (STP)</div><div class="val">{metrics['stp_rate']:.1%}</div></div>
    <div class="card"><div class="lbl">Human Review Queue</div><div class="val">{metrics['human_review']}</div></div>
    <div class="card"><div class="lbl">VLM Escalation Rate</div><div class="val">{metrics['vlm_escalation_rate']:.1%}</div></div>
    <div class="card"><div class="lbl">Total Batch Cost</div><div class="val">${metrics['total_cost_usd']:.4f}</div></div>
  </div>
  <div class="toolbar">
    <form method="POST" action="/run-benchmark"><button class="btn-primary">Run 25-Doc SR 26-2 Benchmark</button></form>
    <form method="POST" action="/ingest-cord"><button class="btn-secondary">Ingest CORD-v2 Receipt Sample</button></form>
  </div>
  <table>
    <thead>
      <tr>
        <th>Doc ID</th><th>Vendor</th><th>Invoice #</th><th>Date</th><th>Total</th>
        <th>Conf.</th><th>Route</th><th>Triage Status</th><th>Audit Flags</th><th>Action</th>
      </tr>
    </thead>
    <tbody>
      {rows_html}
    </tbody>
  </table>
</body>
</html>"""


class TriageHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        html_body = render_dashboard().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html_body)))
        self.end_headers()
        self.wfile.write(html_body)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        params = parse_qs(body)

        if self.path == "/run-benchmark":
            run_benchmark(db_path=DB_PATH)
        elif self.path == "/ingest-cord":
            ingest_cord_batch(limit=5)
        elif self.path == "/resolve":
            doc_id = params.get("document_id", [""])[0]
            res = params.get("resolution", ["APPROVE"])[0]
            if doc_id:
                resolve_human_review(doc_id, res)

        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()

    def log_message(self, format: str, *args) -> None:
        return


if __name__ == "__main__":
    if not AuditWarehouse(DB_PATH).summary_metrics()["total_docs"]:
        run_benchmark(db_path=DB_PATH)
    server = HTTPServer(("127.0.0.1", 8050), TriageHandler)
    print("Triage Queue UI running at http://127.0.0.1:8050 (Ctrl+C to stop)")
    server.serve_forever()
