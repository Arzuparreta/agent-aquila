# Testing

Automated tests live under `backend/tests/` and use **[pytest](https://pytest.org/)** with **pytest-asyncio** (`asyncio_mode = auto` in `backend/pyproject.toml`).

The **frontend** has no unit/e2e test script; use `npm run lint` (Next.js ESLint).

Background **Redis** and the **ARQ worker** are for runtime mail/calendar/drive sync — they are **not** required to run `pytest`.

---

## Prerequisites

- **Python** ≥ 3.11
- **Backend dev dependencies**: install with the `dev` extra. On **PEP 668** systems, use a venv first:

  ```bash
  cd backend
  python -m venv .venv
  source .venv/bin/activate   # Windows: .venv\Scripts\activate
  pip install -e ".[dev]"
  ```

- **Postgres + pgvector** (for integration tests using `db_session`): migrated schema (`alembic upgrade head`). If the DB is unreachable, those tests **skip** (see `backend/tests/conftest.py`).

  Default test DB URL (overridable):

  ```bash
  export TEST_DATABASE_URL="postgresql+asyncpg://crm_user:crm_password@127.0.0.1:5433/crm_db"
  ```

  Typical local setup (matches the main README):

  ```bash
  docker compose up -d db
  cd backend && alembic upgrade head
  ```

  A full `docker compose up` (API + frontend) also runs `alembic upgrade head` when the backend container starts, so pytest against Compose Postgres only needs the one-off `alembic upgrade head` when you are **not** starting the API container.

---

## Running the suite

The backend currently collects **37** tests under `backend/tests/`.

From `backend/`:

```bash
cd backend
pytest
```

Useful variants:

| Command | Purpose |
|--------|---------|
| `pytest -q` | Quiet summary |
| `pytest tests/test_ai_providers.py` | One file |
| `pytest -k "openai"` | Tests whose name contains `openai` |
| `pytest --tb=short` | Shorter tracebacks |

---

## Shared fixtures (`backend/tests/conftest.py`)

| Fixture | Role |
|--------|------|
| `anyio_backend` | Asyncio backend for anyio-using code |
| `db_session` | Async SQLAlchemy session in a **transaction rolled back** after each test; requires live Postgres at `TEST_DATABASE_URL` |
| `crm_user` | User with Ollama provider and AI enabled (agent/RAG tool tests) |
| `agent_run` | Minimal `AgentRun` row tied to `crm_user` |

---

## What each module covers

| Module | DB | Summary |
|--------|----|---------|
| `test_capability_registry.py` | No | Registry keys, `describe_capabilities`, preview helpers for proposal kinds |
| `test_ai_providers.py` | No | AI provider adapters (OpenAI, Ollama, Anthropic, OpenRouter, Azure, LiteLLM, custom OpenAI-compatible): URLs, headers, parsing, error codes — HTTP mocked via `httpx.AsyncClient` patches |
| `test_ai_routes.py` | No | Provider registry enumeration, API key sentinel resolution, Pydantic normalization for user AI settings |
| `test_agent_tools.py` | Mostly yes | Hybrid RAG + entity tools, CRM/connector proposals, idempotency; `test_agent_proposal_tool_registry_matches_service` is DB-free |

---

## Frontend

```bash
cd frontend
npm install
npm run lint
```

---

## Manual UI QA

There is no Playwright/Cypress suite for the chat or inbox yet. After changing those surfaces, run through the checklist in **[`MANUAL_QA.md`](MANUAL_QA.md)** (thread kebab: rename / pin / archive / delete; inbox kebab: read state, promote, silence, start chat).

---

## Summary

| Area | Runner | Needs DB |
|------|--------|----------|
| `test_capability_registry`, `test_ai_providers`, `test_ai_routes` | `pytest` | No |
| `test_agent_tools` (except registry test) | `pytest` | Yes (skips if unreachable) |
| Frontend | `npm run lint` | No |
