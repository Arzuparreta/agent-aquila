
# 🦅 Agent Aquila — Life & Buisness Manager

```
        ⠀⠀⠀⠀⠀⠀⠀⠐⣶⠦⣄⣐⢤⡉⢷⡀⢹⡇⢠⣿⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
        ⠀⠀⠀⠀⠀⠀⠀⠀⢹⣆⣯⣽⣿⣿⣷⣽⣦⣿⡌⣿⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
        ⠀⠀⠀⠀⠀⠀⠀⠀⠈⡵⣿⣿⣿⣿⣿⡟⣠⠟⠋⡉⠩⣿⣖⠶⣄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
        ⠀⠀⠀⠀⠀⠀⠀⠀⠀⠉⠸⣿⣿⣿⣿⣯⣿⡷⠚⠿⠒⠛⠛⠛⠚⠷⣄⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
        ⢠⣦⣤⣤⣤⣤⣀⣤⣄⣤⠴⠖⠛⡭⡍⣉⣠⣤⣤⣤⠬⣁⡀⠤⠠⢾⡞⣩⣷⡶⢤⣤⣤⣀⠀⠀⠀⠀⠀
        ⢾⣻⣯⣽⣷⣾⣿⣿⣿⣿⣷⣤⣄⣀⣶⣿⣿⣦⣴⣆⣨⣑⣲⡿⢛⣯⣻⣽⢻⣧⣌⣹⣟⡛⠛⣆⠀⠀⠀
        ⠀⠈⠉⠀⠈⠉⠉⠉⠉⠉⠉⠛⠛⠛⢯⣿⣿⣿⣟⠉⠉⣿⡿⠛⠛⠿⢸⢿⣿⡿⠟⠛⠛⠉⠙⠋⠀⠀⠀
   ⠀⠀     ⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢿⢿⣿⣿⣿⣿⣾⠿⣯⣁⣸⣤⣮⡿⢽⣧⡀⠀⠀⠀⠀⠀⠀⠀⠀
   ⠀⠀⠀⠀⠀⠀     ⠀⠀⠀⠀⠀⠀⠀⠀⠈⠳⡿⣿⣿⣿⣿⣿⣾⣻⣦⡀⠉⣟⠲⣟⣷⡀⠀⠀⠀⠀⠀⠀⠀
   ⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀     ⠀⠀⠀⠀⠀⠀⠙⢾⢻⣿⣿⣿⣿⣿⣎⢿⣷⣰⣖⡸⢻⣿⣄⠀⠀⠀⠀⠀⠀
⠀⠀   ⠀⠀⠀⠀⠀⠀⠀⠀⠀     ⠀⠀⠀⠀⠀⠀⠈⠻⣍⣿⣿⣿⣿⣿⣯⣿⢿⣶⣭⣿⣿⣍⣧⠀⠀⠀⠀⠀
⠀⠀⠀⠀   ⠀⠀⠀⠀⠀⠀⠀⠀     ⠀⠀⠀⠀⠀⠀⠀⠀⠈⢿⢛⠛⣛⣿⣿⣷⣿⢻⡿⣿⣿⡇⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀   ⠀⠀⠀⠀⠀⠀⠀     ⠀⠀⠀⠀⠀⠀⠀⠀⠈⢧⣉⣥⣾⣿⣿⣿⣷⣛⣿⣿⣿⠄⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀   ⠀⠀⠀⠀⠀⠀⠀     ⠀⠀⠀⠀⠀⠀⠀⠀⠻⣿⣽⣿⣿⣿⣿⣿⣿⣿⣿⡆⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀   ⠀⠀⠀⠀⠀⠀⠀     ⠀⠀⠀⠀⠀⠀⠀⠘⠿⢿⣿⣿⣿⣿⣿⣯⣿⣿⡀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀   ⠀⠀⠀⠀⠀⠀     ⠀⠀⠀⠀⠀⠀⠀⠀⠘⠿⣿⣿⠻⣿⡿⣿⢿⣷⣤⣤⡤
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀   ⠀⠀⠀⠀⠀⠀⠀     ⠀⠀⠀⠀⠀⠀⠀⣿⠇⠀⢻⣇⠙⠣⣌⣻⣏⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
```

**Self-hosted agentic harness delivered as a personal assistant, focused on observability and control** — your accounts, your keys, your machine. Chat with an agent that can work in **Gmail, Calendar, Drive, Outlook, and Teams** the same way you would.

Persistent **memory** (what to remember across sessions) and **skills** (markdown recipes in `backend/skills/`) keep behaviour consistent. An optional **heartbeat** job can wake the agent on a schedule. By default the heartbeat **does not** instruct the model to scan Gmail (`AGENT_HEARTBEAT_CHECK_GMAIL=false`), so background ticks do not burn Gmail API quota; see [`docs/GMAIL_QUOTA.md`](docs/GMAIL_QUOTA.md).

