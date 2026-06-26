# Plum AI Engineer Assignment

## Overview

This package contains everything you need to complete the Health Insurance Claims Processing assignment for the AI Engineer role at Plum.

## Package Contents

```
multi_agent_claims_pipeline/
│
├── README.md                  # This file
├── assignment.md              # Full assignment — read this first
├── policy_terms.json          # Policy configuration, coverage rules, member roster
├── test_cases.json            # 12 test scenarios with expected outcomes
├── sample_documents_guide.md  # Indian medical document formats and extraction guidance
├── plan.md                    # Phase-wise implementation plan
├── backend/                   # FastAPI backend
├── frontend/                  # Next.js ops review UI
├── docs/                      # Architecture, contracts, and eval reports
└── data/                      # Application copies of assignment data files
```

## Getting Started

Read `assignment.md` in full before writing a single line of code. Understand the problem before you reach for a solution.

## Phase 1 Local Setup

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
uvicorn app.main:app --reload
```

The backend also supports the modern editable install path:

```bash
pip install -e ".[dev]"
```

Backend health check:

```bash
curl http://localhost:8000/health
```

### Frontend

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

Frontend URL:

```text
http://localhost:3000
```

### Deployment Target

- Frontend: Render web/static service
- Backend: Render web service
- Database: Neon Postgres with pgvector
- LLM provider: Groq Llama API

## Timeline

2-3 days from receipt.
