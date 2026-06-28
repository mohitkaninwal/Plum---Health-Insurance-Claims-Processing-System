# Component Contracts

Every significant component is defined below with its precise input type, output type, and errors it can raise. An engineer can reimplement any single component from this document without reading the source code.

---

## API Endpoints

### `POST /claims/submit`

Accepts a claim submission as JSON and runs the full processing pipeline synchronously.

**Input — `ClaimSubmission` (JSON body)**

| Field | Type | Required | Notes |
|---|---|---|---|
| `member_id` | `string` | yes | Must exist in the active policy's member roster |
| `policy_id` | `string` | yes | Must match the loaded policy's `policy_id` |
| `claim_category` | `ClaimCategory` enum | yes | `CONSULTATION \| DIAGNOSTIC \| PHARMACY \| DENTAL \| VISION \| ALTERNATIVE_MEDICINE` |
| `treatment_date` | `ISO 8601 date` | yes | Format: `YYYY-MM-DD` |
| `claimed_amount` | `float > 0` | yes | Total amount claimed in INR |
| `documents` | `UploadedDocument[]` | yes | At least one document required |
| `ytd_claims_amount` | `float >= 0` | no | Year-to-date claims total for limit checks |
| `hospital_name` | `string` | no | Used for network hospital verification |
| `claims_history` | `ClaimHistoryItem[]` | no | Prior claims for fraud signal detection |
| `simulate_component_failure` | `boolean` | no | For test scenarios only; defaults to `false` |

**`UploadedDocument` fields**

| Field | Type | Required | Notes |
|---|---|---|---|
| `file_id` | `string` | yes | Unique identifier for the document |
| `file_name` | `string` | no | Used for filename-based type inference |
| `declared_type` | `DocumentType` enum | no | Submitter-declared document type |
| `actual_type` | `DocumentType` enum | no | Fixture-only; bypasses classification |
| `quality` | `DocumentQuality` enum | no | `GOOD \| LOW \| UNREADABLE \| UNKNOWN` (default: `UNKNOWN`) |
| `patient_name_on_doc` | `string` | no | Used for patient consistency checks |
| `content` | `dict[str, Any]` | no | Fixture extraction fields or upload metadata |

**Output — `ClaimResponse` (HTTP 202)**

| Field | Type | Notes |
|---|---|---|
| `claim_id` | `string` | Format: `CLM_<12-char hex>` |
| `status` | `ClaimStatus` enum | `RECEIVED \| PROCESSING \| ACTION_REQUIRED \| COMPLETED \| FAILED` |
| `submitted_at` | `ISO 8601 datetime` | UTC |
| `submission` | `ClaimSubmission` | Echo of the original submission |
| `decision` | `ClaimDecision \| null` | Null when `status == ACTION_REQUIRED` |
| `approved_amount` | `float \| null` | Null when no decision was reached |
| `confidence_score` | `float [0,1] \| null` | Null when no decision was reached |
| `reason` | `string \| null` | Human-readable summary of the decision |
| `rejection_reasons` | `string[]` | Coded rejection reason identifiers |
| `line_item_decisions` | `LineItemDecision[]` | Per-item breakdowns for partial approvals |
| `extracted_document_data` | `ExtractedDocumentData[]` | Structured fields extracted from each document |
| `member_action_required` | `MemberActionRequired \| null` | Set when early stop is triggered |
| `trace` | `TraceEvent[]` | Ordered audit log of every processing step |
| `retrieved_policy_evidence` | `PolicyEvidence[]` | Policy chunks that informed the decision |
| `component_failures` | `ComponentFailure[]` | Recoverable failures encountered during processing |

**Errors**

| Status | Condition |
|---|---|
| `422 Unprocessable Entity` | Missing or invalid required fields; Pydantic validation failure |

---

### `POST /claims/submit/upload`

Accepts a claim submission as a multipart form with real file uploads. Runs Groq Vision classification on image files when `GROQ_API_KEY` is configured.

**Input — multipart/form-data**

| Field | Type | Required | Notes |
|---|---|---|---|
| `member_id` | `string` | yes | |
| `policy_id` | `string` | yes | |
| `claim_category` | `ClaimCategory` | yes | |
| `treatment_date` | `string (YYYY-MM-DD)` | yes | |
| `claimed_amount` | `float > 0` | yes | |
| `files` | `UploadFile[]` | yes | At least one file |
| `ytd_claims_amount` | `float` | no | |
| `hospital_name` | `string` | no | |
| `declared_types` | `JSON string` | no | Map of `filename → DocumentType` or `index → DocumentType` |
| `patient_names` | `JSON string` | no | Map of `filename → patient name` |

