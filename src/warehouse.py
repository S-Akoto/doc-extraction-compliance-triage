from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any

import duckdb

from src.schemas import ComplianceAuditResult, ExtractedDocument


class AuditWarehouse:
    def __init__(self, db_path: str | Path = "data/triage_audit.duckdb") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = duckdb.connect(str(self.db_path))
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS extracted_documents (
                document_id VARCHAR PRIMARY KEY,
                fingerprint VARCHAR NOT NULL,
                vendor_name VARCHAR NOT NULL,
                vendor_tax_id VARCHAR,
                invoice_number VARCHAR,
                invoice_date DATE NOT NULL,
                currency VARCHAR(3) NOT NULL,
                subtotal DECIMAL(12, 2) NOT NULL,
                tax_amount DECIMAL(12, 2) NOT NULL,
                tip_or_fee DECIMAL(12, 2) NOT NULL,
                total_amount DECIMAL(12, 2) NOT NULL,
                overall_confidence DOUBLE NOT NULL,
                route_used VARCHAR NOT NULL,
                latency_ms DOUBLE NOT NULL,
                estimated_cost_usd DOUBLE NOT NULL,
                ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS line_items (
                document_id VARCHAR NOT NULL,
                line_index INTEGER NOT NULL,
                description VARCHAR NOT NULL,
                quantity DECIMAL(12, 3) NOT NULL,
                unit_price DECIMAL(12, 2) NOT NULL,
                line_total DECIMAL(12, 2) NOT NULL,
                confidence DOUBLE NOT NULL,
                PRIMARY KEY (document_id, line_index)
            );

            CREATE TABLE IF NOT EXISTS compliance_audit_log (
                document_id VARCHAR PRIMARY KEY,
                fingerprint VARCHAR NOT NULL,
                decision VARCHAR NOT NULL,
                route_used VARCHAR NOT NULL,
                passed_math_checks BOOLEAN NOT NULL,
                flags_json VARCHAR NOT NULL,
                audited_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

    def get_seen_fingerprints(self) -> set[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT fingerprint FROM compliance_audit_log WHERE decision = 'AUTO_APPROVE'"
        ).fetchall()
        return {r[0] for r in rows}

    def persist_record(
        self,
        doc: ExtractedDocument,
        audit: ComplianceAuditResult,
        latency_ms: float,
        estimated_cost_usd: float,
    ) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO extracted_documents (
                document_id, fingerprint, vendor_name, vendor_tax_id, invoice_number,
                invoice_date, currency, subtotal, tax_amount, tip_or_fee, total_amount,
                overall_confidence, route_used, latency_ms, estimated_cost_usd
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                doc.document_id,
                doc.fingerprint,
                doc.vendor_name,
                doc.vendor_tax_id,
                doc.invoice_number,
                doc.invoice_date,
                doc.currency,
                doc.subtotal,
                doc.tax_amount,
                doc.tip_or_fee,
                doc.total_amount,
                doc.overall_confidence,
                doc.route_used.value,
                latency_ms,
                estimated_cost_usd,
            ],
        )

        self.conn.execute(
            "DELETE FROM line_items WHERE document_id = ?", [doc.document_id]
        )
        for idx, item in enumerate(doc.line_items, start=1):
            self.conn.execute(
                """
                INSERT INTO line_items (
                    document_id, line_index, description, quantity, unit_price, line_total, confidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    doc.document_id,
                    idx,
                    item.description,
                    item.quantity,
                    item.unit_price,
                    item.line_total,
                    item.confidence,
                ],
            )

        self.conn.execute(
            """
            INSERT OR REPLACE INTO compliance_audit_log (
                document_id, fingerprint, decision, route_used, passed_math_checks, flags_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                audit.document_id,
                audit.fingerprint,
                audit.decision.value,
                audit.route_used.value,
                audit.passed_math_checks,
                json.dumps(audit.flags),
            ],
        )

    def summary_metrics(self) -> Dict[str, Any]:
        row = self.conn.execute(
            """
            SELECT
                COUNT(*) AS total_docs,
                SUM(CASE WHEN a.decision = 'AUTO_APPROVE' THEN 1 ELSE 0 END) AS auto_approved,
                SUM(CASE WHEN a.decision = 'HUMAN_REVIEW' THEN 1 ELSE 0 END) AS human_review,
                SUM(CASE WHEN d.route_used = 'VLM_FALLBACK' THEN 1 ELSE 0 END) AS vlm_escalated,
                ROUND(AVG(d.latency_ms), 2) AS avg_latency_ms,
                ROUND(SUM(d.estimated_cost_usd), 5) AS total_cost_usd
            FROM extracted_documents d
            JOIN compliance_audit_log a USING (document_id)
            """
        ).fetchone()
        total = row[0] or 0
        return {
            "total_docs": total,
            "auto_approved": row[1] or 0,
            "human_review": row[2] or 0,
            "stp_rate": round((row[1] or 0) / total, 4) if total else 0.0,
            "vlm_escalated": row[3] or 0,
            "vlm_escalation_rate": round((row[3] or 0) / total, 4) if total else 0.0,
            "avg_latency_ms": row[4] or 0.0,
            "total_cost_usd": row[5] or 0.0,
        }

    def close(self) -> None:
        self.conn.close()
