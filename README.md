
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

Persistent **memory** (what to remember across sessions) and **skills** (markdown recipes in `backend/skills/`) keep behaviour consistent. An optional **heartbeat** job can wake the agent on a schedule.

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