**Output** — Same `ClaimResponse` shape as `POST /claims/submit`.

**Errors**

| Status | Condition |
|---|---|
| `422` | Missing required fields or invalid `declared_types` JSON |

---

### `GET /claims/{claim_id}`

Returns the stored `ClaimResponse` for a previously submitted claim.

**Input** — `claim_id` path parameter (string).

**Output** — `ClaimResponse` (HTTP 200).

**Errors**

| Status | Condition |
|---|---|
| `404 Not Found` | `claim_id` does not exist in the in-memory store |

---

### `POST /eval/run`

Executes all 12 test cases from `test_cases.json` through the full pipeline and returns aggregated metrics.

**Input** — No body required.

**Output — `EvalRun`**

| Field | Type | Notes |
|---|---|---|
| `eval_run_id` | `string` | Format: `EVAL_<12-char hex>` |
| `status` | `ClaimStatus` | `COMPLETED` on success |
| `started_at` | `ISO 8601 datetime` | UTC |
| `completed_at` | `ISO 8601 datetime \| null` | UTC |
| `metrics` | `EvalMetrics` | Aggregate accuracy statistics |
| `cases` | `EvalCaseResult[]` | Per-case pass/fail with full `ClaimResponse` |

**`EvalMetrics` fields**

| Field | Type |
|---|---|
| `total_cases` | `int` |
| `completed_cases` | `int` |
| `decision_accuracy` | `float [0,1]` |
| `early_stop_accuracy` | `float [0,1]` |
| `approved_amount_exact_match_rate` | `float [0,1]` |
| `retrieval_precision_at_k` | `float [0,1]` |
| `retrieval_recall_at_k` | `float [0,1]` |

**Errors**

| Status | Condition |
|---|---|
| `500` | `test_cases.json` missing or malformed |

---

### `GET /eval/latest`

Returns the most recent `EvalRun` if available, otherwise an empty shell with `status = RECEIVED`.

**Input** — None.

**Output** — `EvalRun`.

**Errors** — None (always returns 200).

---

### `GET /health`

Returns API status.

**Input** — None.

**Output** — `{ "status": "ok" }` (HTTP 200).

---

## Service Components

---

### `DocumentClassifier` — `classify_document`

**Module:** `app.services.document_intake`

Classifies a single uploaded document into a `DocumentType` using a priority fallback chain. Fully synchronous and always returns a result — never raises.

**Input**

| Parameter | Type | Notes |
|---|---|---|
| `document` | `UploadedDocument` | The document to classify |

**Classification fallback chain (priority order)**

1. **Fixture** — If `document.actual_type` is set, return it directly with `confidence=1.0`.
2. **Quality gate** — If `document.quality == UNREADABLE`, return `UNKNOWN` with `confidence=0.0`.
3. **Groq Vision** (upload path only) — Called upstream in `submission_from_upload_form`; if successful, `actual_type` is already set before `classify_document` is called.
4. **Filename inference** — Matches filename stem against keywords (`prescription`, `bill`, `lab`, `dental`, etc.) with `confidence=0.74`.
5. **Declared type** — Uses `document.declared_type` with `confidence=0.62`.
6. **Unknown fallback** — Returns `UNKNOWN` with `confidence=0.2`.

**Output — `IntakeClassification`**

| Field | Type | Notes |
|---|---|---|
| `document` | `UploadedDocument` | Echo of the input document |
| `classification` | `DocumentClassification` | Classified type, confidence, rationale |
| `source` | `string` | One of: `fixture`, `quality`, `preprocessing`, `declared`, `unknown` |

**`DocumentClassification` fields**

| Field | Type |
|---|---|
| `file_id` | `string` |
| `document_type` | `DocumentType` |
| `confidence` | `float [0,1]` |
| `rationale` | `string` |

**Errors** — None. All exceptions in the Groq Vision path are caught upstream; `classify_document` itself is exception-free.

---

### `UploadFormParser` — `submission_from_upload_form`

**Module:** `app.services.document_intake`

Parses a multipart upload form into a `ClaimSubmission`. For image files, calls Groq Vision to classify and set `actual_type` on the document before returning. Async.

