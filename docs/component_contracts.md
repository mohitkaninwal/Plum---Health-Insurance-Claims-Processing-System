# Component Contracts

## API Contracts

### `POST /claims/submit`

Accepts a claim submission and returns the standard claim response envelope. Phase 2 stores the submission in memory and marks it as `RECEIVED`; later phases will attach the processing pipeline without changing this public shape.

Input:

- `member_id`: string
- `policy_id`: string
- `claim_category`: `CONSULTATION | DIAGNOSTIC | PHARMACY | DENTAL | VISION | ALTERNATIVE_MEDICINE`
- `treatment_date`: ISO date
- `claimed_amount`: positive number
- `documents`: one or more uploaded document records
- `ytd_claims_amount`: optional number
- `hospital_name`: optional string
- `claims_history`: optional prior claim records
- `simulate_component_failure`: optional boolean for eval scenarios

Output:

- `claim_id`
- `status`
- `submitted_at`
- `submission`
- `decision`
- `approved_amount`
- `confidence_score`
- `reason`
- `rejection_reasons`
- `line_item_decisions`
- `member_action_required`
- `trace`
- `retrieved_policy_evidence`
- `component_failures`

Errors:

- `422` for invalid payloads

### `GET /claims/{claim_id}`

Returns the stored claim response envelope for the supplied ID.

Errors:

- `404` when the claim does not exist

### `POST /eval/run`

Creates an eval run shell for the 12 assignment cases. Later phases will execute the full pipeline and populate per-case results.

Output:

- `eval_run_id`
- `status`
- `started_at`
- `completed_at`
- `metrics`
- `cases`

### `GET /eval/latest`

Returns the latest eval run if available, otherwise a default empty eval shell.

## Planned Component Contracts

The following components will be implemented in later phases using the models already defined in `backend/app/models/contracts.py`.

- Document classifier: `UploadedDocument -> DocumentClassification`
- Document extractor: `UploadedDocument + DocumentClassification -> ExtractedDocumentData`
- Policy retriever: `ClaimSubmission + ExtractedDocumentData[] -> PolicyEvidence[]`
- Rule engine: `ClaimSubmission + ExtractedDocumentData[] + PolicyEvidence[] -> ClaimDecision`
- Fraud signal detector: `ClaimSubmission + ClaimHistoryItem[] -> RuleCheckResult[]`
- Explanation builder: `TraceEvent[] + RuleCheckResult[] -> ClaimResponse`
- Eval runner: `test_cases.json -> EvalRun`
