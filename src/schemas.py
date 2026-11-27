from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class TriageDecision(str, Enum):
    AUTO_APPROVE = "AUTO_APPROVE"
    ESCALATE_VLM = "ESCALATE_VLM"
    HUMAN_REVIEW = "HUMAN_REVIEW"


class ExtractionRoute(str, Enum):
    LOCAL_OCR = "LOCAL_OCR"
    VLM_FALLBACK = "VLM_FALLBACK"


class LineItem(BaseModel):
    description: str = Field(..., min_length=1)
    quantity: Decimal = Field(..., gt=0)
    unit_price: Decimal = Field(..., ge=0)
    line_total: Decimal = Field(..., ge=0)
    confidence: float = Field(..., ge=0.0, le=1.0)

    @model_validator(mode="after")
    def verify_line_math(self) -> "LineItem":
        expected = (self.quantity * self.unit_price).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        if abs(expected - self.line_total) > Decimal("0.02"):
            raise ValueError(
                f"Line item math mismatch for '{self.description}': "
                f"{self.quantity} x {self.unit_price} = {expected}, got {self.line_total}"
            )
        return self


class ExtractedDocument(BaseModel):
    document_id: str
    vendor_name: str = Field(..., min_length=1)
    vendor_tax_id: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: date
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    line_items: List[LineItem] = Field(..., min_length=1)
    subtotal: Decimal = Field(..., ge=0)
    tax_amount: Decimal = Field(default=Decimal("0.00"), ge=0)
    tip_or_fee: Decimal = Field(default=Decimal("0.00"), ge=0)
    total_amount: Decimal = Field(..., gt=0)
    overall_confidence: float = Field(..., ge=0.0, le=1.0)
    route_used: ExtractionRoute = ExtractionRoute.LOCAL_OCR

    @field_validator("vendor_name")
    @classmethod
    def normalize_vendor(cls, v: str) -> str:
        return " ".join(v.strip().split())

    @property
    def fingerprint(self) -> str:
        raw = f"{self.vendor_name.lower()}|{self.invoice_date.isoformat()}|{self.total_amount:.2f}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class ComplianceAuditResult(BaseModel):
    document_id: str
    fingerprint: str
    decision: TriageDecision
    route_used: ExtractionRoute
    passed_math_checks: bool
    flags: List[str] = Field(default_factory=list)


def audit_extracted_document(
    doc: ExtractedDocument,
    seen_fingerprints: set[str],
    confidence_threshold: float = 0.85,
    tax_id_required_above: Decimal = Decimal("500.00"),
) -> ComplianceAuditResult:
    """
    Deterministic policy & accounting audit layer (SR 26-2 control gate).
    Evaluates mathematical invariants, duplicate risk, tax ID thresholds,
    and model confidence before clearing straight-through processing.
    """
    flags: List[str] = []
    passed_math = True

    # 1. Reconcile sum of line items against stated subtotal
    computed_subtotal = sum(
        (item.line_total for item in doc.line_items), Decimal("0.00")
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    if abs(computed_subtotal - doc.subtotal) > Decimal("0.02"):
        passed_math = False
        flags.append(
            f"SUBTOTAL_MISMATCH: sum(lines)={computed_subtotal} vs subtotal={doc.subtotal}"
        )

    # 2. Reconcile subtotal + tax + fees against stated total
    computed_total = (
        doc.subtotal + doc.tax_amount + doc.tip_or_fee
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    if abs(computed_total - doc.total_amount) > Decimal("0.02"):
        passed_math = False
        flags.append(
            f"TOTAL_MISMATCH: subtotal+tax+fee={computed_total} vs total={doc.total_amount}"
        )

    # 3. Duplicate invoice / receipt fingerprint check
    if doc.fingerprint in seen_fingerprints:
        flags.append(f"DUPLICATE_FINGERPRINT: {doc.fingerprint}")

    # 4. Compliance policy: high-value invoices require a vendor Tax ID / EIN
    if doc.total_amount > tax_id_required_above and not doc.vendor_tax_id:
        flags.append(
            f"MISSING_TAX_ID: total {doc.total_amount} exceeds {tax_id_required_above} threshold"
        )

    # 5. Confidence threshold check across document & individual line items
    min_line_conf = min(item.confidence for item in doc.line_items)
    low_confidence = (
        doc.overall_confidence < confidence_threshold
        or min_line_conf < confidence_threshold
    )
    if low_confidence:
        flags.append(
            f"LOW_CONFIDENCE: doc={doc.overall_confidence:.2f}, min_line={min_line_conf:.2f}"
        )

    # Routing decision
    if not flags:
        decision = TriageDecision.AUTO_APPROVE
    elif low_confidence and doc.route_used == ExtractionRoute.LOCAL_OCR and len(flags) == 1:
        decision = TriageDecision.ESCALATE_VLM
    else:
        decision = TriageDecision.HUMAN_REVIEW

    return ComplianceAuditResult(
        document_id=doc.document_id,
        fingerprint=doc.fingerprint,
        decision=decision,
        route_used=doc.route_used,
        passed_math_checks=passed_math,
        flags=flags,
    )
