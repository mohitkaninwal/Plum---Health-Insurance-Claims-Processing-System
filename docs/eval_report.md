# Eval Report

Generated: 2026-06-28 11:18 UTC  
Eval run ID: `EVAL_D380D9698A0A`  
Cases: 12/12

## Aggregate Metrics

| Metric | Value | Notes |
| --- | ---: | --- |
| Decision accuracy | 100.0% | Correct decision type out of all cases |
| Early-stop accuracy | 100.0% | ACTION_REQUIRED returned correctly before adjudication |
| Approved amount exact match | 100.0% | Applies to 3 cases |
| System-must accuracy | 100.0% | Behavioural requirements across all system_must items |
| Rejection reason precision | 100.0% | Macro-avg over 4 cases with expected labels |
| Rejection reason recall | 100.0% | Macro-avg |
| Rejection reason F1 | 100.0% | Harmonic mean of precision and recall |

> Retrieval precision@k, recall@k, MRR, NDCG are not computed: `test_cases.json` contains
> no `expected_evidence_ids` field, so ground-truth evidence labels do not exist.

---

## Per-Case Results

### ✅ TC001 — Wrong Document Uploaded

**Input summary**

- Member: `EMP001` · Policy: `PLUM_GHI_2024`
- Category: `CONSULTATION` · Treatment date: `2024-11-01`
- Claimed amount: INR 1,500
- Hospital: —
- Documents: `F001` (UNKNOWN), `F002` (UNKNOWN)

**Expected vs actual**

| Field | Expected | Actual |
| --- | --- | --- |
| Decision | `None` | `ACTION_REQUIRED` |

**System-must checks**

- ✅ Stop before making any claim decision
- ✅ Tell the member specifically what document type was uploaded and what is needed instead
- ✅ Not return a generic error — the message must name the uploaded document type and the required document type

**Trace summary**

1. `ClaimIntakeAPI` [INFO] — Claim submission accepted.
2. `DocumentClassifier` [INFO] — Documents classified for early intake validation.
3. `DocumentVerifierAgent` [WARNING] (-0.20) — A HOSPITAL_BILL document is required for CONSULTATION claims, but only PRESCRIPTION and PRESCRIPTION documents were uploaded.

---

### ✅ TC002 — Unreadable Document

**Input summary**

- Member: `EMP004` · Policy: `PLUM_GHI_2024`
- Category: `PHARMACY` · Treatment date: `2024-10-25`
- Claimed amount: INR 800
- Hospital: —
- Documents: `F003` (UNKNOWN), `F004` (UNKNOWN)

**Expected vs actual**

| Field | Expected | Actual |
| --- | --- | --- |
| Decision | `None` | `ACTION_REQUIRED` |

**System-must checks**

- ✅ Identify that the pharmacy bill cannot be read
- ✅ Ask the member to re-upload that specific document
- ✅ Not reject the claim outright

**Trace summary**

1. `ClaimIntakeAPI` [INFO] — Claim submission accepted.
2. `DocumentClassifier` [INFO] — Documents classified for early intake validation.
3. `DocumentVerifierAgent` [WARNING] (-0.35) — The uploaded document "blurry_bill.jpg" is unreadable. Please re-upload a clearer image or PDF.

---

### ✅ TC003 — Documents Belong to Different Patients

**Input summary**

- Member: `EMP001` · Policy: `PLUM_GHI_2024`
- Category: `CONSULTATION` · Treatment date: `2024-11-01`
- Claimed amount: INR 1,500
- Hospital: —
- Documents: `F005` (UNKNOWN), `F006` (UNKNOWN)

**Expected vs actual**

| Field | Expected | Actual |
| --- | --- | --- |
| Decision | `None` | `ACTION_REQUIRED` |

**System-must checks**

- ✅ Detect that the documents belong to different people
- ✅ Surface this to the member with the specific names found on each document
- ✅ Not proceed to a claim decision

**Trace summary**

1. `ClaimIntakeAPI` [INFO] — Claim submission accepted.
2. `DocumentClassifier` [INFO] — Documents classified for early intake validation.
3. `PatientConsistencyAgent` [WARNING] (-0.25) — Uploaded documents appear to belong to different patients: Arjun Mehta, Rajesh Kumar. Please upload documents for the same patient.

