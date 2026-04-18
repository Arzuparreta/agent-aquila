# CRM + AI Cockpit MVP

Production-oriented MVP for a music artist CRM + future AI automation cockpit.

## Tech stack

- Backend: FastAPI + SQLAlchemy + Alembic
- Database: PostgreSQL 16 (`pgvector` extension enabled)
- Jobs: Redis7 + [ARQ](https://arq-docs.helpmanual.io/) worker (background Gmail / Calendar / Drive sync)
- Frontend: Next.js (TypeScript, Tailwind, shadcn-style UI primitives)
- Infra: Docker Compose (`db`, `redis`, `backend`, `worker`, `frontend`)

## Features in this MVP

- JWT auth (`/api/v1/auth/register`, `/api/v1/auth/login`, `/api/v1/auth/me`)
- CRUD APIs for `contacts`, `emails`, `deals`, `events`
- **Automations**: `/api/v1/automations` (user-defined rules + manual test run)
- **OAuth connectors**: Google (Gmail, Calendar, Drive) and optional Microsoft Graph (mail, calendar, OneDrive) under `/api/v1/oauth/...` — see `.env.example` for client IDs, redirect base, and post-auth redirect
- **Operations cockpit** (Next.js `/cockpit`): ReAct-style agent with hybrid RAG and **human-gated pending operations** — CRM create/update (contacts, deals, events) plus **connector actions** (email send, calendar create, file upload, Teams message) after approval (`POST /api/v1/agent/runs`, `/api/v1/agent/proposals/...` or list `/api/v1/agent/pending-operations`, preview `/api/v1/agent/pending-operations/{id}/preview`, capabilities `/api/v1/agent/capabilities`). Configure connectors via `/api/v1/connectors` (create, `GET/PATCH /connectors/{id}`, `POST /connectors/preview`, `POST /connectors/dry-run`).
- **Chunked hybrid RAG**: per-entity text is split into labeled chunks, embedded, and searched with **dense vectors + PostgreSQL full-text (RRF fusion)**. Falls back to legacy single-vector row search if `rag_chunks` is empty. Rebuild indexes with `POST /api/v1/ai/rag/backfill`.
- Per-user AI settings (OpenAI-compatible / Ollama / OpenRouter) and encrypted API keys
- Deterministic email ingestion rule on `POST /api/v1/emails`:
  - upsert contact by sender email
  - create `new` deal when subject contains `concert|booking|show` (LLM triage can refine when configured)
- Audit log table for create/update/delete tracking
- Clean layering: `models/`, `schemas/`, `services/`, `routes/`

## Project structure

- `backend/` FastAPI app, SQLAlchemy models, services, routes, Alembic migrations, ARQ worker (`app/worker.py`)
- `frontend/` Next.js dashboard app
- `docker-compose.yml` local orchestration
- `.env.example` environment template (Postgres, JWT, CORS, Redis, OAuth, agent limits)
- `docs/testing.md` how to run backend pytest and frontend lint

## Local run

1. Copy env template:

   ```bash
   cp .env.example .env
   ```

2. Start all services:

   ```bash
   docker compose up --build
   ```

   This starts **Postgres**, **Redis**, the API (runs migrations on boot), the **worker** (sync jobs), and the **frontend**.

3. Open:
   - Frontend: `http://localhost:3002` (Compose maps this to the app in the container; avoids host port clashes on `3000`)
   - The UI talks to the API via same-origin `/api/v1` (Next.js proxies to the backend), which avoids browser `NetworkError` / CORS when using `127.0.0.1` vs `localhost` or another host.
   - Backend docs: `http://localhost:8000/docs`
   - Postgres from your host (optional): `localhost:5433` → container `5432` (avoids clashing with a local PostgreSQL on `5432`)
   - Redis from your host (optional): `localhost:6379`

   For **OAuth** (connector login from the UI), configure the Google/Microsoft variables in `.env` and use the redirect URIs documented there.

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

## Notes

- Optional agent / ingest behavior is centralized in `.env.example` (`AGENT_*`, `EMAIL_INGEST_AUTO_CREATE_DEALS`, sync poll limits).
- `services/` is the main extension point; the agent coordinator is `app/services/agent_service.py`.
- `pgvector` is enabled in migration `0001_initial`; `0003_rag_agent` adds `rag_chunks` (HNSW + GIN fts), `agent_runs`, and `pending_proposals`.
- For **JSON `response_format` on chat completions**, use an OpenAI-compatible provider; some local stacks omit this and may need a code-path change.
