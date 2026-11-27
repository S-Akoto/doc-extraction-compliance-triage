from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict, List


def generate_benchmark_dataset() -> List[Dict[str, Any]]:
    """
    Produces 25 labeled evaluation cases covering:
    - Clean high-confidence receipts/invoices (12)
    - Noisy low-confidence OCR scans that VLM fallback repairs (6)
    - Arithmetic discrepancies / OCR digit misreads caught by guardrails (3)
    - High-value invoices (> $500) missing vendor Tax ID (2)
    - Duplicate invoice submissions (2)
    """
    cases: List[Dict[str, Any]] = []
    base_date = date(2026, 11, 1)

    vendors = [
        ("Northeast Brake & Rotor Co", "06-1122334"),
        ("Connecticut Fleet Lubricants", "06-2233445"),
        ("New England Diagnostic Supply", "06-3344556"),
        ("Middletown Commercial Tire", "06-4455667"),
    ]

    # 1. 12 Clean high-confidence documents
    for i in range(1, 13):
        vendor, tax_id = vendors[i % len(vendors)]
        qty = Decimal(str((i % 3) + 1))
        unit_price = Decimal(f"{45 + i * 5}.00")
        subtotal = (qty * unit_price).quantize(Decimal("0.01"))
        tax = (subtotal * Decimal("0.0635")).quantize(Decimal("0.01"))
        total = subtotal + tax
        inv_date = (base_date + timedelta(days=i)).isoformat()

        record = {
            "vendor_name": vendor,
            "vendor_tax_id": tax_id,
            "invoice_number": f"INV-2026-{1000 + i}",
            "invoice_date": inv_date,
            "line_items": [
                {
                    "description": f"Commercial Fleet Component #{i}",
                    "quantity": str(qty),
                    "unit_price": str(unit_price),
                    "line_total": str(subtotal),
                    "confidence": 0.96,
                }
            ],
            "subtotal": str(subtotal),
            "tax_amount": str(tax),
            "total_amount": str(total),
            "overall_confidence": 0.95,
        }
        cases.append(
            {
                "document_id": f"BENCH-{i:03d}",
                "category": "clean_standard",
                "local_ocr_output": record,
                "ground_truth": record,
                "expected_decision": "AUTO_APPROVE",
            }
        )

    # 2. 6 Noisy low-confidence OCR scans (VLM repairs OCR typos & raises confidence)
    for i in range(13, 19):
        vendor, tax_id = vendors[i % len(vendors)]
        subtotal = Decimal(f"{120 + (i - 12) * 15}.00")
        tax = (subtotal * Decimal("0.0635")).quantize(Decimal("0.01"))
        total = subtotal + tax
        inv_date = (base_date + timedelta(days=i)).isoformat()

        ground_truth = {
            "vendor_name": vendor,
            "vendor_tax_id": tax_id,
            "invoice_number": f"INV-2026-{1000 + i}",
            "invoice_date": inv_date,
            "line_items": [
                {
                    "description": f"Heavy Duty Assembly #{i}",
                    "quantity": "1",
                    "unit_price": str(subtotal),
                    "line_total": str(subtotal),
                    "confidence": 0.94,
                }
            ],
            "subtotal": str(subtotal),
            "tax_amount": str(tax),
            "total_amount": str(total),
            "overall_confidence": 0.94,
        }

        noisy_local = dict(ground_truth)
        # Simulate smudged vendor name & low OCR confidence
        noisy_local["vendor_name"] = vendor.replace("e", "3", 1)
        noisy_local["overall_confidence"] = 0.72
        noisy_local["line_items"] = [
            dict(ground_truth["line_items"][0], confidence=0.74)
        ]

        cases.append(
            {
                "document_id": f"BENCH-{i:03d}",
                "category": "noisy_low_confidence",
                "local_ocr_output": noisy_local,
                "ground_truth": ground_truth,
                "expected_decision": "AUTO_APPROVE",
            }
        )

    # 3. 3 Arithmetic discrepancy cases (total does not equal subtotal + tax)
    for i in range(19, 22):
        vendor, tax_id = vendors[i % len(vendors)]
        subtotal = Decimal("200.00")
        tax = Decimal("12.70")
        bad_total = Decimal("225.70")  # $13.00 discrepancy
        inv_date = (base_date + timedelta(days=i)).isoformat()

        bad_record = {
            "vendor_name": vendor,
            "vendor_tax_id": tax_id,
            "invoice_number": f"INV-2026-{1000 + i}",
            "invoice_date": inv_date,
            "line_items": [
                {
                    "description": f"Diagnostic Sensor Kit #{i}",
                    "quantity": "2",
                    "unit_price": "100.00",
                    "line_total": "200.00",
                    "confidence": 0.93,
                }
            ],
            "subtotal": str(subtotal),
            "tax_amount": str(tax),
            "total_amount": str(bad_total),
            "overall_confidence": 0.92,
        }
        cases.append(
            {
                "document_id": f"BENCH-{i:03d}",
                "category": "math_mismatch",
                "local_ocr_output": bad_record,
                "ground_truth": bad_record,
                "expected_decision": "HUMAN_REVIEW",
            }
        )

    # 4. 2 High-value invoices (> $500) missing required Vendor Tax ID
    for i in range(22, 24):
        vendor, _ = vendors[i % len(vendors)]
        subtotal = Decimal("650.00")
        tax = Decimal("41.28")
        total = Decimal("691.28")
        inv_date = (base_date + timedelta(days=i)).isoformat()

        missing_tin_record = {
            "vendor_name": vendor,
            "vendor_tax_id": None,
            "invoice_number": f"INV-2026-{1000 + i}",
            "invoice_date": inv_date,
            "line_items": [
                {
                    "description": f"Transmission Overhaul Core #{i}",
                    "quantity": "1",
                    "unit_price": "650.00",
                    "line_total": "650.00",
                    "confidence": 0.95,
                }
            ],
            "subtotal": str(subtotal),
            "tax_amount": str(tax),
            "total_amount": str(total),
            "overall_confidence": 0.94,
        }
        cases.append(
            {
                "document_id": f"BENCH-{i:03d}",
                "category": "missing_tax_id_policy",
                "local_ocr_output": missing_tin_record,
                "ground_truth": missing_tin_record,
                "expected_decision": "HUMAN_REVIEW",
            }
        )

    # 5. 2 Duplicate submissions of BENCH-001 and BENCH-002
    for idx, dup_source_idx in enumerate([0, 1], start=24):
        orig = dict(cases[dup_source_idx]["ground_truth"])
        cases.append(
            {
                "document_id": f"BENCH-{idx:03d}",
                "category": "duplicate_submission",
                "local_ocr_output": orig,
                "ground_truth": orig,
                "expected_decision": "HUMAN_REVIEW",
            }
        )

    return cases
