# Plum Claims Processing System — Architecture Design Document
*For visual presentation in Eraser.io*

---

## 1. SYSTEM OVERVIEW

**Project:** Plum Health Insurance Claims Processing System
**Type:** Full-stack AI-powered claims adjudication platform
**Purpose:** Automated, explainable, deterministic adjudication of employee health insurance claims with full audit trails

---

## 2. HIGH-LEVEL ARCHITECTURE DIAGRAM

### Layers (top → bottom)

```
┌─────────────────────────────────────────────────────┐
│                   PRESENTATION LAYER                │
│              Next.js 15 + React 19 + TypeScript     │
│         Submit Tab │ Decision Tab │ Eval Tab         │
└──────────────────────────┬──────────────────────────┘
                           │ REST API (HTTP/JSON)
┌──────────────────────────▼──────────────────────────┐
│                    API GATEWAY LAYER                │
│              FastAPI (Python 3.11+)                 │
│     /claims  │  /eval  │  /health  (CORS enabled)  │
└──────────────────────────┬──────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────┐
│                   SERVICES LAYER                    │
│  Document Intake  │  Extraction Pipeline            │
│  Policy Loader    │  Policy Retriever               │
│  Claims Processor │  Claim Intake Repository        │
└──────────────────────────┬──────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────┐
│                   DATA LAYER                        │
│   PostgreSQL + pgvector │  In-Memory (local mode)   │
│   13 Tables + Vector Embeddings (64-dim)            │
└──────────────────────────┬──────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────┐
│                  EXTERNAL SERVICES                  │
│          Groq API (Llama 4 Scout Vision)            │
└─────────────────────────────────────────────────────┘
```

---

## 3. COMPONENT DIAGRAM

### Frontend Components (Single-Page App)

```
page.tsx (2078 lines)
├── Navigation Bar
│   ├── Submit Tab ("submit")
│   ├── Decision Tab ("decision")
│   └── Eval Tab ("eval")
│
├── Submit Tab
│   ├── Document Upload Section
│   │   ├── Drag-Drop Zone
│   │   ├── File Browser
│   │   └── Document Type Selector
│   ├── Document List (uploaded docs)
│   │   └── Per Doc: type, quality, confidence
│   └── Claim Form Section
│       ├── Patient Name (matched from policy)
│       ├── Claim Category Selector
│       ├── Claimed Amount
│       ├── Treatment Date
│       ├── Provider Name
│       └── YTD Claims Display (per member)
│
├── Decision Tab
│   ├── Decision Banner (APPROVED / PARTIAL / REJECTED / MANUAL_REVIEW)
│   ├── Amount Summary (approved vs claimed)
│   ├── Rejection Reasons List
│   ├── Line Items Breakdown
│   ├── Policy Evidence Citations
│   ├── Audit Trace Log
│   │   └── Per Step: timestamp, component, checks, evidence IDs
│   ├── Member Action Required Panel
│   └── Component Failure Alerts
│
└── Eval Tab
    ├── Run Eval Button
    ├── Overall Metrics Summary
    │   ├── Accuracy
    │   ├── Early-Stop Accuracy
    │   ├── Amount Match Rate
    │   └── Rejection Reason Precision/Recall
    └── Per Test Case Results Table
        └── Per Case: expected vs actual, pass/fail
```

---

## 4. BACKEND SERVICE ARCHITECTURE

### Service Interaction Flow

