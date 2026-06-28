# System Architecture

> Last updated to reflect the final implemented system.

---

## 1. System Overview

This is a full-stack, explainable AI system for adjudicating employee health insurance OPD claims. A claim is submitted with member details, treatment information, and supporting documents. The system validates the documents, extracts structured fields from them, applies 35+ deterministic policy rules loaded from `policy_terms.json`, and returns a final decision with a complete audit trace.

**Key design guarantee:** no LLM makes an approval or rejection decision. All adjudication is deterministic Python. LLMs are confined to OCR-style extraction and document classification.

---

## 2. Component Diagram

```
┌────────────────────────────────────────────────────────────┐
│                   PRESENTATION LAYER                       │
│  Next.js 15 · React 19 · TypeScript 5.5 · Tailwind CSS     │
│  ┌─────────────────┬──────────────────┬──────────────────┐ │
│  │  Claim Submit   │  Decision Review │  Eval Dashboard  │ │
│  └─────────────────┴──────────────────┴──────────────────┘ │
└──────────────────────────┬─────────────────────────────────┘
                           │ REST  HTTP/JSON
┌──────────────────────────▼─────────────────────────────────┐
│                    API GATEWAY LAYER                        │
│  FastAPI · Python 3.11+ · Uvicorn · python-multipart       │
│  Routes: /claims  /eval  /health                           │
└──────┬───────────────┬──────────────────┬──────────────────┘
       │               │                  │
┌──────▼──────┐ ┌──────▼──────┐  ┌───────▼───────────────────┐
│  document_  │ │ extraction_ │  │    claims_processor.py     │
│  intake.py  │ │ pipeline.py │  │  (35+ deterministic rules) │
└──────┬──────┘ └──────┬──────┘  └───────┬───────────────────┘
       │               │                  │
       │           ┌───▼──────────┐  ┌────▼─────────────┐
       │           │  Groq Cloud  │  │ policy_retriever  │
       │           │  Llama 4     │  │ .py (RAG + RRF)  │
       │           │  Scout API   │  └────┬─────────────┘
       │           └──────────────┘       │
       │                            ┌─────▼────────────────────┐
       │                            │      DATA LAYER           │
       └───────────────────────────►│  PostgreSQL + pgvector    │
                                    │  Neon.tech hosted         │
                                    │  13 tables · 64-dim vecs  │
                                    └──────────────────────────┘
```

---

## 3. End-to-End Data Flow

### Step 1 — Document Parse (upload flow only)

```
User uploads files → POST /claims/parse/upload
  ↓
document_intake.py
  • Reads each UploadFile (PDF / PNG / JPEG)
  • Calls Groq Vision per image to classify doc type + quality
  • Encodes content as base64 in UploadedDocument.content.upload
  ↓
extraction_pipeline.py  (LangGraph — see §5)
  • DocumentVerifierAgent  → classify, flag quality
  • VisionExtractionAgent  → extract fields (Groq or text fallback)
  • StructuredNormalizationAgent → normalize aliases, dates, amounts
  • PatientConsistencyAgent → cross-doc name check
  ↓
DocumentParseResult (fields + confidence + warnings)
  ↓
Frontend auto-fills claim form; user reviews + adjusts
```

### Step 2 — Claim Submission

```
User submits form → POST /claims/submit
  ↓
claims_processor.py
  ├─ Document validation (required types, UNREADABLE gate)
  ├─ Extraction pipeline (if pre-parsed fields not cached)
  ├─ Policy evidence retrieval (hybrid RAG, top-5 chunks)
  └─ 35+ ordered rule checks
       └─ Approved amount + confidence score
  ↓
claim_intake_repository.py → persists to PostgreSQL
  ↓
ClaimResponse (decision · trace · evidence · failures)
  ↓
Frontend Decision Review tab
```

---

## 4. Database Schema (13 Tables)

