# Agent persistent memory

Aquila uses a **hybrid** design:

1. **Canonical (OpenClaw-style) markdown** per user — source of truth for what the *model* sees in
   the system prompt: `MEMORY.md`, `USER.md`, `memory/YYYY-MM-DD.md`, optional `DREAMS.md` digest
   and `rubric.json` for dynamic importance routing.
2. **Postgres** (`agent_memories`) as an **index** for Settings UI, semantic recall, and
   `memory_search` / `recall_memory` when embeddings are configured.

See **[AGENTIC_MEMORY.md](./AGENTIC_MEMORY.md)** for the full V1 design (committee, consolidation,
autogenesis, adapter contract).

## Where it lives

| Layer | Location |
| ----- | -------- |
| Canonical root | `data/users/<user_id>/memory_workspace/` (or `AQUILA_USER_DATA_DIR`) — see [AGENTIC_MEMORY.md](./AGENTIC_MEMORY.md) |
| Service | `backend/app/services/canonical_memory.py`, `agent_memory_service.py` |
| Database (index) | `agent_memories` table |
| HTTP API | `GET/POST/DELETE /api/v1/memory`, `GET /api/v1/memory/digest`, `POST /api/v1/memory/reset` |
| Agent tools | `upsert_memory`, `recall_memory`, `memory_search`, `memory_get`, `list_memory`, `delete_memory` in `agent_tools.py` |
| Post-turn | `agent_memory_post_turn_service.py` (committee; legacy `heuristic` still available) |
| Runtime config | [AGENT_SETTINGS.md](./AGENT_SETTINGS.md) — `AGENT_MEMORY_POST_TURN_MODE` (`heuristic` \| `always` \| `committee` \| `adaptive`) |

## How the agent uses it

On every run the system prompt is **warmed** with a **markdown snapshot** (canonical) plus
tooling. The agent can call the memory tools; each successful `upsert_memory` updates both
Postgres and the per-user markdown KV section between `<!-- aqv1 -->` markers.

## Post-turn memory ingestion

After a completed reply, the backend may run a **multi-judge committee** (propose → filter) and
`upsert` rows — **not** a keyword list gate (except in `heuristic` legacy mode). Configure
defaults with `AGENT_MEMORY_POST_TURN_ENABLED` and `AGENT_MEMORY_POST_TURN_MODE`.

| Env | Meaning |
| --- | ------- |
| `AGENT_MEMORY_POST_TURN_ENABLED` | Default `true`. |
| `AGENT_MEMORY_POST_TURN_MODE` | Default `committee`. See [AGENTIC_MEMORY.md](./AGENTIC_MEMORY.md). |

## Memory flush before compaction

When chat history is trimmed, the backend may run a **memory flush** turn first. See
`AGENT_MEMORY_FLUSH_*` in [AGENT_SETTINGS.md](./AGENT_SETTINGS.md).

## Consolidation (periodic)

The ARQ worker runs `agent_memory_consolidation_tick` and periodically appends to `DREAMS.md` and
reindexes the database from canonical files. `AGENT_MEMORY_CONSOLIDATION_MINUTES` (default 360)
aligns the sweep on a minute clock.

## Hard reset

- **API:** `POST /api/v1/memory/reset` (authenticated) — deletes all DB rows and the user’s
  `memory_workspace` tree.
- **SQL (DB only):** `TRUNCATE agent_memories;` if you need to clear the index without removing files.

## Diagnostics

- [MEMORY_POST_TURN_DIAGNOSTICS.md](./MEMORY_POST_TURN_DIAGNOSTICS.md) — SQL + trace (extend with
  `adaptive_trivial_skip` and committee trace payloads as needed)