```
Claims API Endpoint (/claims/submit)
         │
         ▼
   document_intake.py
   ┌────────────────────────────────┐
   │  submission_from_upload_form() │
   │  - Read uploaded files         │
   │  - SHA256 hash computation     │
   │  - Base64 encode content       │
   │  - (Optional) Groq vision      │
   │    classification              │
   └───────────────┬────────────────┘
                   │
                   ▼
         claims_processor.py
   ┌─────────────────────────────────────┐
   │  process_claim(submission, policy)  │
   │                                     │
   │  [35+ Deterministic Rules Applied]  │
   │                                     │
   │  Step 1: Policy Mismatch Check      │
   │  Step 2: Document Validation        │
   │  Step 3: ──► extraction_pipeline.py │
   │  Step 4: Member Validation          │
   │  Step 5: Policy Validity Dates      │
   │  Step 6: Submission Rules           │
   │  Step 7: Category Coverage Check    │
   │  Step 8: Exclusion Rules            │
   │  Step 9: Waiting Period Rules       │
   │  Step 10: Patient Name Consistency  │
   │  Step 11: Network Hospital Check    │
   │  Step 12: Coverage Limit Check      │
   │  Step 13: Co-pay Calculation        │
   │  Step 14: Pre-Auth Requirements     │
   │  Step 15: Fraud Detection           │
   │  Step 16: Line Item Adjudication    │
   │  Step 17: ──► policy_retriever.py   │
   │  Step 18: Confidence Scoring        │
   └───────────────┬─────────────────────┘
                   │
                   ▼
   claim_intake_repository.py
   ┌──────────────────────────────────┐
   │  persist_claim_intake(response)  │
   │  - Insert claim metadata         │
   │  - Insert per-document records   │
   │  - Graceful DB fallback          │
   └──────────────────────────────────┘
```

---

## 5. DOCUMENT EXTRACTION PIPELINE (LangGraph)

### Multi-Agent Pipeline (4 Agents)

```
Input: UploadedDocument list
         │
         ▼
┌─────────────────────────────────────┐
│    Agent 1: Document Verifier       │
│  - Classify document type           │
│  - Flag low/unknown quality docs    │
│  - Confidence impact: -0.03 (low)   │
│  Output: DocumentClassification     │
└──────────────────┬──────────────────┘
                   │
                   ▼
┌─────────────────────────────────────┐
│   Agent 2: Vision Extraction        │
│                                     │
│  Priority fallback chain:           │
│  1. Fixture content (test mode)     │
│  2. Uploaded text content           │
│  3. Groq Llama 4 Scout (Vision)     │
│     Model: llama-4-scout-17b        │
│     Max retries: 3                  │
│                                     │
│  Extracts per doc type:             │
│  - Prescription: patient, drugs,    │
│    diagnosis, prescriber            │
│  - Hospital Bill: hospital, total,  │
│    invoice_date, services           │
│  - Lab Report: tests, results       │
│  - Pharmacy: drugs, total           │
│  - Discharge Summary: admission,    │
│    discharge, diagnosis             │
└──────────────────┬──────────────────┘
                   │
                   ▼
┌─────────────────────────────────────┐
│  Agent 3: Structured Normalization  │
│  - Pydantic validation              │
│  - Normalize dates, amounts, names  │
│  - Handle missing fields            │
│  Output: ExtractedDocumentData      │
└──────────────────┬──────────────────┘
                   │
                   ▼
┌─────────────────────────────────────┐
│  Agent 4: Patient Consistency       │
│  - Match patient name to members    │
│  - Flag name mismatches             │
│  - Set action_required if mismatch  │
│  Output: ExtractionPipelineResult   │
└──────────────────┬──────────────────┘
                   │
                   ▼
         claims_processor.py (continues)
```

---

## 6. POLICY RETRIEVAL SYSTEM (Hybrid Search)

### Hybrid Search Architecture

```
Input: ClaimSubmission + ClaimCategory
              │
              ▼
    ┌──────────────────────┐
    │  Query Construction  │
    │  claim_category +    │
    │  submission summary  │
    └──────┬───────────────┘
           │
    ┌──────▼───────────────────────────────────────┐
    │            Hybrid Search Engine              │
    │                                              │
    │  ┌─────────────────┐  ┌──────────────────┐  │
    │  │  Dense Search   │  │  Lexical Search   │  │
    │  │  (pgvector)     │  │  (keyword match)  │  │
    │  │  64-dim embed   │  │                   │  │
    │  │  (SHA256-based, │  │  Token overlap    │  │
    │  │   deterministic)│  │  scoring          │  │
    │  └────────┬────────┘  └────────┬──────────┘  │
    │           │                    │              │
    │           └────────┬───────────┘              │
    │                    ▼                          │
    │     Reciprocal Rank Fusion (RRF)              │
    │     score = Σ 1/(k + rank)  [k=60]            │
    │     Returns top-5 evidence chunks             │
    └────────────────────┬─────────────────────────┘
                         │
                         ▼
              PolicyEvidence list
              (with hybrid scores, raw text, citations)
```