| Table | Purpose |
|---|---|
| `policy_terms` | Policy metadata (id, name, dates, company) |
| `policy_members` | Member roster with join dates and relationships |
| `coverage_limits` | Per-category sub-limits and co-pay percentages |
| `document_requirements` | Required doc types per claim category |
| `opd_categories` | OPD category config (covered, annual limit, per-claim) |
| `exclusions` | Excluded conditions, dental/vision procedures |
| `waiting_periods` | Initial, pre-existing, and specific condition windows |
| `pre_auth_requirements` | Pre-authorisation thresholds by category |
| `fraud_thresholds` | Same-day, monthly, and high-value limits |
| `network_hospitals` | Hospital names with discount percentages |
| `policy_knowledge_chunks` | Vector-indexed policy text chunks for RAG |
| `claim_intakes` | Persisted ClaimResponse records |
| `uploaded_documents` | Per-document classification, quality, sha256, URI |

---

## 5. LangGraph Extraction Pipeline

### Why LangGraph

LangGraph provides stateful, typed multi-agent execution with explicit edges between nodes. This means:
- Each agent reads from a typed `_ExtractionState` dict — no implicit shared mutable state.
- Failures in one agent are isolated; downstream agents still run with what's available.
- The pipeline can be inspected, replayed, or extended without rewriting routing logic.
- The graph compiles to a simple directed acyclic sequence for this use case, but the structure allows conditional edges (e.g. early exit) to be added without changing agent code.

Alternatives considered:
- **Plain sequential functions**: no state isolation, harder to extend.
- **LangChain Chains**: less control over per-step state typing and failure capture.
- **Celery / async tasks**: adds infrastructure overhead for a synchronous demo system.

### Pipeline Nodes

```
UploadedDocument list
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ 1. DocumentVerifierAgent                                    │
│    • Calls classify_document() per document                 │
│    • Fallback chain: fixture → quality gate → Groq Vision   │
│      → filename inference → declared type → UNKNOWN         │
│    • Flags LOW quality docs → −0.03 confidence impact each  │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. VisionExtractionAgent                                    │
│    • For each document, tries in order:                     │
│      a) Fixture content (pre-populated dict in content)     │
│      b) Uploaded text (PDF text or .txt body)               │
│      c) Groq Llama 4 Scout Vision (image base64)            │
│      d) _empty_extraction fallback (LOW or UNREADABLE)      │
│    • Groq failures → ComponentFailure, −0.08 impact         │
│    • Missing required fields → −0.02 per field              │
│    • If any doc UNREADABLE after extraction →               │
│      sets member_action_required (UNREADABLE_DOCUMENT)      │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. StructuredNormalizationAgent                             │
│    • Normalizes field aliases (patientName → patient_name)  │
│    • Parses and validates dates (ISO 8601)                   │
│    • Parses amounts, removes currency symbols               │
│    • Normalizes line items: description + amount            │
│    • Merges extracted fields into submission.document.content│
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. PatientConsistencyAgent                                  │
│    • Collects patient_name from all extracted docs          │
│    • If > 1 distinct name found:                            │
│      → sets member_action_required (PATIENT_MISMATCH)       │
│      → −0.25 confidence impact                              │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
                   ExtractionPipelineResult
```

**Fast-path optimization:** If all documents already have `content.parsed_fields` from a prior `/claims/parse/upload` call, the LangGraph pipeline is bypassed entirely and a result is built directly from cached fields.

---

## 6. Deterministic Rules Engine

### Why Rules Own Decisions

Using an LLM to approve or reject a claim introduces three problems:
1. **Non-determinism**: the same inputs can produce different outputs across calls.
2. **Unauditability**: you cannot explain which policy clause caused a rejection.
3. **Liability**: a hallucinated approval or incorrect rejection has financial consequences.

The rules engine solves all three: every rule check is a pure Python function, every result is logged as a `TraceEvent`, and every rejection reason maps to a named policy clause.

