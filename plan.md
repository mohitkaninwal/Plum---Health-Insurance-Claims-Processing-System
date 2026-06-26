# Health Insurance Claims Processing System: Phase-Wise Plan

## Summary

Build a full-stack, explainable health insurance claims processing system using:

- **Frontend**: Next.js/React hosted on Render
- **Backend**: FastAPI hosted on Render
- **Database**: Neon Postgres with pgvector
- **LLM**: Groq Llama API
- **Orchestration**: LangChain + LangGraph
- **RAG**: Hybrid retrieval with dense vector search, lexical search, RRF, HNSW, and optional `halfvec`
- **Evaluation**: Decision accuracy, precision, recall, F1, retrieval precision@k/recall@k

The system must accept claim submissions, validate documents early, extract structured data, apply `policy_terms.json`, produce explainable decisions, and run all 12 cases from `test_cases.json`.

## Phase 1: Project Setup

- Create a monorepo with:
  - `backend/` for FastAPI
  - `frontend/` for Next.js
  - `docs/` for architecture, contracts, and eval reports
  - `data/` for `policy_terms.json`, `test_cases.json`, and document guide files
- Configure backend dependencies:
  - FastAPI
  - Pydantic v2
  - SQLAlchemy or SQLModel
  - Alembic
  - LangChain
  - LangGraph
  - Groq SDK
  - pgvector client support
  - pytest
- Configure frontend dependencies:
  - Next.js
  - TypeScript
  - Tailwind CSS
  - React Query or SWR
  - lightweight chart/table components
- Configure deployment:
  - Render web service for backend
  - Render static/web service for frontend
  - Neon Postgres for database and vector index
  - Groq API key as backend environment variable

## Phase 2: Data Models And Contracts

- Define backend domain models:
  - `ClaimSubmission`
  - `UploadedDocument`
  - `DocumentClassification`
  - `ExtractedDocumentData`
  - `PolicyEvidence`
  - `RuleCheckResult`
  - `ClaimDecision`
  - `TraceEvent`
  - `EvalRun`
- Define API endpoints:
  - `POST /claims/submit`
  - `GET /claims/{claim_id}`
  - `POST /eval/run`
  - `GET /eval/latest`
  - `GET /health`
- Standard response shape:
  - `claim_id`
  - `status`
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

## Phase 3: Policy Loading And Rule Configuration

- Load `policy_terms.json` at backend startup.
- Validate it with strict Pydantic schemas.
- Store normalized policy data in Postgres for:
  - members
  - coverage limits
  - document requirements
  - OPD categories
  - exclusions
  - waiting periods
  - pre-authorization rules
  - fraud thresholds
  - network hospitals
- Do not hardcode policy values.
- Hardcode only generic rule execution logic.

## Phase 4: Document Intake And Early Validation

- Support two input modes:
  - real uploaded PDFs/images from frontend
  - deterministic fixture documents from `test_cases.json`
- Implement document classification:
  - For fixtures, use `actual_type`.
  - For real uploads, use Groq vision-first classification when possible.
  - Use backend PDF/image preprocessing fallback when needed.
- Validate required documents using `policy_terms.document_requirements`.
- Stop before claim adjudication for:
  - missing required documents
  - wrong document type
  - unreadable document
  - conflicting patient names across documents
- Return specific actionable messages, for example:
  - "CONSULTATION requires HOSPITAL_BILL, but only PRESCRIPTION documents were uploaded."
  - "The uploaded pharmacy bill `blurry_bill.jpg` is unreadable. Please re-upload a clearer image."

## Phase 5: Extraction Pipeline

- Use LangGraph to orchestrate extraction and validation.
- Build extraction nodes:
  - `DocumentVerifierAgent`
  - `VisionExtractionAgent`
  - `StructuredNormalizationAgent`
  - `PatientConsistencyAgent`
- Use Groq Llama for:
  - OCR-style extraction from image documents
  - classification
  - structured field extraction
  - normalization of messy medical terms
- Validate all LLM outputs with Pydantic.
- Retry invalid JSON once with a repair prompt.
- If extraction partially fails:
  - preserve available fields
  - mark missing fields
  - reduce confidence
  - continue only if minimum evidence exists

## Phase 6: RAG Indexing And Retrieval

- Build a policy knowledge base from:
  - `policy_terms.json`
  - relevant sections of `sample_documents_guide.md`
- Use advanced splitting:
  - JSON chunks by policy rule family and JSON path
  - Markdown chunks by document type and extraction topic
- Store embeddings in Neon Postgres with pgvector.
- Create vector indexes:
  - HNSW index for dense search
  - `halfvec` if supported by the deployed pgvector version
  - normal vector fallback if `halfvec` is unavailable
- Implement hybrid retrieval:
  - dense vector search
  - Postgres full-text lexical search
  - Reciprocal Rank Fusion
- Retrieval is used for:
  - policy evidence
  - trace explanation
  - eval metrics
- Final claim decisions remain deterministic through the rule engine.

## Phase 7: Deterministic Rule Engine