### Policy Knowledge Chunks (Indexed)
- `coverage_limits` — Sum insured, OPD limit, per-claim limit
- `opd_category` — Sub-limits and co-pays per category
- `waiting_periods` — Initial, pre-existing, specific condition waits
- `exclusions` — Excluded conditions, dental, vision
- `pre_authorization` — Pre-auth requirements and validity
- `submission_rules` — Deadlines, minimum amounts, currency
- `fraud_thresholds` — High-value, same-day, monthly limits
- `network_hospitals` — Eligible network facilities

---

## 7. DATA FLOW DIAGRAM (End-to-End)

```
USER (Browser)
     │
     │  1. Upload Documents (multipart form)
     ▼
 FRONTEND (Next.js)
     │
     │  POST /claims/parse/upload
     ▼
 FastAPI
     │
     ├──► document_intake.py (classify + encode files)
     ├──► extraction_pipeline.py (LangGraph, 4 agents)
     │         └──► Groq Vision API (optional)
     │
     │  DocumentParseResult (fields + confidence)
     ▼
 FRONTEND
     │  (auto-fill form fields from parse result)
     │
     │  2. Submit Claim (JSON)
     │  POST /claims/submit
     ▼
 FastAPI
     │
     ├──► claims_processor.py
     │         ├──► extraction_pipeline.py (re-extract if needed)
     │         ├──► policy_retriever.py (get evidence)
     │         └──► 35+ rule checks
     │
     ├──► claim_intake_repository.py (persist to DB)
     │
     │  ClaimResponse (decision + trace + evidence)
     ▼
 FRONTEND
     │  (display decision, trace, evidence, line items)
     ▼
 USER (sees APPROVED / PARTIAL / REJECTED / MANUAL_REVIEW)
```

---

## 8. DATABASE SCHEMA DIAGRAM

### Tables and Relationships

```
policies (1)
  │
  ├──────────────────── members (N)
  │                     policy_id (FK)
  │
  ├──────────────────── coverage_limits (1)
  │                     policy_id (FK)
  │
  ├──────────────────── document_requirements (N)
  │                     policy_id (FK), claim_category
  │
  ├──────────────────── opd_categories (N)
  │                     policy_id (FK), category_name
  │
  ├──────────────────── exclusions (N)
  │                     policy_id (FK), type
  │
  ├──────────────────── waiting_periods (N)
  │                     policy_id (FK), type
  │
  ├──────────────────── pre_authorization_rules (N)
  │                     policy_id (FK)
  │
  ├──────────────────── fraud_thresholds (1)
  │                     policy_id (FK)
  │
  ├──────────────────── network_hospitals (N)
  │                     policy_id (FK)
  │
  └──────────────────── policy_knowledge_chunks (N)
                        policy_id (FK)
                        embedding: vector(64) [pgvector]

claim_intakes (1)
  │
  └──────────────────── uploaded_documents (N)
                        claim_id (FK)
```

### Key Table Fields

| Table | Key Fields |
|-------|-----------|
| `policies` | id, policy_id, policy_name, insurer, raw_policy (JSONB) |
| `members` | id, member_id, name, relationship, dob, sum_insured |
| `coverage_limits` | sum_insured, opd_limit, per_claim_limit, is_family_floater |
| `policy_knowledge_chunks` | chunk_id, category, raw_text, embedding (vector 64) |
| `claim_intakes` | claim_id, status, decision, approved_amount, claimed_amount |
| `uploaded_documents` | document_id, claim_id, document_type, quality, confidence |

---

## 9. TECHNOLOGY STACK DIAGRAM

### Frontend Stack