### Rule Execution Order

Rules execute in a strict order. Any failure at a gate step returns immediately — downstream rules are not evaluated.

| Step | Rule Group | Exit Type |
|---|---|---|
| 1 | Policy ID match | REJECTED |
| 2–3 | Document validation (missing / UNREADABLE) | ACTION_REQUIRED |
| 4 | Extraction pipeline (patient mismatch) | ACTION_REQUIRED |
| 5 | Member exists | REJECTED |
| 6 | Policy active dates | REJECTED |
| 7 | Submission deadline (30 days) | REJECTED |
| 8 | Minimum claim amount | REJECTED |
| 9 | Category enabled | REJECTED |
| 10–12 | Waiting periods (initial, specific, pre-existing) | REJECTED |
| 13–15 | Exclusions (condition, dental, vision) | REJECTED |
| 16 | Pre-authorisation | REJECTED |
| 17–19 | Fraud signals (same-day, monthly, high-value) | MANUAL_REVIEW |
| 20 | Per-claim OPD limit | REJECTED or cap |
| 21 | Annual OPD limit | REJECTED or cap |
| 22 | Network hospital discount | amount adjusted |
| 23 | Co-pay deduction | amount adjusted |
| 24 | Line-item adjudication (dental/vision) | PARTIAL |
| 25 | Confidence scoring | — |

---

## 7. RAG Strategy (Hybrid Policy Retrieval)

### Purpose

Policy evidence is retrieved to:
1. Provide human-readable citations alongside rule check results.
2. Give the trace viewer justification for why a rule applied.
3. Feed the eval metrics (retrieval precision@k, recall@k).

### Why Hybrid Search (Dense + Lexical + RRF)

Pure semantic search misses precise keyword terms (e.g. "Teeth Whitening", "pre-authorization", "LASIK"). Pure keyword search misses paraphrase matches. Hybrid search combining both via Reciprocal Rank Fusion achieves better recall across all categories.

### Implementation

```
Query = f"{claim_category} {member_id} {hospital_name} {claimed_amount}"
           │
           ├── Dense vector search (pgvector)
           │     64-dim SHA256-derived embedding
           │     HNSW index  (halfvec if available)
           │     Top-K by cosine similarity
           │
           └── Lexical search (Postgres FTS)
                 tsvector on text column
                 ts_rank scoring
                 Top-K by rank

Both result sets → Reciprocal Rank Fusion
    score(id) = Σ  1 / (k + rank_i)   where k = 60
             i

→ Top-5 PolicyEvidence chunks returned
```

### Knowledge Base Sources

| Source | Rule Categories Indexed |
|---|---|
| `policy_terms.json` | `coverage_limits`, `opd_categories`, `document_requirements`, `exclusions`, `waiting_periods`, `pre_authorization`, `fraud_thresholds`, `network_hospitals`, `members`, `submission_rules` |
| `sample_documents_guide.md` | `document_formats` (one chunk per markdown section) |

**Embedding strategy:** Embeddings are 64-dimensional and deterministic (derived from `sha256(text)[:64]` mapped to `[-1, 1]`). This avoids any LLM call during indexing and ensures reproducible vector positions across restarts.

---

## 8. Failure Handling