---

### ✅ TC004 — Clean Consultation — Full Approval

**Input summary**

- Member: `EMP001` · Policy: `PLUM_GHI_2024`
- Category: `CONSULTATION` · Treatment date: `2024-11-01`
- Claimed amount: INR 1,500
- Hospital: —
- Documents: `F007` (UNKNOWN), `F008` (UNKNOWN)

**Expected vs actual**

| Field | Expected | Actual |
| --- | --- | --- |
| Decision | `APPROVED` | `APPROVED` |
| Approved amount | INR 1,350 | INR 1,350 |
| Confidence | above 0.85 | 0.93 |

**Trace summary**

1. `ClaimIntakeAPI` [INFO] — Claim submission accepted.
2. `DocumentClassifier` [INFO] — Documents classified for early intake validation.
3. `DocumentVerifierAgent` [INFO] — Required documents are present, readable, and patient names are consistent.
4. `DocumentVerifierAgent` [INFO] — Extraction inputs verified after intake validation.
5. `VisionExtractionAgent` [INFO] — Document fields extracted and Pydantic-validated.
6. `StructuredNormalizationAgent` [INFO] — Extracted fields normalized for deterministic rule checks.
7. `PatientConsistencyAgent` [INFO] — Extracted patient identity fields are consistent or unavailable.
8. `RuleEngine` [INFO] — Deterministic policy checks completed.
9. `ConfidenceScorer` [INFO] (-0.04) — Final confidence score computed from document, extraction, policy, rule, and component signals.
10. `DecisionExplainer` [INFO] — Decision explanation assembled for review.

---

### ✅ TC005 — Waiting Period — Diabetes

**Input summary**

- Member: `EMP005` · Policy: `PLUM_GHI_2024`
- Category: `CONSULTATION` · Treatment date: `2024-10-15`
- Claimed amount: INR 3,000
- Hospital: —
- Documents: `F009` (UNKNOWN), `F010` (UNKNOWN)

**Expected vs actual**

| Field | Expected | Actual |
| --- | --- | --- |
| Decision | `REJECTED` | `REJECTED` |
| Rejection reasons | `WAITING_PERIOD` | `WAITING_PERIOD` |

**System-must checks**

- ✅ State the date from which the member will be eligible for diabetes-related claims

**Trace summary**

1. `ClaimIntakeAPI` [INFO] — Claim submission accepted.
2. `DocumentClassifier` [INFO] — Documents classified for early intake validation.
3. `DocumentVerifierAgent` [INFO] — Required documents are present, readable, and patient names are consistent.
4. `DocumentVerifierAgent` [INFO] — Extraction inputs verified after intake validation.
5. `VisionExtractionAgent` [INFO] — Document fields extracted and Pydantic-validated.
6. `StructuredNormalizationAgent` [INFO] — Extracted fields normalized for deterministic rule checks.
7. `PatientConsistencyAgent` [INFO] — Extracted patient identity fields are consistent or unavailable.
8. `RuleEngine` [WARNING] (-0.11) — Diabetes treatment is in the 90-day waiting period. Member is eligible for this condition from 2024-11-30.
9. `ConfidenceScorer` [INFO] (-0.11) — Final confidence score computed from document, extraction, policy, rule, and component signals.
10. `DecisionExplainer` [INFO] — Decision explanation assembled for review.

---

### ✅ TC006 — Dental Partial Approval — Cosmetic Exclusion

**Input summary**

- Member: `EMP002` · Policy: `PLUM_GHI_2024`
- Category: `DENTAL` · Treatment date: `2024-10-15`
- Claimed amount: INR 12,000
- Hospital: —
- Documents: `F011` (UNKNOWN)

**Expected vs actual**

| Field | Expected | Actual |
| --- | --- | --- |
| Decision | `PARTIAL` | `PARTIAL` |
| Approved amount | INR 8,000 | INR 8,000 |

**System-must checks**

- ✅ Itemize which line items were approved and which were rejected
- ✅ State the reason for each rejection at the line-item level

