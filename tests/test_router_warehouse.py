from datetime import date
from decimal import Decimal

from src.router import HybridTriageRouter
from src.schemas import ExtractedDocument, ExtractionRoute, LineItem, TriageDecision
from src.warehouse import AuditWarehouse


def _mock_local_extractor(doc_id: str, raw: dict) -> ExtractedDocument:
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
        total_amount=Decimal(str(raw["total_amount"])),
        overall_confidence=raw["overall_confidence"],
        route_used=ExtractionRoute.LOCAL_OCR,
    )


def test_end_to_end_routing_and_duckdb_audit(tmp_path):
    wh = AuditWarehouse(db_path=tmp_path / "test_audit.duckdb")
    router = HybridTriageRouter(warehouse=wh, local_extractor=_mock_local_extractor)

    base_payload = {
        "vendor_name": "Hartford Fleet Parts",
        "vendor_tax_id": "06-9876543",
        "invoice_number": "INV-101",
        "invoice_date": "2026-11-25",
        "line_items": [
            {
                "description": "Alternator Assembly",
                "quantity": 1,
                "unit_price": "240.00",
                "line_total": "240.00",
                "confidence": 0.97,
            }
        ],
        "subtotal": "240.00",
        "tax_amount": "15.24",
        "total_amount": "255.24",
        "overall_confidence": 0.96,
    }

    # 1. Clean high-confidence document -> stays on LOCAL_OCR, AUTO_APPROVE
    out1 = router.process_document("DOC-101", base_payload)
    assert out1.audit.decision == TriageDecision.AUTO_APPROVE
    assert out1.document.route_used == ExtractionRoute.LOCAL_OCR
    assert out1.estimated_cost_usd == HybridTriageRouter.LOCAL_OCR_COST_USD

    # 2. Low-confidence distinct invoice -> escalates to VLM_FALLBACK, then AUTO_APPROVE
    low_conf_payload = dict(base_payload, invoice_date="2026-11-26", overall_confidence=0.71)
    out2 = router.process_document("DOC-102", low_conf_payload)
    assert out2.document.route_used == ExtractionRoute.VLM_FALLBACK
    assert out2.audit.decision == TriageDecision.AUTO_APPROVE
    assert out2.estimated_cost_usd > HybridTriageRouter.LOCAL_OCR_COST_USD

    # 3. Duplicate of DOC-101 -> caught by fingerprint check -> HUMAN_REVIEW
    out3 = router.process_document("DOC-103", base_payload)
    assert out3.audit.decision == TriageDecision.HUMAN_REVIEW
    assert any("DUPLICATE_FINGERPRINT" in f for f in out3.audit.flags)

    metrics = wh.summary_metrics()
    assert metrics["total_docs"] == 3
    assert metrics["auto_approved"] == 2
    assert metrics["human_review"] == 1
    assert metrics["vlm_escalated"] == 1
    wh.close()
