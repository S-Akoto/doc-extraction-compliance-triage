# Evaluated Structured Document Extraction & Compliance Triage Engine

Hybrid document extraction and deterministic compliance triage pipeline combining fast local OCR extraction, confidence-gated Vision-Language Model (VLM) escalation, Pydantic v2 accounting guardrails, DuckDB audit warehousing, and an SR 26-2 model validation benchmark harness.

## Architecture

1. **Deterministic Accounting & Policy Guardrails (`src/schemas.py`):**
   - Validates line-item arithmetic (`quantity * unit_price == line_total`), subtotal reconciliation, and grand-total invariants (`subtotal + tax + fee == total`).
   - Enforces policy controls including high-value (`> $500`) vendor Tax ID checks and SHA-256 fingerprint duplicate invoice detection.
2. **Cost-Aware Hybrid Routing Engine (`src/router.py`):**
   - Routes clean, high-confidence documents through low-cost local extraction (`LOCAL_OCR`).
   - Escalates low-confidence or math-failing extractions to structured Gemini VLM extraction (`VLM_FALLBACK`), routing unresolved anomalies to `HUMAN_REVIEW`.
3. **DuckDB Audit Warehouse (`src/warehouse.py`):**
   - Persists normalized header records, line items, and compliance audit flags (`AUTO_APPROVE`, `ESCALATE_VLM`, `HUMAN_REVIEW`) alongside per-document latency and cost telemetry.
4. **SR 26-2 Model Validation Harness (`src/evaluate.py`):**
   - Evaluates field-level Precision, Recall, F1, Exact-Match accuracy, Straight-Through Processing (STP) rate, and VLM escalation rate across clean, noisy OCR, arithmetic mismatch, missing Tax ID, and duplicate scenarios.

## Quickstart

    python3 -m venv .venv
    source .venv/bin/activate
    pip install pydantic duckdb google-genai python-dotenv pytest pandas
    python -m pytest -v
    python -m src.evaluate