```
┌──────────────────────────────────────┐
│           User Interface             │
│         (Browser / Web App)          │
├──────────────────────────────────────┤
│     Next.js 15 (App Router)          │
│     React 19 + TypeScript 5.5        │
├──────────────────────────────────────┤
│  TanStack React Query (API state)    │
│  Lucide React (icons)                │
├──────────────────────────────────────┤
│  Tailwind CSS 3.4 (styling)          │
│  PostCSS (transforms)                │
├──────────────────────────────────────┤
│        Node.js 18+ (runtime)         │
└──────────────────────────────────────┘
```

### Backend Stack

```
┌──────────────────────────────────────┐
│         FastAPI + Uvicorn            │
│         (Python 3.11+ runtime)       │
├──────────────────────────────────────┤
│  Pydantic v2 (data validation)       │
│  Pydantic Settings (config)          │
├──────────────────────────────────────┤
│  LangGraph (agent orchestration)     │
│  LangChain (LLM framework)           │
│  Groq SDK (LLM provider)             │
├──────────────────────────────────────┤
│  SQLAlchemy 2.0 (ORM)                │
│  Alembic (migrations)                │
│  psycopg3 (PostgreSQL driver)        │
├──────────────────────────────────────┤
│  pgvector (vector search extension)  │
│  pypdf (PDF parsing)                 │
│  python-multipart (file upload)      │
├──────────────────────────────────────┤
│  pytest + httpx (testing)            │
│  ruff (linting)                      │
└──────────────────────────────────────┘
```

### External Integrations

```
┌──────────────────────────────────────┐
│           Groq Cloud API             │
│   Model: meta-llama/llama-4-scout    │
│   Use: Vision extraction + doc       │
│        classification                │
│   Optional (fallback: deterministic) │
├──────────────────────────────────────┤
│        Neon.tech PostgreSQL          │
│   + pgvector extension               │
│   Use: Claim storage + vector search │
│   Optional (fallback: in-memory)     │
└──────────────────────────────────────┘
```

---

## 10. CLAIMS ADJUDICATION RULES ENGINE

### Rule Execution Order (claims_processor.py)

```
Input: ClaimSubmission + PolicyTerms
         │
    ┌────▼────────────────────────────────────────────────┐
    │  GATE RULES (immediate REJECTED on fail)            │
    │  ├─ [R01] Policy ID mismatch                        │
    │  ├─ [R02] Member not found in policy                │
    │  ├─ [R03] Policy not active (date check)            │
    │  ├─ [R04] Submission deadline exceeded              │
    │  ├─ [R05] Amount below minimum threshold            │
    │  └─ [R06] Claim category not covered                │
    └────┬────────────────────────────────────────────────┘
         │
    ┌────▼────────────────────────────────────────────────┐
    │  DOCUMENT RULES (ACTION_REQUIRED on fail)           │
    │  ├─ [D01] Required documents missing                │
    │  ├─ [D02] Document quality too low (UNREADABLE)     │
    │  └─ [D03] Patient name inconsistency (vs policy)    │
    └────┬────────────────────────────────────────────────┘
         │
    ┌────▼────────────────────────────────────────────────┐
    │  COVERAGE RULES (REJECTED on fail)                  │
    │  ├─ [C01] Condition exclusion check                 │
    │  ├─ [C02] Dental exclusion check                    │
    │  ├─ [C03] Vision exclusion check                    │
    │  ├─ [C04] Initial waiting period                    │
    │  ├─ [C05] Pre-existing condition waiting period     │
    │  └─ [C06] Specific condition waiting period         │
    └────┬────────────────────────────────────────────────┘
         │
    ┌────▼────────────────────────────────────────────────┐
    │  FINANCIAL RULES (PARTIAL on constraint hit)        │
    │  ├─ [F01] Per-claim limit cap                       │
    │  ├─ [F02] Annual OPD limit check                    │
    │  ├─ [F03] Family floater limit check                │
    │  ├─ [F04] Co-pay deduction (per category %)         │
    │  └─ [F05] Sub-limit per OPD category                │
    └────┬────────────────────────────────────────────────┘
         │
    ┌────▼────────────────────────────────────────────────┐
    │  COMPLIANCE RULES                                   │
    │  ├─ [X01] Pre-authorization required check          │
    │  ├─ [X02] Network hospital validation               │
    │  └─ [X03] MANUAL_REVIEW if pre-auth not confirmed   │
    └────┬────────────────────────────────────────────────┘
         │
    ┌────▼────────────────────────────────────────────────┐
    │  FRAUD DETECTION                                    │
    │  ├─ [FR1] Same-day claims count threshold           │
    │  ├─ [FR2] Monthly claims count threshold            │
    │  ├─ [FR3] High-value claim threshold                │
    │  └─ [FR4] Composite fraud score → MANUAL_REVIEW     │
    └────┬────────────────────────────────────────────────┘
         │
    ┌────▼────────────────────────────────────────────────┐
    │  LINE ITEM ADJUDICATION (multi-service claims)      │
    │  └─ Per line: APPROVED / REJECTED / ADJUSTED /      │
    │               REVIEW                                │
    └────┬────────────────────────────────────────────────┘
         │
    ┌────▼────────────────────────────────────────────────┐
    │  CONFIDENCE SCORING (0.0 – 1.0)                     │
    │  Base: 0.9                                          │
    │  Deductions:                                        │
    │  - Low quality docs: -0.03 each                     │
    │  - Missing fields: -0.05 each                       │
    │  - Component failures: -0.1 each                    │
    │  - No policy evidence: -0.15                        │
    └────┬────────────────────────────────────────────────┘
         │
         ▼
   ClaimDecision
   ├── decision: APPROVED | PARTIAL | REJECTED | MANUAL_REVIEW
   ├── approved_amount: Float
   ├── claimed_amount: Float
   ├── confidence: 0.0–1.0
   ├── rejection_reasons: List[str]
   └── line_item_decisions: List[LineItemDecision]
```