**Input — `UploadDocumentForm`**

| Field | Type |
|---|---|
| `member_id` | `string` |
| `policy_id` | `string` |
| `claim_category` | `ClaimCategory` |
| `treatment_date` | `string` |
| `claimed_amount` | `float > 0` |
| `files` | `list[UploadFile]` (min 1) |
| `ytd_claims_amount` | `float \| None` |
| `hospital_name` | `string \| None` |
| `declared_types` | `string \| None` — JSON object `{filename: DocumentType}` |
| `patient_names` | `string \| None` — JSON object `{filename: patient_name}` |

**Output** — `ClaimSubmission`

**Errors**

| Error | Condition |
|---|---|
| `ValueError` | `declared_types` JSON is not a valid object, or contains an unrecognised `DocumentType` value |

---

### `ExtractionPipeline` — `run_extraction_pipeline`

**Module:** `app.services.extraction_pipeline`

Orchestrates a four-node LangGraph pipeline that classifies, extracts, normalises, and validates documents from a claim submission. Always returns a result; component failures are captured in the output rather than raised.

**Input**

| Parameter | Type |
|---|---|
| `submission` | `ClaimSubmission` |

**Pipeline nodes (in order)**

| Node | Component Name | Responsibility |
|---|---|---|
| 1 | `DocumentVerifierAgent` | Re-classifies documents; flags low quality (`LOW` only — not `UNKNOWN`); applies `-0.03` confidence impact per low-quality file |
| 2 | `VisionExtractionAgent` | For each document: tries fixture content → uploaded text → Groq Vision → `_empty_extraction` fallback in order; validates output with Pydantic; applies `-0.08` per extraction failure and `-0.02×n` per missing field; after all docs are processed, if any document has `quality == UNREADABLE`, sets `member_action_required` with code `UNREADABLE_DOCUMENT` |
| 3 | `StructuredNormalizationAgent` | Normalises field aliases (e.g. `patientName → patient_name`, `amount → total`), snake-cases keys, parses amounts, normalises line items |
| 4 | `PatientConsistencyAgent` | Compares `patient_name` across all documents; if >1 distinct name found, sets `member_action_required` with code `PATIENT_MISMATCH` and applies `-0.25` confidence impact |

**Output — `ExtractionPipelineResult`**

| Field | Type | Notes |
|---|---|---|
| `submission` | `ClaimSubmission` | Submission with extracted fields merged into `document.content` |
| `extracted_documents` | `ExtractedDocumentData[]` | One entry per input document |
| `trace` | `TraceEvent[]` | One event per node |
| `component_failures` | `ComponentFailure[]` | Recoverable failures (e.g. Groq timeouts) |
| `member_action_required` | `MemberActionRequired \| null` | Set if patient names are inconsistent (`PATIENT_MISMATCH`) or if any extracted document is unreadable (`UNREADABLE_DOCUMENT`) |
| `confidence_impact` | `float` | Cumulative negative impact on confidence score |

**`ExtractedDocumentData` fields**

| Field | Type |
|---|---|
| `file_id` | `string` |
| `document_type` | `DocumentType` |
| `quality` | `DocumentQuality` — derived from confidence + missing fields |
| `fields` | `dict[str, Any]` — normalised key-value pairs |
| `missing_fields` | `string[]` — required fields absent after extraction |
| `confidence` | `float [0,1]` |
| `warnings` | `string[]` |

**`quality` derivation rule (`_quality_from_confidence`)**

| Condition | Quality |
|---|---|
| `confidence >= 0.8` and no missing fields | `GOOD` |
| `confidence >= 0.5` | `LOW` |
| `confidence < 0.5` | `UNREADABLE` |
| Upload content present but all extraction attempts failed | `UNREADABLE` |
| No upload content (fixture document, no binary payload) | `LOW` |

**Required fields by document type**

| Document Type | Required Fields |
|---|---|
| `PRESCRIPTION` | `patient_name`, `diagnosis` |
| `HOSPITAL_BILL` | `patient_name`, `total` |
| `PHARMACY_BILL` | `patient_name`, `total` |
| `LAB_REPORT` | `patient_name`, `test_name` |
| `DIAGNOSTIC_REPORT` | `patient_name`, `test_name` |
| `DISCHARGE_SUMMARY` | `patient_name`, `diagnosis` |
| `DENTAL_REPORT` | `patient_name`, `diagnosis` |

