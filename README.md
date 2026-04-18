# CRM + AI Cockpit MVP

Production-oriented MVP for a music artist CRM + future AI automation cockpit.

## Tech stack

- Backend: FastAPI + SQLAlchemy + Alembic
- Database: PostgreSQL 16 (`pgvector` extension enabled)
- Frontend: Next.js (TypeScript, Tailwind, shadcn-style UI primitives)
- Infra: Docker Compose

## Features in this MVP

- JWT auth (`/api/v1/auth/register`, `/api/v1/auth/login`, `/api/v1/auth/me`)
- CRUD APIs for `contacts`, `emails`, `deals`, `events`
- **Operations cockpit** (Next.js `/cockpit`): ReAct-style agent with hybrid RAG and **human-gated pending operations** — CRM create/update (contacts, deals, events) plus **connector actions** (email send, calendar create, file upload, Teams message) after approval (`POST /api/v1/agent/runs`, `/api/v1/agent/proposals/...` or list `/api/v1/agent/pending-operations`, preview `/api/v1/agent/pending-operations/{id}/preview`, capabilities `/api/v1/agent/capabilities`). Configure connectors via `/api/v1/connectors` (create, `GET/PATCH /connectors/{id}`, `POST /connectors/preview`, `POST /connectors/dry-run`).
- **Chunked hybrid RAG**: per-entity text is split into labeled chunks, embedded, and searched with **dense vectors + PostgreSQL full-text (RRF fusion)**. Falls back to legacy single-vector row search if `rag_chunks` is empty. Rebuild indexes with `POST /api/v1/ai/rag/backfill`.
- Per-user AI settings (OpenAI-compatible / Ollama / OpenRouter) and encrypted API keys
- Deterministic email ingestion rule on `POST /api/v1/emails`:
  - upsert contact by sender email
  - create `new` deal when subject contains `concert|booking|show` (LLM triage can refine when configured)
- Audit log table for create/update/delete tracking
- Clean layering: `models/`, `schemas/`, `services/`, `routes/`

## Project structure

- `backend/` FastAPI app, SQLAlchemy models, services, routes, Alembic migrations
- `frontend/` Next.js dashboard app
- `docker-compose.yml` local orchestration
- `.env.example` environment template

## Local run

1. Copy env template:

   ```bash
   cp .env.example .env
   ```

2. Start all services:

   ```bash
   docker compose up --build
   ```

3. Open:
   - Frontend: `http://localhost:3002` (Compose maps this to the app in the container; avoids host port clashes on `3000`)
   - The UI talks to the API via same-origin `/api/v1` (Next.js proxies to the backend), which avoids browser `NetworkError` / CORS when using `127.0.0.1` vs `localhost` or another host.
   - Backend docs: `http://localhost:8000/docs`
   - Postgres from your host (optional): `localhost:5433` → container `5432` (avoids clashing with a local PostgreSQL on `5432`)

## API quickstart

1. Register:

   ```bash
   curl -X POST http://localhost:8000/api/v1/auth/register \
     -H "Content-Type: application/json" \
     -d '{"email":"admin@example.com","password":"password123","full_name":"Admin"}'
   ```

2. Login (use returned `access_token`):

   ```bash
   curl -X POST http://localhost:8000/api/v1/auth/login \
     -H "Content-Type: application/json" \
     -d '{"email":"admin@example.com","password":"password123"}'
   ```

## Notes for future AI evolution

- Optional env: `AGENT_EMAIL_DOMAIN_ALLOWLIST`, `AGENT_MAX_RUNS_PER_HOUR`, `AGENT_MAX_TOOL_STEPS`, `EMAIL_INGEST_AUTO_CREATE_DEALS` (set `false` to stop auto deal creation on email ingest; aligns with human-gated agent mutations).
- `services/` layer is the extension point for future AI workflows; the agent coordinator lives in `app/services/agent_service.py` with tools over the same CRM APIs.
- `pgvector` extension is enabled in migration `0001_initial`; migration `0003_rag_agent` adds `rag_chunks` (HNSW + GIN fts), `agent_runs`, and `pending_proposals`.
- `audit_logs` keeps deterministic history for replay/training pipelines.
- For **JSON `response_format` on chat completions**, use an OpenAI-compatible provider; some local stacks omit this and may require a code-path change.
