# SR 26-2 Model Validation & Compliance Triage Benchmark Report

- **Benchmark Sample Size:** 25 documents
- **Field-Level Precision:** 100.00%
- **Field-Level Recall:** 100.00%
- **Field-Level F1 Score:** 100.00%
- **Document Exact-Match Rate:** 100.00%
- **Compliance Triage Gate Accuracy:** 100.00%
- **Straight-Through Processing (STP) Rate:** 72.00%
- **VLM Escalation Rate:** 24.00%
- **Average Latency:** 0.68 ms/doc
- **Total Batch Cost:** $0.01580

## Breakdown by Risk & Quality Scenario

| Scenario | Docs | Triage Accuracy | Exact Match |
| :--- | :---: | :---: | :---: |
| `clean_standard` | 12 | 100% | 100% |
| `noisy_low_confidence` | 6 | 100% | 100% |
| `math_mismatch` | 3 | 100% | 100% |
| `missing_tax_id_policy` | 2 | 100% | 100% |
| `duplicate_submission` | 2 | 100% | 100% |
