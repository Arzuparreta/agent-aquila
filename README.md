
# Agent Aquila

<img src="docs/branding/aquila-simpler.png" alt="Agent Aquila" width="80" style="display: block; margin: 0 auto;">

Your self-hosted personal operations assistant: **broad connector surface**, **context-first** automated wakes, and a **lean harness** (scoped tool palettes and user context snapshot) so you are not paying the full tool catalogue on every background ping.

Agent Aquila helps you manage mail, calendar, files, and more across **Gmail, Calendar, Drive, Outlook, Teams**, and many other linked providers while keeping control where it belongs: **your accounts, your keys, your machine**. Multi-channel is a first-class goal (web UI plus gateway and channel adapters). See [`docs/VISION.md`](docs/VISION.md) for how this compares to the harnesses like openclaw and what Aquila optimizes for.

Persistent **memory** and reusable **skills** (markdown playbooks in `backend/skills/`) keep behavior consistent across sessions. An optional heartbeat scheduler can wake the agent on a cadence; by default it does **not** scan Gmail (`AGENT_HEARTBEAT_CHECK_GMAIL=false`) to avoid background quota burn (details in [`docs/GMAIL_QUOTA.md`](docs/GMAIL_QUOTA.md)).

---

## Quick Start

```bash
cp .env.example .env
docker compose up --build
```

If you run the **frontend on the host** (for example `cd frontend && npm install && npm run dev`), Next.js will generate `frontend/next-env.d.ts` for TypeScript. That file is generated and is **not** kept in git, so run `npm install` in `frontend/` after a fresh clone if your editor complains about missing types.

| | URL |
|--|--|
| App | <http://localhost:3002> |
| API | <http://localhost:8000/docs> |
| Postgres | `localhost:5433` |
| Redis | `localhost:6379` |

Migrations run when the API starts. **First boot on an old database** may apply a destructive migration that drops legacy mirror/CRM tables, so back up if that data matters.

If startup fails or you see frontend `500` errors, use [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md).

Connect providers under **Settings → External connectors**. If you already had Gmail linked, you may need to reconnect once so the grant includes `gmail.settings.basic` (filters for mute/spam); the UI shows a banner when scopes are missing.

---

## What You Get

- **Chat** — agent turns with tools against your connected services.
- **Inbox** — one list, Gmail search, pagination, actions wired to the real mailbox (including mute/spam via filters).
- **Settings** — connectors, AI provider, memory viewer, skills list.

---

## Safety Defaults

Sending or replying **from the agent** is the only action that asks for approval by default. Other actions run directly through OAuth-backed provider calls.

You can tune this policy in [`backend/app/services/agent_tools.py`](backend/app/services/agent_tools.py) (`_PROPOSAL_TOOLS`) and [`backend/app/services/capability_registry.py`](backend/app/services/capability_registry.py).

---

## Add a Capability

1. Describe the tool in [`backend/app/services/agent_tools.py`](backend/app/services/agent_tools.py) (`AGENT_TOOLS`).
2. Handle it in [`backend/app/services/agent_service.py`](backend/app/services/agent_service.py) (`AgentService._DISPATCH` / `_dispatch_tool`).

---

## Repo Map

| Path | Role |
|------|------|
| [`backend/`](backend/) | FastAPI, SQLAlchemy, Alembic, ARQ worker, `skills/`, `agent_workspace/` |
| [`frontend/`](frontend/) | Next.js app |
| [`docker-compose.yml`](docker-compose.yml) | `db`, `redis`, `backend`, `worker`, `frontend` |
| [`.env.example`](.env.example) | Environment template |

---

## Documentation

- [`docs/VISION.md`](docs/VISION.md) — product direction, harness goals, and doc map  
- [`docs/PROVIDERS.md`](docs/PROVIDERS.md) — models and provider setup  
- [`docs/MEMORY.md`](docs/MEMORY.md) — persistent memory  
- [`docs/AGENT_SETTINGS.md`](docs/AGENT_SETTINGS.md) — agent runtime tunables (env + per-user)  
- [`docs/SKILLS.md`](docs/SKILLS.md) — authoring skills  
- [`docs/testing.md`](docs/testing.md) — tests  
- [`docs/MANUAL_QA.md`](docs/MANUAL_QA.md) — manual checks  
- [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) — startup and runtime failure patterns  
- [`docs/GMAIL_QUOTA.md`](docs/GMAIL_QUOTA.md) — Gmail API usage, heartbeat, SQL to audit tool calls  
- [`docs/GMAIL_WATCH.md`](docs/GMAIL_WATCH.md) — design: Gmail Pub/Sub / `users.watch` (automation)  
- [`docs/INTEGRATIONS_ROADMAP.md`](docs/INTEGRATIONS_ROADMAP.md) — integration backlog (not a release promise)  

---

## Version Sync From GitHub Releases

This repository treats the GitHub release/tag as the version source of truth.

- Workflow: `.github/workflows/sync-version-from-release.yml`
- Expected tag format: `vX.Y.Z` (also accepts `X.Y.Z`)
- On release publish (or matching tag push), the workflow syncs:
  - `frontend/package.json` -> `version`
  - `backend/pyproject.toml` -> `[project].version`
  - `backend/app/main.py` -> `FastAPI(..., version="...")`
- If the tag is invalid, or any target cannot be updated deterministically, the workflow fails fast.

Local checks:

```bash
python3 scripts/sync_version_from_tag.py --tag v0.0.3 --dry-run
python3 scripts/sync_version_from_tag.py --tag refs/tags/v0.0.3 --print-only
```