---

### Run it

```bash
cp .env.example .env
docker compose up --build
```

| | URL |
|--|--|
| App | <http://localhost:3002> |
| API | <http://localhost:8000/docs> |
| Postgres | `localhost:5433` |
| Redis | `localhost:6379` |

Migrations run when the API starts. **First boot on an old database** may apply a destructive migration that drops legacy mirror/CRM tables — back up if you care about that data.

### Troubleshooting: backend exits, UI 500 / proxy error

| What you see | What to check |
|----------------|---------------|
| `backend` container **Exited (1)** right after `alembic upgrade head` | `docker logs <backend-container>` |
| Log: **`StringDataRightTruncationError`**, **`character varying(32)`**, SQL mentions **`alembic_version`** | PostgreSQL’s `alembic_version.version_num` was too short for a migration’s `revision` string. **`backend/alembic/env.py`** widens that column automatically before upgrades; if the error returns, confirm that helper was not removed or bypassed. |
| UI: **Server error (500)** and text about **Next.js proxy** / **`BACKEND_INTERNAL_URL`** | Usually the API never started—check **backend** logs first, not only `frontend`. |
| Dashboard or chat shows **500** / *Internal server error* while the API is up | Often **pending DB migrations** after `git pull`. Run `cd backend && alembic upgrade head` (Compose: `docker compose up --build backend`). The API may also return **503** with *schema_out_of_date* and explicit instructions. On startup, the backend **fails fast** if `user_ai_settings.agent_processing_paused` is missing—check `docker logs` for the Alembic hint. To bypass the probe (dev only): `AQUILA_SKIP_SCHEMA_PROBE=1`. |
| Chat **stalls** on “…” after sending, or bulk Gmail tasks **never finish** | Ensure **`worker`** is running (`arq app.worker.WorkerSettings`), **`REDIS_URL`** is set, and **`AGENT_ASYNC_RUNS`** is not disabled. Chat agent turns are queued to the worker by default so long runs are not tied to a single HTTP request. |
| **Step budget exceeded** | Raise **`AGENT_MAX_TOOL_STEPS`** (see `.env.example`) or use fewer tool rounds; **`gmail_trash_bulk_query`** clears an inbox in one tool for “delete everything”-style asks. |

**Grep-friendly keywords for agents:** `StringDataRightTruncation`, `alembic_version`, `_widen_alembic_version_num`. Regression test: `backend/tests/test_alembic_version_column.py`.

Connect providers under **Settings → External connectors**. If you already had Gmail linked, you may need to reconnect once so the grant includes `gmail.settings.basic` (filters for mute/spam); the UI shows a banner when scopes are missing.

---

### What you get in the UI

- **Chat** — agent turns with tools against your connected services.
- **Inbox** — one list, Gmail search, pagination, actions wired to the real mailbox (including mute/spam via filters).
- **Settings** — connectors, AI provider, memory viewer, skills list.

---

### Default gate on outbound mail

Sending or replying **from the agent** is the only action that shows an approval card by default — everything else goes straight through OAuth to the provider. That policy is a few lines in [`backend/app/services/agent_tools.py`](backend/app/services/agent_tools.py) (`_PROPOSAL_TOOLS`) and [`backend/app/services/capability_registry.py`](backend/app/services/capability_registry.py); tighten or loosen it however you like.

---

### Add a capability

1. Describe the tool in [`backend/app/services/agent_tools.py`](backend/app/services/agent_tools.py) (`AGENT_TOOLS`).
2. Handle it in [`backend/app/services/agent_service.py`](backend/app/services/agent_service.py) (`AgentService._DISPATCH` / `_dispatch_tool`).

---

### Repo map

| Path | Role |
|------|------|
| [`backend/`](backend/) | FastAPI, SQLAlchemy, Alembic, ARQ worker, `skills/`, `agent_workspace/` |
| [`frontend/`](frontend/) | Next.js app |
| [`docker-compose.yml`](docker-compose.yml) | `db`, `redis`, `backend`, `worker`, `frontend` |
| [`.env.example`](.env.example) | Environment template |

---

### Docs

- [`docs/PROVIDERS.md`](docs/PROVIDERS.md) — models and provider setup  
- [`docs/MEMORY.md`](docs/MEMORY.md) — persistent memory  
- [`docs/SKILLS.md`](docs/SKILLS.md) — authoring skills  
- [`docs/testing.md`](docs/testing.md) — tests  
- [`docs/MANUAL_QA.md`](docs/MANUAL_QA.md) — manual checks  
- [`docs/GMAIL_QUOTA.md`](docs/GMAIL_QUOTA.md) — Gmail API usage, heartbeat, SQL to audit tool calls  
- [`docs/GMAIL_WATCH.md`](docs/GMAIL_WATCH.md) — design: Gmail Pub/Sub / `users.watch` (Phase B)  
