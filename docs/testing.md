# Testing

This repository’s **automated tests** live under `backend/tests/` and use **[pytest](https://pytest.org/)** with **pytest-asyncio** (`asyncio_mode = auto` in `backend/pyproject.toml`).

The **frontend** has **no Jest/Vitest/Playwright scripts** in `frontend/package.json`; the closest check is static analysis via `npm run lint` (Next.js ESLint).

---

## Prerequisites

- **Python** ≥ 3.11
- **Backend dev dependencies**: install the backend package with the `dev` extra (includes pytest and pytest-asyncio). On distributions with **PEP 668** (externally managed Python), use a venv first:

  ```bash
  cd backend
  python -m venv .venv
  source .venv/bin/activate   # Windows: .venv\Scripts\activate
  pip install -e ".[dev]"
  ```

- **Postgres + pgvector** (for integration tests that use the `db_session` fixture): migrated schema (`alembic upgrade head`). If the DB is unreachable, those tests **skip** with a message pointing at Docker and Alembic (see `backend/tests/conftest.py`).

  Default test DB URL (overridable):

  ```bash
  export TEST_DATABASE_URL="postgresql+asyncpg://crm_user:crm_password@127.0.0.1:5433/crm_db"
  ```

  Typical local setup (matches the main README):

  ```bash
  docker compose up -d db
  cd backend && alembic upgrade head
  ```

---

## How to run everything

The backend suite currently collects **37** tests under `backend/tests/`.

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
| `anyio_backend` | Forces asyncio backend for anyio-using code |
| `db_session` | Async SQLAlchemy session in a **transaction rolled back** after each test; requires live Postgres at `TEST_DATABASE_URL` |
| `crm_user` | User with Ollama provider and AI enabled (for agent/RAG tool tests) |
| `agent_run` | Minimal `AgentRun` row tied to `crm_user` |

---

## Test modules and what they assert

### `test_capability_registry.py` (unit — no DB)

| Test | What it checks |
|------|----------------|
| `test_proposal_kind_registry_covers_execution_kinds` | `proposal_kind_registry()` includes key kinds (e.g. `create_deal`, `connector_teams_message`) and risk tier for `connector_email_send` |
| `test_describe_capabilities_shape` | `describe_capabilities()` returns a dict with a `proposal_kinds` map |
| `test_preview_for_create_deal` | `preview_for_proposal_kind("create_deal", ...)` returns expected `action` and `title` |

### `test_ai_providers.py` (unit — mocked HTTP, no DB)

Patches `httpx.AsyncClient` so **no real network** calls run. Covers AI provider adapters: request URLs/headers, response parsing, and error normalization.

| Test | What it checks |
|------|----------------|
| `test_openai_list_models_happy_path` | OpenAI-style `GET /v1/models`, auth header, successful `test_connection`, `safe_list_models` IDs and chat vs embedding capabilities |
| `test_openai_invalid_api_key` | 401 → `ok=False`, `code=invalid_api_key` |
| `test_openai_requires_api_key` | Empty key → `missing_field` |
| `test_ollama_tags` | Ollama `/api/tags`, no auth header, models and embedding capability for embed model names |
| `test_ollama_strips_v1_suffix` | Base URL ending in `/v1` is normalized for the tags request |
| `test_ollama_network_error` | Connect error → `code=network` |
| `test_anthropic_list_models` | Anthropic models endpoint, headers, display names, all chat capability |
| `test_openrouter_sends_extra_headers` | Referer and X-Title from extras |
| `test_azure_lists_deployments` | Azure deployments listing, api-version query, deployment IDs and model-derived capabilities |
| `test_azure_missing_api_version` | Azure without api_version → `missing_field` |
| `test_litellm_base_url_required` | LiteLLM without base URL → `missing_field` |
| `test_custom_openai_compatible_ok` | OpenAI-compatible `GET .../v1/models` success path |
| `test_timeout_mapped` | Read timeout → `code=timeout` |

### `test_ai_routes.py` (unit — no full FastAPI app / no DB)

Exercises route-adjacent helpers and schema normalization (not full HTTP integration).

| Test | What it checks |
|------|----------------|
| `test_get_providers_enumerates_registry` | `get_providers()` returns every id in `PROVIDER_IDS`, each provider has non-empty `fields` with `key` and `label` |
| `test_resolve_config_uses_sentinel` | When API key is `STORED_API_KEY_SENTINEL`, `_resolve_config` loads the real key from `UserAISettingsService.get_api_key` |
| `test_resolve_config_passes_explicit_key` | Explicit key is used; vault not called |
| `test_resolve_config_passes_none` | Ollama-style payload with `api_key=None` stays None |
| `test_user_ai_settings_update_normalizes_provider` | Pydantic normalization: empty `provider_kind` → `openai`, `openai_compat` → `openai_compatible`, invalid value raises |

### `test_agent_tools.py` (integration for DB-backed tools; one pure check)

Requires **`db_session`** (Postgres) for all tests **except** `test_agent_proposal_tool_registry_matches_service`, which only inspects `AgentService._PROPOSAL_TOOL_METHODS`.

| Test | What it checks |
|------|----------------|
| `test_agent_proposal_tool_registry_matches_service` | Set of keys in `AgentService._PROPOSAL_TOOL_METHODS` matches the curated list (CRM create/update + connector: email send/reply, calendar create/update/delete, file upload/share, Teams message) — kept in sync when new proposal tools are added |
| `test_tool_hybrid_rag_search_missing_query` | `_tool_rag` with empty args → `hits: []`, `error: missing query` |
| `test_tool_hybrid_rag_search_ai_disabled` | User with `ai_disabled` → empty hits |
| `test_tool_hybrid_rag_search_returns_hits_legacy_vector_path` | Legacy entity embedding path: contact with embedding, mocked `EmbeddingClient.embed_text`, hit includes citation, `vector_legacy`, title/snippet |
| `test_tool_get_entity_contact_found` | `_tool_get_entity` for contact returns `found` and fields |
| `test_tool_get_entity_email_deal_event` | Same for email, deal, event |
| `test_tool_get_entity_not_found_and_invalid_type` | Missing id → not found; bad `entity_type` → error |
| `test_propose_create_contact` | Proposal row created, `kind`, `proposal_id`, human-approval messaging |
| `test_propose_create_contact_idempotency` | Same `idempotency_key` returns same proposal, `deduplicated` |
| `test_propose_update_contact_and_no_fields_error` | No fields → error; with fields → `update_contact` |
| `test_propose_create_deal_and_update_deal` | Create deal proposal; update deal empty vs with fields |
| `test_propose_create_event_and_update_event` | Create event; update event empty vs with fields |
| `test_propose_connector_email_send` | Connector email send proposal kind |
| `test_propose_connector_calendar_create_summary_and_title_alias` | Calendar create accepts `summary` or `title` alias |
| `test_propose_connector_file_upload_and_missing_content_error` | Missing content → error; with `content_text` → file upload proposal |
| `test_propose_connector_teams_message` | Teams message proposal kind |

---

## Frontend

There is **no `npm test`** (or equivalent) configured. To run the linter:

```bash
cd frontend
npm install
npm run lint
```

---

## Summary

| Area | Runner | Needs DB |
|------|--------|----------|
| Backend unit tests (`test_ai_providers`, `test_ai_routes`, `test_capability_registry`) | `pytest` | No |
| Backend agent/CRM tool integration tests (`test_agent_tools` except registry test) | `pytest` | Yes (skips if unreachable) |
| Frontend | `npm run lint` only | No |