| Failure Type | Trigger | System Behavior |
|---|---|---|
| Groq API unavailable | No `GROQ_API_KEY` or API error | Falls back to deterministic text extraction; appends `ComponentFailure`; reduces confidence by 0.08 per affected doc |
| Groq JSON invalid | LLM returns malformed JSON | Retried once with a repair prompt (`llama-3.3-70b-versatile`); if still invalid, falls back to `_empty_extraction` |
| Document UNREADABLE (upload) | Groq Vision classifies quality as UNREADABLE | Stopped at document validation gate; returns `ACTION_REQUIRED` with `UNREADABLE_DOCUMENT` |
| Document UNREADABLE (extraction) | All extraction attempts yield zero fields on an uploaded binary | `VisionExtractionAgent` sets `UNREADABLE_DOCUMENT` action; claim halts before rules engine |
| Patient name mismatch | > 1 distinct patient name across documents | `PatientConsistencyAgent` sets `PATIENT_MISMATCH` action; confidence −0.25 |
| Database unavailable | `DATABASE_URL` not set or DB unreachable | In-memory mode; `ClaimResponse` not persisted; policy loaded from JSON file only |
| Policy file missing/invalid | `policy_terms.json` not found or fails Pydantic | `PolicyLoadError` raised; claims return FAILED with message |
| Unexpected exception | Any unhandled exception in a service | Caught by `process_claim`; returns FAILED response with `ComponentFailure` entry |

---

## 9. Deployment Architecture

### Target Infrastructure

```
┌─────────────────────────────────────────────────────────────┐
│                    Render.com                               │
│  ┌──────────────────────────┐  ┌─────────────────────────┐ │
│  │   Backend Web Service    │  │   Frontend Web Service  │ │
│  │   Python 3.11            │  │   Node.js 18            │ │
│  │   uvicorn app.main:app   │  │   npm run build + start │ │
│  │   --host 0.0.0.0         │  │                         │ │
│  │   --port $PORT           │  │   NEXT_PUBLIC_API_BASE  │ │
│  │                          │  │   _URL → backend URL    │ │
│  │   Env vars:              │  └─────────────────────────┘ │
│  │   DATABASE_URL           │                               │
│  │   GROQ_API_KEY           │                               │
│  │   CORS_ORIGINS           │                               │
│  │   ENVIRONMENT=production │                               │
│  └──────────┬───────────────┘                               │
└─────────────┼───────────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────┐     ┌────────────────────────┐
│   Neon.tech PostgreSQL      │     │   Groq Cloud           │
│   pgvector enabled          │     │   Llama 4 Scout Vision │
│   Alembic migrations run    │     │   llama-3.3-70b repair │
│   HNSW index on embeddings  │     └────────────────────────┘
└─────────────────────────────┘
```

### Startup Sequence

1. Alembic migrations run (`alembic upgrade head`).
2. `load_policy_terms_on_startup()` reads `policy_terms.json`, validates with Pydantic, persists to DB, and indexes chunks in `policy_knowledge_chunks`.
3. FastAPI app starts accepting requests.

### Local vs Production Behavior

| Behavior | `local` / `test` env | `production` env |
|---|---|---|
| DB unavailable | Logs warning, continues in-memory | Raises `PolicyLoadError` at startup |
| Claim persistence | No-op | Writes to `claim_intakes` table |
| CORS | Allows localhost | Restricted to `CORS_ORIGINS` |

---

## 10. Scaling Considerations

The system is currently designed for a single-instance demo. Scaling paths if the system were productionised:

| Concern | Current | Scalable Path |
|---|---|---|
| Claim processing latency | Synchronous, in-request | Move to async queue (Celery + Redis); poll `/claims/{id}` for result |
| Database contention | Single connection pool | Add PgBouncer connection pooler in front of Neon |
| Vector index performance | HNSW on 64-dim vectors | Upgrade to 1536-dim (text-embedding-3-small) with `halfvec` compression for better recall |
| LLM cost / latency | Every image goes to Groq | Add a local OCR step (Tesseract) as a pre-filter; only route to Groq when text extraction yields < 2 fields |
| Policy hot-reload | Restart required | Add `POST /admin/reload-policy` endpoint that invalidates the in-memory policy singleton |
| Multi-tenant | Single policy hardcoded | Extract `policy_id` routing; store multiple `PolicyTerms` records; look up by `submission.policy_id` |
| Observability | Trace stored in `ClaimResponse` JSON | Ship `TraceEvent` list to a structured logging sink (Datadog, Loki) with `claim_id` as correlation key |
