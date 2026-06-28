# Plum Health Insurance Claims Processing System

An automated, explainable AI system for adjudicating employee health insurance claims — built for Plum's AI Engineer assignment.

---

## What It Does

Accepts a claim submission (member details, treatment type, claimed amount, uploaded documents), validates documents against policy requirements, extracts structured information, applies 35+ deterministic policy rules, and returns a final decision (`APPROVED`, `PARTIAL`, `REJECTED`, `MANUAL_REVIEW`) with a complete audit trace.

---

## Repository Structure

```
.
├── assignment.md              # Assignment specification
├── policy_terms.json          # Policy configuration, coverage rules, member roster
├── test_cases.json            # 12 test scenarios with expected outcomes
├── sample_documents_guide.md  # Indian medical document format reference
├── plan.md                    # Phase-wise implementation notes
├── backend/                   # FastAPI + LangGraph Python backend
├── frontend/                  # Next.js ops review UI
├── docs/
│   ├── architecture_design.md # Full architecture design (Eraser.io-ready)
│   ├── component_contracts.md # Typed contracts for every component
│   └── eval_report.md         # Results for all 12 test cases
└── data/                      # Symlinks to policy and test data
```

---

## System Architecture

### High-Level Layers

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

### End-to-End Data Flow

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

## Document Extraction Pipeline (LangGraph)

A stateful 4-agent pipeline orchestrated with LangGraph. Each agent has typed input/output edges and a defined failure fallback.

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

**Fast-path:** If documents were already extracted at parse time and content hasn't changed, the pipeline skips Agent 2 and reuses cached extraction results.

---

## Claims Adjudication Rules Engine

35+ deterministic Python rules applied in strict order. No LLM is involved in adjudication — full auditability is guaranteed.

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

## Policy Retrieval (Hybrid Search)

Policy evidence is retrieved using a hybrid search engine combining dense vector search and lexical keyword matching, fused with Reciprocal Rank Fusion (RRF).

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

**Indexed knowledge chunks:** `coverage_limits`, `opd_category`, `waiting_periods`, `exclusions`, `pre_authorization`, `submission_rules`, `fraud_thresholds`, `network_hospitals`

---

## Technology Stack

### Frontend

| Layer | Technology |
|---|---|
| Framework | Next.js 15 (App Router) |
| UI | React 19 + TypeScript 5.5 |
| State | React hooks (no Redux/Zustand) |
| API state | TanStack React Query |
| Styling | Tailwind CSS 3.4 + PostCSS |
| Icons | Lucide React |
| Runtime | Node.js 18+ |

### Backend

| Layer | Technology |
|---|---|
| API server | FastAPI + Uvicorn (Python 3.11+) |
| Validation | Pydantic v2 + Pydantic Settings |
| Agent orchestration | LangGraph |
| LLM framework | LangChain |
| LLM provider | Groq SDK (Llama 4 Scout) |
| ORM | SQLAlchemy 2.0 |
| Migrations | Alembic |
| DB driver | psycopg3 |
| Vector search | pgvector |
| PDF parsing | pypdf |
| File upload | python-multipart |
| Testing | pytest + httpx |
| Linting | ruff |

### External Services

| Service | Purpose | Fallback |
|---|---|---|
| Groq Cloud (Llama 4 Scout) | Vision extraction + doc classification | Deterministic filename inference |
| Neon.tech PostgreSQL + pgvector | Claim storage + vector search | In-memory mode |

---

## Key Design Decisions

| Decision | Choice | Reason |
|---|---|---|
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

---

## Error Handling & Resilience

| Layer | Trigger | Behavior |
|---|---|---|
| LLM Unavailable | No `GROQ_API_KEY` or Groq API down | Falls back to deterministic extraction from text content |
| Database Unavailable | `DATABASE_URL` not set or DB unreachable | In-memory operation; policy loaded from JSON |
| Low Quality Document | Doc marked `UNREADABLE` or `LOW` | Returns `ACTION_REQUIRED`; prompts user to re-upload |
| Name Mismatch | Patient name doesn't match any policy member | Returns `ACTION_REQUIRED`; asks user to confirm member |
| Component Failure | Any service throws unexpected exception | `ComponentFailure` recorded; confidence reduced; `MANUAL_REVIEW` if too many |

