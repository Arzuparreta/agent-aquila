# Agent persistent memory

Start with [VISION.md](./VISION.md) for *why* memory pieces exist, then use this
file for **storage mechanics** and [AGENTIC_MEMORY.md](./AGENTIC_MEMORY.md) for
deep architectural details (committee, consolidation, autogenesis).

Aquila uses a **hybrid** design:

1. **Canonical markdown** per user — source of truth for what the model sees in the
   system prompt: `MEMORY.md`, `USER.md`, `memory/YYYY-MM-DD.md` (key-value store),
   `DREAMS.md` (consolidation digest), `rubric.json` (dynamic importance weights).
2. **Postgres** (`agent_memories`) — an index for the Settings UI and semantic
   `recall_memory` when embeddings are configured.
3. **User context snapshot** (`user_ai_settings.agent_context_overview`) — a
   compressed TL;DR for non-chat agent turns, distinct from the full memory block.

See [AGENTIC_MEMORY.md](./AGENTIC_MEMORY.md) for the full design.

## Where it lives

| Layer | Location |
| ----- | -------- |
| Canonical root | `data/users/<user_id>/memory_workspace/` (or `AQUILA_USER_DATA_DIR`) |
| User context snapshot | `user_ai_settings.agent_context_overview` |
| Service | `backend/app/services/canonical_memory.py`, `agent_memory_service.py` |
| Database (index) | `agent_memories` table |
| HTTP API | `GET/POST/DELETE /api/v1/memory`, `GET /api/v1/memory/digest`, `POST /api/v1/memory/reset` |
| Agent tools | `upsert_memory`, `recall_memory`, `memory_get`, `list_memory`, `delete_memory` (see `agent_tools.py`) |
| Post-turn | `agent_memory_post_turn_service.py` |
| Runtime config | [AGENT_SETTINGS.md](./AGENT_SETTINGS.md) — `AGENT_MEMORY_POST_TURN_MODE` |

## How the agent uses memory

On every run the system prompt is warmed with the canonical markdown snapshot
and tooling. The agent can call the memory tools; each `upsert_memory`
updates both Postgres and the per-user markdown KV section.

Key conventions (see AGENTS.md for the agent-facing rules):

- `memory.durable.*` — long-term facts (OpenClaw `MEMORY.md`)
- `memory.daily.YYYY-MM-DD` — day-scoped notes
- `user.profile.*` — identity and preferences (OpenClaw `USER.md`)
- `agent.identity.*` — the agent's own display name

## Post-turn memory ingestion

After a completed reply, the backend may run a memory extraction pass —
the agent's LLM call extracts durable facts and upserts rows. Configure
defaults with `AGENT_MEMORY_POST_TURN_ENABLED` and `AGENT_MEMORY_POST_TURN_MODE`
(see [AGENT_SETTINGS.md](./AGENT_SETTINGS.md)).

## Memory flush before compaction

When chat history is trimmed, the backend may run a separate **memory flush** turn
first, to persist important facts from about-to-be-dropped messages.
This uses `AGENT_MEMORY_FLUSH_*` settings.

## Consolidation (periodic)

The ARQ worker runs a consolidation pass on a minute-level cron. Each pass
appends a digest line to `DREAMS.md` and reindexes the database from
canonical files.

- Default interval: 360 minutes (6-hour slot)
- Disable: `AGENT_MEMORY_CONSOLIDATION_ENABLED=false`

## Hard reset

- **API:** `POST /api/v1/memory/reset` — deletes all DB rows and the user's
  `memory_workspace` tree.
- **SQL (DB only):** `TRUNCATE agent_memories;` — clears the index without
  removing files.
