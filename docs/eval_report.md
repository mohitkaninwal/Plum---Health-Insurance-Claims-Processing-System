# Eval Report

Generated from `POST /eval/run` against `test_cases.json`.

## Metrics

| Metric | Value |
| --- | ---: |
| Total cases | 12 |
| Completed cases | 12 |
| Decision accuracy | 100% |
| Early-stop accuracy | 100% |
| Approved amount exact match rate | 100% |
| Retrieval precision@k | 100% |
| Retrieval recall@k | 100% |

## Case Results

| Case | Passed | Status | Decision | Approved | Primary reason |
| --- | --- | --- | --- | ---: | --- |
| TC001 | Yes | ACTION_REQUIRED | Early stop | - | CONSULTATION requires HOSPITAL_BILL, but uploaded documents were classified as PRESCRIPTION. |
| TC002 | Yes | ACTION_REQUIRED | Early stop | - | The uploaded document blurry_bill.jpg is unreadable. |
| TC003 | Yes | ACTION_REQUIRED | Early stop | - | Documents contain different patient names: Arjun Mehta and Rajesh Kumar. |
| TC004 | Yes | COMPLETED | APPROVED | 1350 | Co-pay 10% deducted. |
| TC005 | Yes | COMPLETED | REJECTED | 0 | Diabetes treatment is in the 90-day waiting period; eligible from 2024-11-30. |
| TC006 | Yes | COMPLETED | PARTIAL | 8000 | Covered dental items were approved and excluded cosmetic items were rejected. |
| TC007 | Yes | COMPLETED | REJECTED | 0 | Pre-authorization is required for MRI above INR 10000; none was provided. |
| TC008 | Yes | COMPLETED | REJECTED | 0 | Claimed amount INR 7500 exceeds the per-claim limit of INR 5000. |
| TC009 | Yes | COMPLETED | MANUAL_REVIEW | 0 | 4 same-day claims for member EMP008 triggered manual review. |
| TC010 | Yes | COMPLETED | APPROVED | 3240 | Network discount 20% applied before co-pay; co-pay 10% deducted. |
| TC011 | Yes | COMPLETED | APPROVED | 4000 | Processing continued after a recoverable component failure with reduced confidence. |
| TC012 | Yes | COMPLETED | REJECTED | 0 | Treatment is excluded under the obesity and weight loss programs exclusion. |

## Notes

The current implementation uses deterministic fixture extraction through `actual_type`, `quality`, `patient_name_on_doc`, and `content` fields in `test_cases.json`. Real OCR/vision extraction and hybrid vector retrieval remain integration points; the response contract already exposes component failures, policy evidence, line-item decisions, and trace events so those components can be swapped in without changing API consumers.
