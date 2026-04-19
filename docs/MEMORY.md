# Agent persistent memory

Agent Aquila has a small **key/value scratchpad** that persists across runs,
threads and even browser sessions. It exists so the agent can remember things
about you that don't fit anywhere else: preferences, naming conventions,
project context, "always do X for sender Y", etc.

This is intentionally **not** a chat log, not a CRM, and not a vector
database of your emails — it's a private notebook the agent owns.

## Where it lives

| Layer       | Location                                                            |
| ----------- | ------------------------------------------------------------------- |
| Database    | `agent_memories` table (created by Alembic migration `0018`)        |
| Model       | `backend/app/models/agent_memory.py`                                |
| Service     | `backend/app/services/agent_memory_service.py`                      |
| HTTP API    | `backend/app/routes/memory.py` — `GET/POST/DELETE /memory`          |
| Agent tools | `upsert_memory`, `recall_memory`, `list_memory`, `delete_memory` in `agent_tools.py` |
| Settings UI | **Settings → Memoria del agente** (`frontend/src/components/features/memory/memory-section.tsx`) |

Each row is `(user_id, key, content, importance, tags, embedding,
embedding_model, meta, created_at, updated_at)` with a `UNIQUE (user_id, key)`
constraint, so the agent always upserts on `key`.

## How the agent uses it

On every run the system prompt is **warmed** with the most recent /
highest-importance memories for that user. The agent can then call:

- `upsert_memory(key, content, importance?, tags?)` — write or upsert. The
  service computes an embedding (when an embedding provider is configured) so
  later `recall_memory` queries can be semantic.
- `recall_memory(query, limit?)` — semantic + keyword search across the
  user's memories.
- `list_memory(tag?, limit?)` — most-recent-first listing, optionally
  filtered by a tag.
- `delete_memory(key)` — hard-delete by key.

Importance is a small integer (0–10). Higher importance memories are more
likely to make it into the system-prompt warmup.

## When to use it

Good keys (the agent will use these naturally):

- `prefs.timezone` → `"Europe/Madrid"`
- `prefs.signature` → `"Saludos, — Arsu"`
- `routing.support` → `"Forward stripe.com bills to accounting@example.com"`
- `project.acme.context` → `"Acme is the Q3 launch — budget owner is Sara."`

Bad keys (these belong somewhere else):

- A whole email body. The agent should fetch it live with `gmail_get_message`.
- A list of all your contacts. There is no CRM any more — read live from
  Gmail / Calendar.
- Per-message labels. Use Gmail's own labels via `gmail_modify_message`.

## Inspecting and pruning from the UI

**Settings → Memoria del agente** lists every memory the agent has stored for
you, newest first, with importance and tags. You can delete any row from
there; the agent will simply re-create it next time if it still considers it
worth remembering.

## Privacy

Memories live in **your** Postgres only. They are never sent to the LLM
provider unless the agent explicitly includes them in a prompt (which is what
the warmup does). If you want to wipe everything, truncate the table:

```bash
docker compose exec db psql -U app -d app -c "TRUNCATE agent_memories;"
```