**Errors** — None raised to the caller. All Groq API failures and Pydantic validation errors are caught and recorded as `ComponentFailure` entries with `recoverable=True`.

---

### `PolicyRetriever` — `retrieve_policy_evidence`

**Module:** `app.services.policy_retriever`

Returns ranked policy knowledge chunks relevant to a given claim. Uses hybrid retrieval (dense vector + Postgres full-text search combined via Reciprocal Rank Fusion). Falls back to in-memory retrieval if the database is unavailable.

**Input**

| Parameter | Type | Default | Notes |
|---|---|---|---|
| `submission` | `ClaimSubmission` | — | Used to build the retrieval query |
| `policy` | `PolicyTerms` | — | Used for in-memory fallback |
| `limit` | `int` | `5` | Maximum number of chunks to return |

**Query construction** — Built from `claim_category`, `member_id`, `hospital_name`, and `claimed_amount` fields of the submission.

**Retrieval strategy**

1. Dense vector search using 64-dimensional SHA256-derived embeddings stored in pgvector (`halfvec` type).
2. Lexical search using Postgres full-text search on the `text` column.
3. Scores combined using Reciprocal Rank Fusion: `score(id) = Σ 1/(k + rank)` where `k=60`.
4. Results filtered to the active `policy_id` and optionally the `claim_category`.

**Output** — `PolicyEvidence[]`

| Field | Type |
|---|---|
| `evidence_id` | `string` |
| `source` | `string` — `policy_terms.json` or `sample_documents_guide.md` |
| `source_path` | `string \| null` — JSON path or markdown section |
| `rule_category` | `string` — e.g. `waiting_periods`, `exclusions`, `opd_categories` |
| `claim_category` | `ClaimCategory \| null` |
| `text` | `string` |
| `dense_score` | `float \| null` |
| `lexical_score` | `float \| null` |
| `rrf_score` | `float \| null` |

**Errors** — None raised to caller. `SQLAlchemyError` from the database triggers automatic fallback to in-memory retrieval.

---

### `PolicyKnowledgeIndexer` — `index_policy_knowledge`

**Module:** `app.services.policy_retriever`

Builds the knowledge base from `policy_terms.json` and `sample_documents_guide.md`, then persists it to the `policy_knowledge_chunks` table in Postgres.

**Input**

| Parameter | Type | Notes |
|---|---|---|
| `db` | `sqlalchemy.orm.Session` | Active database session |
| `policy` | `PolicyTerms` | Loaded and validated policy terms |
| `guide_path` | `Path` | Path to `sample_documents_guide.md` (default: repo root) |

**Chunk sources**

| Source | Rule Categories |
|---|---|
| `policy_terms.json` | `document_requirements`, `opd_categories`, `coverage`, `exclusions`, `waiting_periods`, `pre_authorization`, `fraud_thresholds`, `network_hospitals`, `members`, `submission_rules` |
| `sample_documents_guide.md` | `document_formats` (one chunk per markdown section) |

**Output** — `KnowledgeChunk[]` (side effect: rows written to `policy_knowledge_chunks` table)

**Errors**

| Error | Condition |
|---|---|
| `SQLAlchemyError` | Database write failure; raised to caller for rollback handling |

---

### `ClaimsProcessor` — `process_claim`

**Module:** `app.services.claims_processor`

The core adjudication engine. Runs all policy rule checks against the extracted claim data and produces a final decision. Always returns a `ClaimResponse` — never raises.

**Input**

| Parameter | Type | Notes |
|---|---|---|
| `submission` | `ClaimSubmission` | Fully populated claim submission |
| `policy` | `PolicyTerms \| None` | Active policy; loaded from file if not passed |

**Processing order**

