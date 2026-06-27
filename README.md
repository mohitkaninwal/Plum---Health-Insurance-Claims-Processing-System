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
│   ├── architecture.md        # System design document
│   ├── component_contracts.md # Typed contracts for every component
│   └── eval_report.md         # Results for all 12 test cases
└── data/                      # Symlinks to policy and test data
```

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

## Key Documents

- **`docs/component_contracts.md`** — Typed input/output/error contracts for every component. Start here if you want to understand or reimplement any part of the system.
- **`docs/architecture.md`** — System design, component interactions, and scaling considerations.
- **`docs/eval_report.md`** — Decision accuracy on all 12 test cases with full traces.

---

## Quick API Reference

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/claims/submit` | Submit a claim as JSON |
| `POST` | `/claims/submit/upload` | Submit a claim with real file uploads |
| `GET` | `/claims/{claim_id}` | Fetch a claim response and full trace |
| `POST` | `/eval/run` | Run all 12 test cases and return metrics |
| `GET` | `/eval/latest` | Fetch the last eval run |
| `GET` | `/health` | Health check |