---

## 11. API ENDPOINT MAP

```
FastAPI Application (port 8000)
│
├── GET  /health
│         └── Returns {"status": "ok"}
│
├── GET  /claims/context
│         └── Returns PolicyContext
│             (policy metadata + member roster)
│
├── GET  /claims/members/{member_id}/ytd
│         └── Query param: as_of_date (optional)
│         └── Returns MemberYtdSummary
│             (used/remaining amounts per category)
│
├── POST /claims/submit
│         └── Body: ClaimSubmission (JSON)
│         └── Returns ClaimResponse (full adjudication)
│
├── POST /claims/submit/upload
│         └── Body: multipart/form-data (files + fields)
│         └── Returns ClaimResponse (full adjudication)
│
├── POST /claims/parse/upload
│         └── Body: multipart/form-data (files)
│         └── Returns DocumentParseResult
│             (fields extracted, no adjudication)
│
├── GET  /claims/{claim_id}
│         └── Returns ClaimResponse (cached in memory)
│
├── POST /eval/run
│         └── Runs all 12 test cases
│         └── Returns EvalRun (metrics + per-case results)
│
└── GET  /eval/latest
          └── Returns cached latest EvalRun
```

---

## 12. DEPLOYMENT ARCHITECTURE

```
┌──────────────────────────────────────────────────────┐
│                  PRODUCTION ENVIRONMENT              │
│                                                      │
│  ┌──────────────────┐      ┌────────────────────┐   │
│  │  Render.com       │      │   Render.com        │   │
│  │  Frontend Service │      │   Backend Service   │   │
│  │  (Next.js)        │      │   (FastAPI)         │   │
│  │  Port: 3000       │─────▶│   Port: 8000        │   │
│  └──────────────────┘      └────────┬───────────┘   │
│                                      │               │
│                             ┌────────▼───────────┐   │
│                             │   Neon.tech         │   │
│                             │   PostgreSQL        │   │
│                             │   + pgvector ext.   │   │
│                             └────────────────────┘   │
│                                                      │
│                             ┌────────────────────┐   │
│                             │   Groq Cloud API    │   │
│                             │   (External)        │   │
│                             │   Llama 4 Scout     │   │
│                             └────────────────────┘   │
└──────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────┐
│                  LOCAL ENVIRONMENT                   │
│                                                      │
│  Frontend: http://localhost:3000  (npm run dev)       │
│  Backend:  http://localhost:8000  (uvicorn --reload)  │
│  Database: In-memory fallback (no DB required)       │
│  LLM:      Deterministic fallback (no Groq needed)   │
└──────────────────────────────────────────────────────┘
```