| Step | Check | Early Exit |
|---|---|---|
| 1 | Policy ID match | REJECTED if mismatch |
| 2 | Document validation — required docs present | ACTION_REQUIRED if wrong doc type or unreadable |
| 3 | Extraction pipeline | ACTION_REQUIRED if patient mismatch |
| 4 | Member exists in policy | REJECTED if not found |
| 5 | Policy active dates | REJECTED if outside active window |
| 6 | Submission deadline (30 days) | REJECTED if past deadline |
| 7 | Minimum claim amount | REJECTED if below minimum |
| 8 | Category enabled | REJECTED if category not covered |
| 9 | Waiting period — initial (90 days from join) | REJECTED if within period |
| 10 | Waiting period — specific conditions | REJECTED if condition under waiting period |
| 11 | Waiting period — pre-existing (48 months) | REJECTED if pre-existing diagnosis |
| 12 | Exclusions — condition-based | REJECTED if diagnosis matches exclusion |
| 13 | Exclusions — category-specific | REJECTED if category exclusion applies |
| 14 | Pre-authorisation required | REJECTED if pre-auth needed and absent |
| 15 | Network hospital check | Co-pay/discount adjusted; trace note added |
| 16 | Fraud signals — same-day claim count | MANUAL_REVIEW if ≥ threshold (default: 3) |
| 17 | Fraud signals — monthly claim limit | MANUAL_REVIEW if ≥ threshold |
| 18 | Fraud signals — high-value threshold | MANUAL_REVIEW if above threshold |
| 19 | Per-claim OPD limit | REJECTED or amount capped |
| 20 | Annual OPD limit | REJECTED or amount capped |
| 21 | Family floater limit | Amount capped if applicable |
| 22 | Co-pay calculation | Approved amount reduced by copay% |
| 23 | Network discount | Approved amount reduced before copay |
| 24 | Line-item decisions (dental/vision) | Partial approval per covered/excluded items |

**Output — `ClaimResponse`** (see API section above for full field definitions)

**Decision rules**

| Decision | Condition |
|---|---|
| `REJECTED` | Any non-recoverable rule check fails |
| `MANUAL_REVIEW` | Fraud signals triggered; no rule hard-fails |
| `PARTIAL` | Some line items approved, others rejected |
| `APPROVED` | All rule checks pass; full or co-pay-adjusted amount |
| `ACTION_REQUIRED` | Document validation fails before adjudication |

**Confidence scoring**

Base confidence starts at `0.85` and is adjusted by:
- `-0.08` per Groq extraction failure
- `-0.03` per low-quality document
- `-0.02` to `-0.12` per failed/uncertain rule check
- `-0.25` for patient name mismatch

**Errors** — None raised. `PolicyLoadError` is caught and returned as a REJECTED response with a `component_failures` entry.

---

### `EvalRunner` — `run_eval_cases`

**Module:** `app.services.claims_processor`

Loads all test cases from `test_cases.json` and runs each through `process_claim`, comparing the result to the expected outcome.

**Input** — None (reads `test_cases.json` from the repo root at import time).

**Output — `EvalRun`**

| Field | Type |
|---|---|
| `eval_run_id` | `string` |
| `status` | `ClaimStatus` — `COMPLETED` on success |
| `started_at` | `datetime` |
| `completed_at` | `datetime` |
| `metrics` | `EvalMetrics` |
| `cases` | `EvalCaseResult[]` |

**`EvalCaseResult` fields**

| Field | Type |
|---|---|
| `case_id` | `string` |
| `case_name` | `string` |
| `passed` | `boolean` |
| `expected` | `dict` — expected decision, approved amount, early_stop flag |
| `actual` | `ClaimResponse` |
| `notes` | `string[]` — mismatch explanations |

**Pass criteria**

A case passes when all of the following match:
1. `decision` matches expected (or `status == ACTION_REQUIRED` for early-stop cases)
2. `approved_amount` matches expected (exact, within ±0.01 tolerance)
3. Early-stop flag matches expected

**Errors**

| Error | Condition |
|---|---|
| `FileNotFoundError` | `test_cases.json` missing from repo root |
| `JSONDecodeError` | `test_cases.json` is malformed |

---

### `ClaimIntakeRepository` — `persist_claim_intake`

**Module:** `app.services.claim_intake_repository`

Persists a completed `ClaimResponse` to the `claim_intakes` and `uploaded_documents` tables. Gracefully no-ops if the database is unavailable or the environment is `local`/`test`.

**Input**

| Parameter | Type |
|---|---|
| `response` | `ClaimResponse` |

**Output** — `ClaimResponse` (the same object, possibly with a `ComponentFailure` appended if persistence failed in a non-local environment)

**Database tables written**

| Table | Content |
|---|---|
| `claim_intakes` | Member ID, policy ID, category, dates, amounts, status, decision, rejection reasons, trace, failures |
| `uploaded_documents` | Per-document classification, quality, sha256, storage URI, validation status |