---

## Local Setup

### Prerequisites

- Python 3.11+
- Node.js 18+
- A Postgres database with the `pgvector` extension enabled (see [Neon](https://neon.tech) for a free hosted option)
- A [Groq API key](https://console.groq.com) for document classification and field extraction (optional — the system falls back to filename inference and fixture data without it)

---

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
```

Copy the environment file and fill in your values:

```bash
cp .env.example .env
```

**Backend environment variables (`.env`)**

| Variable | Required | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | yes* | `postgresql+psycopg://postgres:postgres@localhost:5432/plum_claims` | Postgres connection string with `pgvector` extension. Use `postgresql+psycopg://` scheme (psycopg v3). |
| `GROQ_API_KEY` | no | `""` | Groq API key for Llama-4-Scout vision extraction and document classification. Without this, the system uses filename inference and fixture content only. |
| `ENVIRONMENT` | no | `local` | Set to `local` or `test` to suppress database errors on startup. Set to `production` for strict mode. |
| `CORS_ORIGINS` | no | `http://localhost:3000` | Comma-separated list of allowed CORS origins. |
| `APP_NAME` | no | `Plum Claims API` | Application name shown in OpenAPI docs. |

\* If `DATABASE_URL` is empty and `ENVIRONMENT` is `local`, the backend starts without a database — policy evidence retrieval falls back to in-memory mode and claim persistence is skipped.

Run database migrations:

```bash
alembic upgrade head
```

Start the API server:

```bash
uvicorn app.main:app --reload
```

Verify the backend is running:

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

Interactive API docs: [http://localhost:8000/docs](http://localhost:8000/docs)

---

### Frontend

```bash
cd frontend
npm install
cp .env.example .env.local
```

**Frontend environment variables (`.env.local`)**

| Variable | Required | Default | Description |
|---|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | yes | `http://localhost:8000` | Base URL of the FastAPI backend. Change this when pointing at a deployed backend. |

Start the dev server:

```bash
npm run dev
```

Frontend: [http://localhost:3000](http://localhost:3000)

---

### Running Tests

```bash
cd backend
pytest
```

To run a specific test file:

```bash
pytest tests/test_claims_contract.py -v
```

The test suite runs in-memory (no database required). The `ENVIRONMENT=test` default in `pytest.ini` / `pyproject.toml` suppresses database connection errors.

---

### Running the Eval Suite

With the backend running locally, trigger the eval from the UI (Eval tab) or directly:

```bash
curl -X POST http://localhost:8000/eval/run | python -m json.tool
```

All 12 test cases are run and results are returned in a single response. See `docs/eval_report.md` for the pre-run results.

---

## Deployment

The system is designed to deploy on:

| Layer | Target |
|---|---|
| Backend | [Render](https://render.com) web service — `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| Frontend | Render static site or web service — `npm run build && npm start` |
| Database | [Neon](https://neon.tech) Postgres with `pgvector` extension enabled |
| LLM | [Groq](https://console.groq.com) API — `meta-llama/llama-4-scout-17b-16e-instruct` |

Set the same environment variables listed above in your Render service dashboard. Set `ENVIRONMENT=production` in deployed environments.

---

## Quick API Reference

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Health check |
| `GET` | `/claims/context` | Policy metadata + member roster |
| `GET` | `/claims/members/{member_id}/ytd` | YTD used/remaining amounts per category |
| `POST` | `/claims/submit` | Submit a claim as JSON |
| `POST` | `/claims/submit/upload` | Submit a claim with real file uploads |
| `POST` | `/claims/parse/upload` | Extract document fields only (no adjudication) |
| `GET` | `/claims/{claim_id}` | Fetch a claim response and full trace |
| `POST` | `/eval/run` | Run all 12 test cases and return metrics |
| `GET` | `/eval/latest` | Fetch the last eval run |

---

## Key Documents

- **`docs/architecture_design.md`** — Full architecture design with all diagrams, ready for Eraser.io visual presentation.
- **`docs/component_contracts.md`** — Typed input/output/error contracts for every component. Start here to understand or reimplement any part of the system.
- **`docs/eval_report.md`** — Decision accuracy on all 12 test cases with full traces.
