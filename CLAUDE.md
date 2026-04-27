# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Quick Start

```bash
# Full stack development
docker compose up --build

# Frontend development (host)
cd frontend && npm install && npm run dev

# Backend development (Docker)
docker compose up backend db redis worker

# Test AI provider configuration
docker compose exec backend python -m app.scripts.smoke_ai_provider
```

## Architecture Overview

Agent Aquila is a self-hosted personal operations assistant with a **context-first** design. The system consists of:

- **Backend** (`backend/`): FastAPI + SQLAlchemy + ARQ worker, handles agent execution, connectors, and memory
- **Frontend** (`frontend/`): Next.js app for chat, inbox, and settings
- **Gateway** (`gateway/`): Channel adapters for external integrations (Telegram, etc.)

### Key Architectural Patterns

**Agent Execution Loop**: The agent runs in a ReAct loop with tool dispatch. Tools are defined in `backend/app/services/agent_tools.py` (`AGENT_TOOLS`) and dispatched via `backend/app/services/agent_dispatch_table.py`. The main loop is in `backend/app/services/agent_service.py`.

**Dual Harness System**: The agent supports both **native** (OpenAI-style `tools=` parameter) and **prompted** (embedded JSON in system prompt) harness modes. The selector in `backend/app/services/agent_harness/selector.py` automatically chooses the appropriate mode based on provider capabilities.

**No Local Mirrors**: Unlike some systems, Aquila does **not** mirror Gmail/Calendar/Drive locally. Every read tool calls the upstream API directly. This keeps the system lightweight and always current.

**Memory System**: Hybrid design with canonical markdown files (`data/users/<user_id>/memory_workspace/`) as source of truth, plus Postgres indexing (`agent_memories` table) for semantic search. See `docs/MEMORY.md` for details.

**Skills System**: Reusable markdown playbooks in `backend/skills/` that the agent can load and execute. Skills are agent-local state and can be auto-generated from successful runs.

**Runtime Configuration**: Agent behavior tunables (rate limits, tool loop, heartbeat, harness options) follow a two-tier system: environment variables define defaults, per-user JSON in `user_ai_settings.agent_runtime_config` stores overrides. See `docs/AGENT_SETTINGS.md`.

**Connector Architecture**: OAuth-based provider connections (Gmail, Calendar, Drive, Outlook, Teams, etc.) are managed through `backend/app/services/connectors/`. Each connector implements a standard interface for tool access.

## Adding Capabilities

To add a new tool/capability:

1. Define the tool in `backend/app/services/agent_tools.py` (`AGENT_TOOLS` dict)
2. Add the dispatch mapping in `backend/app/services/agent_dispatch_table.py`
3. Implement the handler in `backend/app/services/agent_service.py` (`_tool_*` methods)
4. For high-risk actions (like sending email), add to `_PROPOSAL_TOOLS` for approval workflow

## Testing

```bash
# Run all backend tests
docker compose exec backend pytest

# Run specific test file
docker compose exec backend pytest tests/test_agent_tools.py

# Run with coverage
docker compose exec backend pytest --cov=app

# Frontend tests
cd frontend && npm test
```

Test utilities and fixtures are in `backend/tests/conftest.py`. The test suite uses pytest-asyncio for async tests.

## Database

- **ORM**: SQLAlchemy 2.0 with async support
- **Migrations**: Alembic (migrations in `backend/alembic/versions/`)
- **Connection**: PostgreSQL via asyncpg
- **Vector search**: pgvector for semantic memory recall

Migrations run automatically on API startup. First boot on an old database may apply destructive migrations.

## Background Jobs

The ARQ worker (`backend/app/worker.py`) handles:

- **Heartbeat**: Optional scheduled agent wakes (disabled by default to avoid quota burn)
- **Memory consolidation**: Periodic reindexing and `DREAMS.md` generation
- **Telegram polling**: Long-poll supervisor for Telegram integration
- **Scheduled tasks**: User-defined cron jobs

## AI Provider Configuration

The system supports multiple AI providers through a unified interface:

- **Google AI Studio (Gemini)**: Free cloud option with generous free tier
- **Ollama**: Free local option with various model tiers
- **OpenAI**: Paid frontier option with highest tool-call accuracy
- **Others**: OpenRouter, LiteLLM, Anthropic (via OpenRouter), Azure OpenAI, Custom

All providers use the same `LLMClient.chat_with_tools` and `EmbeddingClient.embed_texts` clients. Provider-specific logic is in `backend/app/services/ai_providers/`.

## Important Files

| Path | Purpose |
|------|---------|
| `backend/app/services/agent_service.py` | Main agent execution loop |
| `backend/app/services/agent_tools.py` | Tool definitions and schemas |
| `backend/app/services/agent_dispatch_table.py` | Tool → handler mapping |
| `backend/app/services/agent_memory_service.py` | Memory operations |
| `backend/app/services/connector_service.py` | Connector management |
| `backend/app/services/llm_client.py` | Unified LLM client |
| `backend/app/worker.py` | Background job processing |
| `backend/skills/` | Reusable agent skills |
| `docs/` | Comprehensive documentation |

## Environment Configuration

Key environment variables (see `.env.example`):

- `DATABASE_URL`: PostgreSQL connection string
- `REDIS_URL`: Redis connection for ARQ
- `SECRET_KEY`: JWT signing key
- `AGENT_HEARTBEAT_ENABLED`: Enable/disable scheduled agent wakes
- `AGENT_HEARTBEAT_CHECK_GMAIL`: Include Gmail in heartbeat (default: false)

Provider credentials and OAuth app settings are also environment-configured.

## Development Notes

- **TypeScript**: Frontend uses TypeScript; run `npm install` in `frontend/` after fresh clone
- **Python**: Backend requires Python 3.11+
- **Docker**: Primary development environment via docker-compose
- **Hot reload**: Frontend supports hot reload; backend requires restart for Python changes
- **Logging**: Structured logging via Python's logging module
- **Error handling**: Mis-invoked tools return structured errors for model retry

## Safety Defaults

Sending or replying **from the agent** is the only action that asks for approval by default. Other actions run directly through OAuth-backed provider calls. This policy can be tuned in `backend/app/services/agent_tools.py` (`_PROPOSAL_TOOLS`) and `backend/app/services/capability_registry.py`.