**Trace summary**

1. `ClaimIntakeAPI` [INFO] — Claim submission accepted.
2. `DocumentClassifier` [INFO] — Documents classified for early intake validation.
3. `DocumentVerifierAgent` [INFO] — Required documents are present, readable, and patient names are consistent.
4. `DocumentVerifierAgent` [INFO] — Extraction inputs verified after intake validation.
5. `VisionExtractionAgent` [INFO] — Document fields extracted and Pydantic-validated.
6. `StructuredNormalizationAgent` [INFO] — Extracted fields normalized for deterministic rule checks.
7. `PatientConsistencyAgent` [INFO] — Extracted patient identity fields are consistent or unavailable.
8. `RuleEngine` [INFO] — Deterministic policy checks completed.
9. `ConfidenceScorer` [INFO] (-0.04) — Final confidence score computed from document, extraction, policy, rule, and component signals.
10. `DecisionExplainer` [INFO] — Decision explanation assembled for review.

---

### ✅ TC007 — MRI Without Pre-Authorization

**Input summary**

- Member: `EMP007` · Policy: `PLUM_GHI_2024`
- Category: `DIAGNOSTIC` · Treatment date: `2024-11-02`
- Claimed amount: INR 15,000
- Hospital: —
- Documents: `F012` (UNKNOWN), `F013` (UNKNOWN), `F014` (UNKNOWN)

**Expected vs actual**

| Field | Expected | Actual |
| --- | --- | --- |
| Decision | `REJECTED` | `REJECTED` |
| Rejection reasons | `PRE_AUTH_MISSING` | `PRE_AUTH_MISSING` |

**System-must checks**

- ✅ Explain that pre-authorization was required and not obtained
- ✅ Tell the member what they should do to resubmit with pre-auth

**Trace summary**

1. `ClaimIntakeAPI` [INFO] — Claim submission accepted.
2. `DocumentClassifier` [INFO] — Documents classified for early intake validation.
3. `DocumentVerifierAgent` [INFO] — Required documents are present, readable, and patient names are consistent.
4. `DocumentVerifierAgent` [INFO] — Extraction inputs verified after intake validation.
5. `VisionExtractionAgent` [INFO] (-0.06) — Document fields extracted and Pydantic-validated.
6. `StructuredNormalizationAgent` [INFO] — Extracted fields normalized for deterministic rule checks.
7. `PatientConsistencyAgent` [INFO] — Extracted patient identity fields are consistent or unavailable.
8. `RuleEngine` [WARNING] (-0.21) — Claim on hold — Pre-Authorization Approval required.

Your Diagnostic claim (Claim ID: CLM_F8C5E3BE2FD9) includes a procedure that requires
prior approval from the insurer before reimbursement can be processed.

Procedure detected: MRI
Claimed amount:     ₹15,000
Pre-auth required:  Yes (mandatory for MRI above ₹10,000)

If you already have pre-authorization:
  Upload your Pre-Authorization Approval Letter. The letter must be valid
  (within 30 days of the procedure date) and show an approval reference number.

If you do not have pre-authorization:
  Cashless/reimbursement for this procedure cannot be processed without prior
  approval. Contact Plum support immediately — approvals cannot be granted
  retroactively in most cases.

Policy Reference: Section 4 — Pre-Authorization Requirements
9. `ConfidenceScorer` [INFO] (-0.21) — Final confidence score computed from document, extraction, policy, rule, and component signals.
10. `DecisionExplainer` [INFO] — Decision explanation assembled for review.

---

### ✅ TC008 — Per-Claim Limit Exceeded

**Input summary**

- Member: `EMP003` · Policy: `PLUM_GHI_2024`
- Category: `CONSULTATION` · Treatment date: `2024-10-20`
- Claimed amount: INR 7,500
- Hospital: —
- Documents: `F015` (UNKNOWN), `F016` (UNKNOWN)

**Expected vs actual**

| Field | Expected | Actual |
| --- | --- | --- |
| Decision | `REJECTED` | `REJECTED` |
| Rejection reasons | `PER_CLAIM_EXCEEDED` | `PER_CLAIM_EXCEEDED` |