---

## 13. STATE MANAGEMENT DIAGRAM

### Frontend State (React Hooks)

```
App Component (page.tsx)
│
├── activeView: "submit" | "decision" | "eval"
│
├── Submit Tab State
│   ├── documents: DocumentDraft[]
│   ├── claimForm: ClaimDraft
│   │   ├── patient_name: string
│   │   ├── claim_category: ClaimCategory
│   │   ├── claimed_amount: number
│   │   ├── treatment_date: string
│   │   └── provider_name: string
│   ├── isUploading: boolean
│   ├── isSubmitting: boolean
│   └── parseResult: DocumentParseResult | null
│
├── Policy/Context State
│   ├── policyContext: PolicyContext | null
│   ├── selectedMemberId: string | null
│   └── ytdSummary: MemberYtdSummary | null
│
├── Decision Tab State
│   └── claimResponse: ClaimResponse | null
│
└── Eval Tab State
    ├── evalRun: EvalRun | null
    └── isRunningEval: boolean
```

### Backend State

```
Application Startup (lifespan)
└── app.state.policy_terms: PolicyTerms
    (loaded from policy_terms.json, indexed in DB)

Request Scope
└── _CLAIMS: Dict[str, ClaimResponse]
    (in-memory, cleared on restart)

Database (persistent)
└── PostgreSQL: all policy + claim data
    (optional, graceful in-memory fallback)
```

---

## 14. ERROR HANDLING & RESILIENCE

```
System Resilience Layers:

Layer 1: LLM Unavailable
  └── Groq API down / no GROQ_API_KEY
      → Falls back to deterministic extraction
      → Document fields extracted from text content
      → ComponentFailure logged (recoverable: true)

Layer 2: Database Unavailable
  └── DATABASE_URL not set / DB unreachable
      → In-memory operation mode
      → Policy loaded from JSON file
      → Claims stored in dict (lost on restart)
      → ComponentFailure logged (recoverable: true)

Layer 3: Document Quality
  └── Document marked UNREADABLE or LOW quality
      → MemberActionRequired returned
      → STATUS = ACTION_REQUIRED (not FAILED)
      → User prompted to upload better quality docs

Layer 4: Name Mismatch
  └── Patient name doesn't match any policy member
      → MemberActionRequired returned
      → User asked to confirm correct member

Layer 5: Component Failures
  └── Any service throws unexpected exception
      → ComponentFailure recorded with details
      → Confidence score reduced
      → Processing continues where possible
      → MANUAL_REVIEW decision if too many failures
```

---

## 15. ERASER DIAGRAM NOTES

### Recommended Diagram Types in Eraser

1. **System Context Diagram** (C4 Level 1)
   - Show: User → Frontend → Backend → DB → Groq
   - Use cloud/system shapes

2. **Container Diagram** (C4 Level 2)
   - Next.js SPA, FastAPI, PostgreSQL, Groq API
   - Show REST API and DB connections between them

3. **Component Diagram** (C4 Level 3 — Backend)
   - 6 service boxes in backend
   - Arrows showing call flow from API → processor → pipeline → DB

4. **Sequence Diagram (Claim Submission)**
   - User → Frontend → /parse/upload → extraction_pipeline → response
   - User → Frontend → /claims/submit → claims_processor → all services → ClaimResponse

5. **Entity Relationship Diagram (Database)**
   - 13 tables with FK relationships as shown in Section 8

6. **Flowchart (Rules Engine)**
   - 35+ rules as decision diamonds
   - Color code: red (REJECTED), yellow (ACTION_REQUIRED), green (APPROVED)

7. **LangGraph Pipeline Diagram**
   - 4 agent nodes with conditional edges
   - Show fast-path (skip extraction) vs full extraction path

