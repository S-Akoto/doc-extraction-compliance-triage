from datetime import date
from decimal import Decimal
import pytest
from pydantic import ValidationError

from src.schemas import (
    ExtractedDocument,
    ExtractionRoute,
    LineItem,
    TriageDecision,
    audit_extracted_document,
)


def _sample_doc(**overrides) -> ExtractedDocument:
    base = dict(
        document_id="DOC-001",
        vendor_name="Acme Industrial Supply",
        vendor_tax_id="12-3456789",
        invoice_number="INV-9001",
        invoice_date=date(2026, 11, 20),
        line_items=[
            LineItem(
                description="Brake Rotor Set",
                quantity=Decimal("2"),
                unit_price=Decimal("75.00"),
                line_total=Decimal("150.00"),
                confidence=0.96,
            )
        ],
        subtotal=Decimal("150.00"),
        tax_amount=Decimal("9.53"),
        total_amount=Decimal("159.53"),
        overall_confidence=0.95,
        route_used=ExtractionRoute.LOCAL_OCR,
    )
    base.update(overrides)
    return ExtractedDocument(**base)


def test_auto_approve_clean_document():
    doc = _sample_doc()
    result = audit_extracted_document(doc, seen_fingerprints=set())
    assert result.decision == TriageDecision.AUTO_APPROVE
    assert result.passed_math_checks is True
    assert result.flags == []


def test_escalate_vlm_on_low_confidence_only():
    doc = _sample_doc(overall_confidence=0.72)
    result = audit_extracted_document(doc, seen_fingerprints=set())
    assert result.decision == TriageDecision.ESCALATE_VLM
    assert any("LOW_CONFIDENCE" in f for f in result.flags)


def test_human_review_on_total_mismatch():
    doc = _sample_doc(total_amount=Decimal("165.00"))
    result = audit_extracted_document(doc, seen_fingerprints=set())
    assert result.decision == TriageDecision.HUMAN_REVIEW
    assert result.passed_math_checks is False
    assert any("TOTAL_MISMATCH" in f for f in result.flags)


def test_human_review_on_duplicate_fingerprint():
    doc = _sample_doc()
    result = audit_extracted_document(doc, seen_fingerprints={doc.fingerprint})
    assert result.decision == TriageDecision.HUMAN_REVIEW
    assert any("DUPLICATE_FINGERPRINT" in f for f in result.flags)


def test_line_item_math_validation_error():
    with pytest.raises(ValidationError):
        LineItem(
            description="Oil Filter",
            quantity=Decimal("3"),
            unit_price=Decimal("10.00"),
            line_total=Decimal("35.00"),
            confidence=0.95,
        )
