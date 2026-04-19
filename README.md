```
        _.--.__                                _.--.
    ./'       `--.__                   __.--'    \.
   //__               `--.__       __.-'              \\
  ///_ `--.._               `-._.-'              _..--' \\\
 /////_      `--.._         _.-'         _..--'      \\\\
//////_         `--.._   .-'    _..--'              \\\\\\
```

# Agent Aquila

> A self-hosted AI agent harness. Bring your own model, keep your own data.

Agent Aquila is a self-hosted cockpit for an AI agent that actually does things on your behalf — but only after you say yes. It pairs a deliberately bare ReAct loop with a small CRM (contacts, deals, events, emails), hybrid RAG search over your own data, and OAuth connectors to Google Workspace and Microsoft 365. Every action the agent wants to take outside of pure reads is staged as a human-gated proposal you approve, edit, or discard.

## Features

- **Agent chat** — ReAct loop with tool-calling; every write is a proposal you must approve
- **CRM** — contacts, deals, events, emails (full CRUD)
- **Hybrid RAG** — dense vectors plus PostgreSQL full-text, fused with RRF
- **Connectors** — Gmail, Google Calendar, Google Drive, Microsoft 365 / Outlook / Teams via OAuth
- **Automations** — user-defined rules with manual test runs
- **Bring your own model** — OpenAI-compatible, Ollama, Google AI Studio, OpenRouter
- **BYOK key storage** — API keys protected with envelope encryption
- **Background sync** — Gmail, Calendar, and Drive kept fresh by an ARQ worker on Redis
- **One-command deploy** — Docker Compose brings up everything

## Quick start

```bash
cp .env.example .env
docker compose up --build
```

Then open:

- **App** — <http://localhost:3002>
- **API docs** — <http://localhost:8000/docs>

The compose stack also exposes Postgres on `localhost:5433` and Redis on `localhost:6379` if you want to poke at them from your host. Migrations run automatically when the API container starts.

To wire up Gmail, Outlook, Drive, Teams, etc., go to **Settings → External connectors** in the app and follow the on-page steps.

## Choosing an AI model

Agent Aquila is BYOK and provider-agnostic. Configure your model in **Settings → AI model**, picking from any OpenAI-compatible endpoint, Ollama, Google AI Studio, or OpenRouter.

The harness ships zero model-compensating shims: the model has to honor `tools=` / `tool_choice="required"` and pick the right tool from its description. Pick a model that does tool-calling well — there are good free, local, and paid options.

For copy-pasteable setup per tier (free cloud / free local / paid frontier) and a smoke-test command that exercises the same code paths the agent uses, see [`docs/PROVIDERS.md`](docs/PROVIDERS.md).

## Extending the harness

Adding a capability is a one-edit change:

1. Register a new entry in `AGENT_TOOLS` inside [`backend/app/services/agent_tools.py`](backend/app/services/agent_tools.py) with a clear description (when to use, when not to use, inputs, outputs).
2. Wire its handler into `AgentService._dispatch_tool` in [`backend/app/services/agent_service.py`](backend/app/services/agent_service.py).

That's it. The harness picks the new tool up on the next turn — no prompt edits, no router changes, no keyword maps. The tool description is the only knob the agent has for picking the right tool, so spend time on it.

## Project layout

- [`backend/`](backend/) — FastAPI app, SQLAlchemy models, services, routes, Alembic migrations, ARQ worker
- [`frontend/`](frontend/) — Next.js app (chat, inbox, automations, settings)
- [`docker-compose.yml`](docker-compose.yml) — local orchestration (`db`, `redis`, `backend`, `worker`, `frontend`)
- [`.env.example`](.env.example) — environment template
- [`docs/`](docs/) — extra documentation

## Further reading

- [`docs/PROVIDERS.md`](docs/PROVIDERS.md) — AI provider setup and smoke tests
- [`docs/testing.md`](docs/testing.md) — backend pytest and frontend lint
- [`docs/MANUAL_QA.md`](docs/MANUAL_QA.md) — manual UI checklist
- <http://localhost:8000/docs> — live OpenAPI reference (once the stack is up)