**System-must checks**

- ✅ State the per-claim limit and the claimed amount clearly in the rejection message

**Trace summary**

1. `ClaimIntakeAPI` [INFO] — Claim submission accepted.
2. `DocumentClassifier` [INFO] — Documents classified for early intake validation.
3. `DocumentVerifierAgent` [INFO] — Required documents are present, readable, and patient names are consistent.
4. `DocumentVerifierAgent` [INFO] — Extraction inputs verified after intake validation.
5. `VisionExtractionAgent` [INFO] (-0.04) — Document fields extracted and Pydantic-validated.
6. `StructuredNormalizationAgent` [INFO] — Extracted fields normalized for deterministic rule checks.
7. `PatientConsistencyAgent` [INFO] — Extracted patient identity fields are consistent or unavailable.
8. `RuleEngine` [WARNING] (-0.17) — Claimed amount INR 7500 exceeds the per-claim limit of INR 5000.
9. `ConfidenceScorer` [INFO] (-0.17) — Final confidence score computed from document, extraction, policy, rule, and component signals.
10. `DecisionExplainer` [INFO] — Decision explanation assembled for review.

---

### ✅ TC009 — Fraud Signal — Multiple Same-Day Claims

**Input summary**

- Member: `EMP008` · Policy: `PLUM_GHI_2024`
- Category: `CONSULTATION` · Treatment date: `2024-10-30`
- Claimed amount: INR 4,800
- Hospital: —
- Documents: `F017` (UNKNOWN), `F018` (UNKNOWN)

**Expected vs actual**

| Field | Expected | Actual |
| --- | --- | --- |
| Decision | `MANUAL_REVIEW` | `MANUAL_REVIEW` |

**System-must checks**

- ✅ Flag the unusual same-day claim pattern
- ✅ Route to manual review rather than auto-rejecting
- ✅ Include the specific signals that triggered the flag in the output

**Trace summary**

1. `ClaimIntakeAPI` [INFO] — Claim submission accepted.
2. `DocumentClassifier` [INFO] — Documents classified for early intake validation.
3. `DocumentVerifierAgent` [INFO] — Required documents are present, readable, and patient names are consistent.
4. `DocumentVerifierAgent` [INFO] — Extraction inputs verified after intake validation.
5. `VisionExtractionAgent` [INFO] (-0.04) — Document fields extracted and Pydantic-validated.
6. `StructuredNormalizationAgent` [INFO] — Extracted fields normalized for deterministic rule checks.
7. `PatientConsistencyAgent` [INFO] — Extracted patient identity fields are consistent or unavailable.
8. `FraudSignalAgent` [WARNING] (-0.14) — Claim routed to manual review due to fraud signals.
9. `ConfidenceScorer` [INFO] (-0.25) — Final confidence score computed from document, extraction, policy, rule, and component signals.
10. `DecisionExplainer` [INFO] — Decision explanation assembled for review.

---

### ✅ TC010 — Network Hospital — Discount Applied

**Input summary**

- Member: `EMP010` · Policy: `PLUM_GHI_2024`
- Category: `CONSULTATION` · Treatment date: `2024-11-03`
- Claimed amount: INR 4,500
- Hospital: Apollo Hospitals
- Documents: `F019` (UNKNOWN), `F020` (UNKNOWN)

**Expected vs actual**

| Field | Expected | Actual |
| --- | --- | --- |
| Decision | `APPROVED` | `APPROVED` |
| Approved amount | INR 3,240 | INR 3,240 |

**System-must checks**

- ✅ Apply network discount before co-pay, not after
- ✅ Show the breakdown of discount and co-pay in the decision output

**Trace summary**