- Implement rule checks for:
  - member validity
  - policy validity
  - submission deadline
  - minimum claim amount
  - document requirements
  - patient consistency
  - exclusions
  - dental and vision exclusions
  - waiting periods
  - pre-authorization
  - per-claim limit
  - annual OPD limit
  - category sub-limits
  - network hospital discount
  - co-pay
  - fraud thresholds
- Apply decision ordering:
  - document/member-action failures stop before decision
  - exclusions reject
  - waiting periods reject
  - missing pre-auth rejects
  - fraud signals route to manual review
  - mixed covered/excluded line items produce partial approval
  - valid claims calculate final approved amount
- Required test outcomes:
  - TC001: stop early for wrong documents
  - TC002: stop early for unreadable bill
  - TC003: stop early for patient mismatch
  - TC004: approve `1350`
  - TC005: reject for waiting period
  - TC006: partial approval `8000`
  - TC007: reject for missing pre-auth
  - TC008: reject for per-claim limit
  - TC009: manual review
  - TC010: approve `3240`
  - TC011: approve with reduced confidence and failure warning
  - TC012: reject for excluded treatment

## Phase 8: Confidence And Explainability

- Compute confidence from:
  - document quality
  - extraction completeness
  - patient consistency
  - policy evidence strength
  - rule certainty
  - component failures
- Persist trace events for every pipeline step:
  - component name
  - input summary
  - output summary
  - checks performed
  - result
  - evidence
  - confidence impact
  - errors or warnings
- Decision output must explain:
  - what documents were checked
  - what fields were extracted
  - what policy rules applied
  - what passed
  - what failed
  - how approved amount was calculated
  - why confidence changed

## Phase 9: Frontend Ops Review UI

- Build pages:
  - claim submission page
  - claim decision detail page
  - eval dashboard
- Claim submission UI:
  - member ID
  - claim category
  - treatment date
  - claimed amount
  - document uploads
  - submit button
- Decision review UI:
  - final decision
  - approved amount
  - confidence score
  - member action required
  - document validation results
  - extracted fields
  - line-item adjudication
  - trace timeline
  - policy evidence panel
  - component failure warnings
- Eval dashboard:
  - run all 12 test cases
  - show expected vs actual
  - show pass/fail
  - show aggregate metrics
  - allow opening full trace per case

## Phase 10: Evaluation

- Implement eval runner over `test_cases.json`.
- Track claim decision metrics:
  - decision accuracy
  - early-stop correctness
  - approved amount exact-match rate
  - reason-label precision
  - reason-label recall
  - reason-label F1
- Track retrieval metrics:
  - precision@k
  - recall@k
  - MRR where labels exist
  - NDCG where labels exist
- Generate `docs/eval_report.md` with:
  - per-case input summary
  - expected outcome
  - actual outcome
  - trace
  - pass/fail status
  - mismatch explanation
  - aggregate metrics

## Phase 11: Testing

- Backend unit tests:
  - policy loader
  - document requirement validation
  - unreadable document handling
  - patient mismatch handling
  - waiting-period calculations
  - exclusion matching
  - pre-auth checks
  - per-claim limit checks
  - network discount and co-pay ordering
  - fraud threshold routing
- Backend integration tests:
  - all 12 test cases
  - simulated component failure
  - fixture adapter
  - mocked Groq extraction path
- Retrieval tests:
  - policy rule retrieval by category
  - dense vs hybrid retrieval comparison
  - RRF ranking behavior
- Frontend tests:
  - submission form validation
  - document error rendering
  - decision detail rendering
  - eval dashboard rendering

## Phase 12: Documentation

- Create `docs/architecture.md`:
  - system overview
  - component diagram
  - data flow
  - deployment architecture
  - why LangGraph
  - why deterministic rules own final decisions
  - RAG strategy
  - failure handling
  - scaling plan
- Create `docs/component_contracts.md`:
  - classifier contract
  - extractor contract
  - retriever contract
  - rule engine contract
  - fraud detector contract
  - explanation builder contract
  - eval runner contract
- Update `README.md`:
  - local setup
  - environment variables
  - database setup
  - run backend
  - run frontend
  - run tests
  - deploy to Render

## Deployment Plan

- Render backend service:
  - Python FastAPI app
  - environment variables:
    - `DATABASE_URL`
    - `GROQ_API_KEY`
    - `CORS_ORIGINS`
  - start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Render frontend service:
  - Next.js app
  - environment variables:
    - `NEXT_PUBLIC_API_BASE_URL`
- Neon database:
  - enable pgvector
  - run Alembic migrations
  - seed policy data
  - build vector index
- Groq:
  - use Llama model for extraction and explanation
  - validate every model output before use

## Assumptions

- Frontend and backend will both deploy on Render.
- Database will use Neon Postgres because its free tier is better suited than Render free Postgres for a persistent demo.
- Groq Llama API will be used for LLM calls.
- Groq vision-first extraction will be preferred over heavy local OCR for deployment practicality.
- Backend-side PDF/image preprocessing may still be used for PDFs and fallback cases.
- LLMs will not make final approval/rejection decisions.
- `policy_terms.json` and `test_cases.json` are the source of truth for policy behavior and acceptance tests.