**Errors** — None raised. `SQLAlchemyError` is:
- Silently swallowed in `local`/`test` environments
- Appended as a `ComponentFailure` entry in production

---

### `PolicyLoader` — `read_policy_terms` / `load_policy_terms`

**Module:** `app.services.policy_loader`

Reads, validates, and optionally persists the policy configuration from `policy_terms.json`.

#### `read_policy_terms(path)`

Reads and validates the policy file only; no database interaction.

**Input**

| Parameter | Type | Default |
|---|---|---|
| `path` | `pathlib.Path` | `<repo_root>/policy_terms.json` |

**Output** — `PolicyTerms`

**Errors**

| Error | Condition |
|---|---|
| `PolicyLoadError` | File not found at `path` |
| `PolicyLoadError` | File content fails Pydantic validation |

#### `load_policy_terms(path)`

Reads the policy, persists it to Postgres, and indexes it in pgvector. Used for explicit reload.

**Input** — Same as `read_policy_terms`.

**Output** — `PolicyTerms`

**Errors**

| Error | Condition |
|---|---|
| `PolicyLoadError` | File not found or validation failure |
| `PolicyLoadError` | `DATABASE_URL` not configured |
| `PolicyLoadError` | Database write failure (wraps `SQLAlchemyError`) |

#### `load_policy_terms_on_startup()`

Called at application startup. In `local`/`test` environments, database failures are logged as warnings and the in-memory policy is returned without raising. In other environments, raises `PolicyLoadError` on database failure.

**Input** — None (uses default path).

**Output** — `PolicyTerms`

**Errors**

| Error | Condition |
|---|---|
| `PolicyLoadError` | File not found or validation failure (all environments) |
| `PolicyLoadError` | Database failure in non-local environments |

---

## Data Type Reference

### Enums

| Enum | Values |
|---|---|
| `ClaimCategory` | `CONSULTATION`, `DIAGNOSTIC`, `PHARMACY`, `DENTAL`, `VISION`, `ALTERNATIVE_MEDICINE` |
| `DocumentType` | `PRESCRIPTION`, `HOSPITAL_BILL`, `LAB_REPORT`, `DIAGNOSTIC_REPORT`, `PHARMACY_BILL`, `DISCHARGE_SUMMARY`, `DENTAL_REPORT`, `UNKNOWN` |
| `DocumentQuality` | `GOOD`, `LOW`, `UNREADABLE`, `UNKNOWN` |
| `ClaimStatus` | `RECEIVED`, `PROCESSING`, `ACTION_REQUIRED`, `COMPLETED`, `FAILED` |
| `ClaimDecisionType` | `APPROVED`, `PARTIAL`, `REJECTED`, `MANUAL_REVIEW` |
| `LineItemDecisionType` | `APPROVED`, `REJECTED`, `ADJUSTED`, `REVIEW` |
| `TraceLevel` | `INFO`, `WARNING`, `ERROR` |

### `MemberActionRequired`

| Field | Type |
|---|---|
| `code` | `string` — `MISSING_REQUIRED_DOCUMENT` (wrong/missing doc type gate), `UNREADABLE_DOCUMENT` (pre-extraction quality gate **or** post-extraction failure on uploaded binary), `PATIENT_MISMATCH` (extraction pipeline consistency check) |
| `message` | `string` — specific, actionable instruction |
| `affected_file_ids` | `string[]` |
| `required_document_types` | `DocumentType[]` |

### `ComponentFailure`

| Field | Type |
|---|---|
| `component` | `string` |
| `message` | `string` |
| `recoverable` | `boolean` (default: `true`) |

### `TraceEvent`

| Field | Type |
|---|---|
| `timestamp` | `ISO 8601 datetime (UTC)` |
| `component` | `string` |
| `level` | `TraceLevel` |
| `message` | `string` |
| `input_summary` | `dict` |
| `output_summary` | `dict` |
| `checks_performed` | `string[]` |
| `evidence_ids` | `string[]` |
| `confidence_impact` | `float` |
| `warnings` | `string[]` |
| `errors` | `string[]` |

### `LineItemDecision`

| Field | Type | Constraint |
|---|---|---|
| `description` | `string` | |
| `claimed_amount` | `float >= 0` | |
| `approved_amount` | `float >= 0` | Must not exceed `claimed_amount` |
| `decision` | `LineItemDecisionType` | |
| `reason` | `string` | |