1. `ClaimIntakeAPI` [INFO] — Claim submission accepted.
2. `DocumentClassifier` [INFO] — Documents classified for early intake validation.
3. `DocumentVerifierAgent` [INFO] — Required documents are present, readable, and patient names are consistent.
4. `DocumentVerifierAgent` [INFO] — Extraction inputs verified after intake validation.
5. `VisionExtractionAgent` [INFO] — Document fields extracted and Pydantic-validated.
6. `StructuredNormalizationAgent` [INFO] — Extracted fields normalized for deterministic rule checks.
7. `PatientConsistencyAgent` [INFO] — Extracted patient identity fields are consistent or unavailable.
8. `RuleEngine` [INFO] — Deterministic policy checks completed.
9. `ConfidenceScorer` [INFO] (-0.04) — Final confidence score computed from document, extraction, policy, rule, and component signals.
10. `DecisionExplainer` [INFO] — Decision explanation assembled for review.

---

### ✅ TC011 — Component Failure — Graceful Degradation

**Input summary**

- Member: `EMP006` · Policy: `PLUM_GHI_2024`
- Category: `ALTERNATIVE_MEDICINE` · Treatment date: `2024-10-28`
- Claimed amount: INR 4,000
- Hospital: —
- Documents: `F021` (UNKNOWN), `F022` (UNKNOWN)

**Expected vs actual**

| Field | Expected | Actual |
| --- | --- | --- |
| Decision | `APPROVED` | `APPROVED` |

**System-must checks**

- ✅ Not crash or return a 500 error
- ✅ Indicate in the output that a component failed and was skipped
- ✅ Return a confidence score lower than a normal full-pipeline approval
- ✅ Include a note that manual review is recommended due to incomplete processing

**Trace summary**

1. `ClaimIntakeAPI` [INFO] — Claim submission accepted.
2. `DocumentClassifier` [INFO] — Documents classified for early intake validation.
3. `DocumentVerifierAgent` [INFO] — Required documents are present, readable, and patient names are consistent.
4. `DocumentVerifierAgent` [INFO] — Extraction inputs verified after intake validation.
5. `VisionExtractionAgent` [INFO] (-0.04) — Document fields extracted and Pydantic-validated.
6. `StructuredNormalizationAgent` [INFO] — Extracted fields normalized for deterministic rule checks.
7. `PatientConsistencyAgent` [INFO] — Extracted patient identity fields are consistent or unavailable.
8. `PolicyEvidenceRetriever` [WARNING] (-0.12) — Recoverable component failure recorded; adjudication continued.
9. `RuleEngine` [INFO] — Deterministic policy checks completed.
10. `ConfidenceScorer` [INFO] (-0.23) — Final confidence score computed from document, extraction, policy, rule, and component signals.
11. `DecisionExplainer` [INFO] — Decision explanation assembled for review.

---

### ✅ TC012 — Excluded Treatment

**Input summary**

- Member: `EMP009` · Policy: `PLUM_GHI_2024`
- Category: `CONSULTATION` · Treatment date: `2024-10-18`
- Claimed amount: INR 8,000
- Hospital: —
- Documents: `F023` (UNKNOWN), `F024` (UNKNOWN)

**Expected vs actual**

| Field | Expected | Actual |
| --- | --- | --- |
| Decision | `REJECTED` | `REJECTED` |
| Rejection reasons | `EXCLUDED_CONDITION` | `EXCLUDED_CONDITION` |
| Confidence | above 0.90 | 0.91 |

**Trace summary**

1. `ClaimIntakeAPI` [INFO] — Claim submission accepted.
2. `DocumentClassifier` [INFO] — Documents classified for early intake validation.
3. `DocumentVerifierAgent` [INFO] — Required documents are present, readable, and patient names are consistent.
4. `DocumentVerifierAgent` [INFO] — Extraction inputs verified after intake validation.
5. `VisionExtractionAgent` [INFO] (-0.04) — Document fields extracted and Pydantic-validated.
6. `StructuredNormalizationAgent` [INFO] — Extracted fields normalized for deterministic rule checks.
7. `PatientConsistencyAgent` [INFO] — Extracted patient identity fields are consistent or unavailable.
8. `RuleEngine` [WARNING] (-0.06) — Treatment is excluded under policy exclusion: Obesity and weight loss programs.
9. `ConfidenceScorer` [INFO] (-0.06) — Final confidence score computed from document, extraction, policy, rule, and component signals.
10. `DecisionExplainer` [INFO] — Decision explanation assembled for review.

---