### Color Coding Suggestion
- **Blue:** Frontend / UI components
- **Green:** Backend API layer
- **Orange:** Service layer (business logic)
- **Purple:** Data layer (DB + models)
- **Red:** External services (Groq, Neon)
- **Gray:** Decision outcomes

---

## 16. TRADE-OFFS, LIMITATIONS & SCALING

### What We Considered and Rejected

| Option Considered | What We Chose Instead | Why We Rejected It |
|---|---|---|
| **LLM-based adjudication** (GPT-4 / Claude decides approve/reject) | Deterministic Python rules engine | Claims decisions must be auditable and reproducible. An LLM might produce different results for the same input, and "the model said so" is not an acceptable explanation for a rejected claim. Deterministic rules give us a 1:1 mapping from input → decision with a full audit trail. |
| **OpenAI GPT-4V** for document extraction | Groq (Llama 4 Scout) | GPT-4V is slower (2-5s per call) and more expensive. Groq's inference speed (<500ms) matters when processing batches. Trade-off: Llama 4 Scout is less accurate on degraded handwritten docs, but the deterministic fallback catches extraction failures. |
| **Dedicated vector database** (Pinecone, Weaviate) | pgvector extension in PostgreSQL | Adding a separate vector DB increases infra complexity for a policy corpus of ~20 chunks. pgvector handles this trivially. At 10x scale with thousands of policy variants, we'd revisit this. |
| **Sentence-transformers embeddings** (all-MiniLM-L6-v2) | SHA256-based deterministic embeddings (default) | Real embeddings require PyTorch (~300-450 MB RAM). On Render's 512 MB free tier, this causes OOM at boot. SHA256 fallback preserves lexical search quality. Toggle: set `ENABLE_EMBEDDINGS=true` on >=1 GB instances. |
| **Multi-model ensemble** (run 2-3 LLMs, vote on extraction) | Single LLM + deterministic validation | Ensemble would triple latency and cost. Instead, we validate LLM output with Pydantic schemas and post-processing filters — cheaper, faster, and equally reliable for structured extraction. |
| **Celery / Redis task queue** for async processing | Synchronous FastAPI with `asyncio` | The current claim volume (75K/year ≈ 200/day) doesn't justify queue infrastructure. FastAPI's async handlers with Groq's fast inference keep P95 latency under 3 seconds. |
| **Microservices** (separate services for extraction, rules, fraud) | Monolith with modular service layer | At current scale, network overhead between microservices would exceed the compute time. The 5-module rule engine (`gate_rules`, `document_rules`, `coverage_rules`, `financial_rules`, `fraud_rules`) gives us clean separation without deployment complexity. |
| **React component library** (Shadcn, Radix) | Single-file Tailwind UI | For an internal ops tool with 3 tabs, a component library adds bundle size and learning curve with no proportional benefit. Trade-off: the 2,078-line `page.tsx` should be split into components if the UI grows. |
| **Authentication / RBAC** | None | This is an internal ops tool. Auth adds real complexity (token management, session handling, role checks) with no value for the assignment scope. First thing to add in production. |
| **OCR pre-processing** (Tesseract, Google Vision) | Direct LLM vision extraction | Modern vision LLMs handle OCR implicitly. A separate OCR step adds latency and another failure point. Trade-off: we lose fine-grained control over OCR confidence scores. |

### What We Consciously Cut

