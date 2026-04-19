```
        _.--.__                                _.--.
    ./'       `--.__                   __.--'    \.
   //__               `--.__       __.-'              \\
  ///_ `--.._               `-._.-'              _..--' \\\
 /////_      `--.._         _.-'         _..--'      \\\\
//////_         `--.._   .-'    _..--'              \\\\\\
```

# Agent Aquila

> A self-hosted agent harness focused on control and observability. Bring your own model, keep your own data, talk to your real services live.

Agent Aquila is a self-hosted cockpit for an AI agent that **operates your real
accounts directly**. It pairs a deliberately bare ReAct loop with persistent
agent memory, a markdown-driven skills folder, and live OAuth tools for Gmail,
Google Calendar, Google Drive, Microsoft Outlook, and Microsoft Teams.

There is no local mirror, no CRM, no triage classifier, no inbox machine
learning. Every read goes straight to the upstream API; every write is either
auto-applied (archive, label, mute, move to spam, calendar edits, file moves,
Teams messages…) or — for the one truly destructive case, **sending email** —
staged as a one-click human approval.

## What changed (OpenClaw refactor)

- **Live, no mirror.** Inbox, calendar, drive and Teams views call the upstream
  API on every request. No `emails`, `events`, `drive_files`,
  `connection_sync_state` or RAG-chunks tables; no background sync workers.
- **Single tab inbox.** Email is shown as one chronological list with free-form
  Gmail search (`q=is:unread from:bob`), keyboard-friendly pagination, and
  per-row **Mute / Spam / Reply** actions wired straight into Gmail.
- **Mute / Spam are real Gmail actions.** "Silenciar" creates a Gmail filter
  for that sender (skip-inbox + mark-read), "Spam" creates a filter and moves
  the current thread to SPAM. The chat agent has the same tools.
- **Persistent memory.** A small key/value scratchpad (with optional
  embeddings) the agent reads, writes and recalls across runs.
  See [`docs/MEMORY.md`](docs/MEMORY.md).
- **Skills folder.** Drop a markdown file in `backend/skills/` and the agent
  can list and load it as a recipe ("how do I…?"). Three seed skills ship in
  the repo. See [`docs/SKILLS.md`](docs/SKILLS.md).
- **Heartbeat instead of sync.** A single ARQ cron (off by default) wakes the
  agent every N minutes with a tiny prompt. Per-user rate-limited.
- **One destructive Alembic migration.** `0018_openclaw_destructive` drops all
  the legacy tables and creates `agent_memories`. The downgrade is a no-op.

## Features

- **Agent chat** — ReAct loop with OpenAI-style tool calling.
- **Live Gmail control** — list/search/get messages and threads, modify
  labels, archive, trash, mark read/unread, manage filters, **mute** /
  **move-to-spam senders**, send and reply (with approval).
- **Live Google Calendar / Drive** — list/create/update/delete events, list
  files, share, move, trash. All auto-applied.
- **Live Microsoft 365** — Outlook mail (read + write) and Teams messaging via
  Microsoft Graph. All auto-applied except sending email.
- **Approval gate for sending email only.** Every other write executes
  immediately; only `email_send` and `email_reply` are staged as proposals.
- **Persistent agent memory** — scratchpad with importance, tags and optional
  semantic recall.
- **Skills folder** — markdown recipes the agent can list and load.
- **Bring your own model** — OpenAI-compatible, Ollama, Google AI Studio,
  OpenRouter, Anthropic, Azure OpenAI, LiteLLM, or any OpenAI-shape custom
  endpoint.
- **BYOK key storage** with envelope encryption.
- **One-command deploy** — Docker Compose brings up everything.

## Quick start

```bash
cp .env.example .env
docker compose up --build
```

Then open:

- **App** — <http://localhost:3002>
- **API docs** — <http://localhost:8000/docs>

The compose stack also exposes Postgres on `localhost:5433` and Redis on
`localhost:6379`. Migrations run automatically when the API container starts;
the destructive `0018_openclaw_destructive` migration will drop all the legacy
mirror/CRM tables on first boot of an existing install.

To wire up Gmail, Outlook, Drive or Teams, go to **Settings → External
connectors** in the app and follow the on-page steps.

> **Existing Gmail users must reconnect.** The agent now needs the
> `https://www.googleapis.com/auth/gmail.settings.basic` scope to manage
> filters (mute/spam). The Settings page shows a yellow **Reconnect Gmail**
> banner whenever a stored grant is missing the scope.

## Approval policy

| Action                                              | Behaviour     |
| --------------------------------------------------- | ------------- |
| Send / reply email (Gmail or Outlook)               | **Proposal**  |
| Archive, trash, label, mark read/unread, mute, spam | Auto-apply    |
| Create / update / delete calendar events            | Auto-apply    |
| Move / share / trash Drive files                    | Auto-apply    |
| Post to Teams chats / channels                      | Auto-apply    |
| Read of any kind                                    | Auto-apply    |

Approvals live at `/proposals` and arrive as a card in the chat.

## Choosing an AI model

Agent Aquila is BYOK and provider-agnostic. Configure your model in
**Settings → AI model**, picking from any OpenAI-compatible endpoint, Ollama,
Google AI Studio, or OpenRouter.

The harness ships zero model-compensating shims: the model has to honor
`tools=` / `tool_choice="required"` and pick the right tool from its
description. Pick a model that does tool-calling well — there are good free,
local, and paid options.

For copy-pasteable setup per tier (free cloud / free local / paid frontier)
and a smoke-test command that exercises the same code paths the agent uses,
see [`docs/PROVIDERS.md`](docs/PROVIDERS.md).

## Extending the harness

Adding a capability is a one-edit change:

1. Register a new entry in `AGENT_TOOLS` inside
   [`backend/app/services/agent_tools.py`](backend/app/services/agent_tools.py)
   with a clear description (when to use, when not to use, inputs, outputs).
2. Wire its handler into `AgentService._dispatch_tool` in
   [`backend/app/services/agent_service.py`](backend/app/services/agent_service.py).

That's it. The harness picks the new tool up on the next turn — no prompt
edits, no router changes, no keyword maps. The tool description is the only
knob the agent has for picking the right tool, so spend time on it.

If your new capability is an external write that you want surfaced as a
proposal (instead of auto-applied), add the tool name to `_PROPOSAL_TOOLS`
in `agent_tools.py` and register the proposal kind in
`backend/app/services/capability_registry.py`.

## Project layout

- [`backend/`](backend/) — FastAPI app, SQLAlchemy models, services, routes,
  Alembic migrations, ARQ worker, and the `skills/` markdown folder.
- [`frontend/`](frontend/) — Next.js app (chat, simplified inbox, settings
  with memory + skills viewers).
- [`docker-compose.yml`](docker-compose.yml) — local orchestration (`db`,
  `redis`, `backend`, `worker`, `frontend`).
- [`.env.example`](.env.example) — environment template.
- [`docs/`](docs/) — extra documentation.

## Further reading

- [`docs/PROVIDERS.md`](docs/PROVIDERS.md) — AI provider setup and smoke
  tests.
- [`docs/MEMORY.md`](docs/MEMORY.md) — how agent persistent memory works.
- [`docs/SKILLS.md`](docs/SKILLS.md) — how to author and load skills.
- [`docs/testing.md`](docs/testing.md) — backend pytest and frontend lint.
- [`docs/MANUAL_QA.md`](docs/MANUAL_QA.md) — manual UI checklist.
- <http://localhost:8000/docs> — live OpenAPI reference (once the stack is
  up).
