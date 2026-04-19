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
- **OAuth connectors**: Google Workspace and Microsoft 365 (Graph) — register redirect URIs in each vendor console once, then paste app credentials under **Settings → External connectors** (stored in Postgres; no OAuth env vars required for normal use)
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
- `.env.example` environment template (Postgres, JWT, CORS, Redis, optional OAuth env fallbacks, agent limits)
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
   - **OAuth** (Gmail, Outlook, etc.): **Settings → External connectors** — set the app’s public URL, then follow the on-page steps for Google and/or Microsoft. Migrations run when the API container starts (`docker compose up`).

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

## Agent harness

The agent runtime is a deliberately bare ReAct loop in the OpenClaw style:
plumbing belongs to the harness, every product decision (which tool to call,
what arguments to pass, when to stop gathering, when to terminate) belongs to
the model.

### Contract

- `AgentService.run_agent` sends the **full** `AGENT_TOOLS` palette on every
  turn with `tool_choice="required"`.
- Every turn ends in a tool call. `final_answer` is the universal terminator —
  calling it persists the natural-language reply and ends the run. The loop
  also stops if `settings.agent_max_tool_steps` is reached (universal step
  cap; failure surfaces as `error="Step budget exceeded"`).
- Tool names must match `AGENT_TOOL_NAMES` exactly. Argument shapes must match
  the JSON schema. There is no alias map and no argument coercion: a wrong
  call comes back as a terse `{"error": "unknown tool '<name>'"}` (or the
  tool's own validation error) and the model is expected to retry inside the
  step budget — exactly like any REST API.

### Adding a tool

Adding a capability is a **one-edit** change: register an entry in
`backend/app/services/agent_tools.py::AGENT_TOOLS` with a rich description in
the OpenClaw "when to use / when not to use / inputs / outputs" pattern and
wire its handler into `AgentService._dispatch_tool`. The harness picks the
new tool up automatically on the next turn — no prompt updates, no router
edits, no keyword maps. The description is the **only** knob the agent has
for picking the right tool, so spend time on it.

### Extension seams

Two pure functions in `agent_service.py` are called once per `run_agent`
invocation; the loop only knows about their return values:

- `get_tool_palette(user, *, tenant_hint=None) -> list[dict]` — today
  returns `AGENT_TOOLS` for everyone. This is where per-tenant skill toggles
  plug in (artists vs businesses, "starter" tier, custom bundles), without
  touching the loop.
- `build_system_prompt(user, *, thread_context_hint=None, tenant_hint=None) -> str` —
  today returns the universal `AGENT_SYSTEM` plus an optional thread-context
  line. This is where per-vertical personas (artist's ops manager, business
  account manager) plug in.

### Recommended models

Any provider that honors `tools=` and `tool_choice="required"` reliably
works. Frontier models (GPT-4o-class, Claude Sonnet-class, Gemini Pro-class)
read tool descriptions and pick the right tool every time. Small local models
(Gemma 3B, Qwen 2.5 small, Llama 3.2 3B) will misbehave more visibly here
than in older harnesses — by design: every model-compensating workaround was
removed because each one was a permanent tax on every future tool. If a
weaker model is in the loop and emits hallucinated tool names, the run will
exhaust the step budget and fail; swap the model rather than re-introducing
compensations.

## Notes

- Optional agent / ingest behavior is centralized in `.env.example` (`AGENT_*`, `EMAIL_INGEST_AUTO_CREATE_DEALS`, sync poll limits).
- `services/` is the main extension point; the agent coordinator is `app/services/agent_service.py`.
- `pgvector` is enabled in migration `0001_initial`; `0003_rag_agent` adds `rag_chunks` (HNSW + GIN fts), `agent_runs`, and `pending_proposals`.
- For **JSON `response_format` on chat completions**, use an OpenAI-compatible provider; some local stacks omit this and may need a code-path change.