| What Was Cut | Why | Impact |
|---|---|---|
| **Real file upload processing** in test mode | Test cases provide structured `content` objects, not actual image files. Building a full OCR pipeline for test cases would be wasted effort. | Tests exercise extraction logic via fixture content; real uploads work via Groq Vision on the `/submit/upload` endpoint. |
| **Persistent claim history across restarts** (in-memory mode) | Without a database, claims are stored in a Python dict. This is acceptable for demo/local use. | Production deployments use PostgreSQL. The in-memory fallback exists so the system runs with zero configuration. |
| **Comprehensive fraud ML model** | A real fraud model needs historical data, feature engineering, and training. We implemented rule-based fraud detection (same-day count, monthly count, high-value threshold) which catches the patterns in the test cases. | Covers TC009 (same-day claims). A production system would add ML scoring based on claim history patterns. |
| **PDF/image quality scoring** | We check for `UNREADABLE` quality flags but don't compute image quality metrics (blur detection, resolution checks). | Depends on quality metadata in the submission. Production would add OpenCV-based quality assessment. |
| **Multi-language support** | All documents assumed to be in English. Indian medical documents often mix English with Hindi/regional languages. | Would need language detection and multilingual extraction prompts. |
| **Claim amendment workflow** | Once a claim is decided, there's no way to amend and resubmit. | Would need a state machine (DRAFT → SUBMITTED → DECIDED → AMENDED) and version history. |
| **WebSocket real-time updates** | Frontend polls for results after submission. | At current volume, polling is fine. WebSockets would matter for a dashboard showing live claim processing. |

### Current Limitations

1. **Single-threaded LLM calls**: Extraction processes documents sequentially. For claims with 5+ documents, this adds up.
2. **No claim deduplication**: The same claim can be submitted multiple times with different claim IDs.
3. **Static policy loading**: Policy terms are loaded at startup from JSON. No hot-reload if policy terms change mid-day.
4. **No partial extraction recovery**: If Groq fails on document 3 of 5, we lose all extraction for that document (the pipeline continues, but with missing data).
5. **Frontend is a single file**: The 2,078-line `page.tsx` works but violates separation of concerns. Would need component extraction for maintainability.
6. **No rate limiting**: The API has no request throttling. A bug in the frontend could hammer the Groq API.

### Scaling to 10x (750K claims/year ≈ 2,000/day)

| Bottleneck | Current State | At 10x |
|---|---|---|
| **LLM extraction** | Sequential, ~1-2s per doc | Parallel document extraction with asyncio.gather(); batch Groq calls; add extraction result cache (Redis) |
| **Rule engine** | In-process, <10ms | Still fine — pure Python, no I/O. 10x doesn't stress this. |
| **Database** | Single PostgreSQL instance | Read replicas for claim lookups; connection pooling (PgBouncer); partition claim_intakes by month |
| **Policy retrieval** | In-memory chunk index | Move to dedicated vector DB (Qdrant/Weaviate) if policy corpus grows to thousands of variants |
| **API throughput** | Single Uvicorn worker | Multiple Uvicorn workers behind a load balancer; horizontal scaling on Render/ECS |
| **Fraud detection** | Rule-based (threshold checks) | ML model trained on historical claim patterns; real-time feature store (Redis) |
| **File storage** | Base64 in memory / DB | S3/GCS for document storage; signed URLs for retrieval |
| **Observability** | Structured JSON logs | Distributed tracing (OpenTelemetry); metrics (Prometheus); alerting on decision confidence drops |
| **Frontend** | Single Next.js instance | CDN for static assets; split page.tsx into lazy-loaded components; add WebSocket for live updates |

---

## 17. KEY DESIGN DECISIONS

| Decision | Choice | Reason |
|----------|--------|--------|
| LLM Framework | LangGraph (not plain LangChain) | Stateful multi-agent pipeline with typed edges |
| LLM Provider | Groq (Llama 4 Scout) | Vision capability for medical doc images |
| Vector DB | pgvector (in PostgreSQL) | Avoid separate vector DB; reuse existing Postgres |
| Embeddings | Deterministic (SHA256-based) | No LLM API call needed for indexing; reproducible |
| Hybrid Search | Dense + Lexical + RRF | Better recall than pure semantic or keyword alone |
| DB Optional | In-memory fallback | Enables zero-config local development |
| LLM Optional | Deterministic fallback | System works without Groq API key for testing |
| Frontend | Single-page (no routing) | Simple 3-tab UX for ops team; no complex navigation |
| State | React hooks only | No Redux/Zustand needed for this scope |
| Auth | None | Internal ops tool; authentication deferred |
| Rules Engine | Deterministic Python (not LLM) | Full auditability; no LLM hallucination in decisions |
