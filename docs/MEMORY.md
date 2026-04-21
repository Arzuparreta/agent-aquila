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
| Agent tools | `upsert_memory`, `recall_memory`, `memory_search`, `memory_get`, `list_memory`, `delete_memory` in `agent_tools.py` |
| Settings UI | **Settings → Memoria del agente** (`frontend/src/components/features/memory/memory-section.tsx`) |
| Diagnostics | [MEMORY_POST_TURN_DIAGNOSTICS.md](./MEMORY_POST_TURN_DIAGNOSTICS.md) — SQL + trace event queries |


Each row is `(user_id, key, content, importance, tags, embedding,
embedding_model, meta, created_at, updated_at)` with a `UNIQUE (user_id, key)`
constraint, so the agent always upserts on `key`.

## How the agent uses it

On every run the system prompt is **warmed** with the most recent /
highest-importance memories for that user. The agent can then call:

- `upsert_memory(key, content, importance?, tags?)` — write or upsert. The
  service computes an embedding (when an embedding provider is configured) so
  later `recall_memory` queries can be semantic.
- `recall_memory(query, limit?)` / `memory_search` — semantic + recency search across the
  user's memories (`memory_search` is an alias).
- `memory_get(key)` — fetch full content for one key.
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

## OpenClaw-style conventions (keys)

The agent is encouraged to use predictable key prefixes (same spirit as OpenClaw `MEMORY.md`, `USER.md`, `memory/YYYY-MM-DD.md`):

- `memory.durable.*` — stable long-term facts.
- `memory.daily.YYYY-MM-DD` — day-scoped observations.
- `user.profile.*` — identity, tone, and preferences.

Use optional `tags` for the same concepts when filtering with `recall_memory`.

## Memory flush before compaction

When chat history is trimmed (see `AGENT_HISTORY_TURNS` / `AGENT_THREAD_COMPACT_AFTER_PAIRS`), the backend may run a **memory flush** turn first: a short internal agent run that only has memory tools, fed the transcript of messages about to be dropped. Configure with `AGENT_MEMORY_FLUSH_*` env vars.

### How this differs from OpenClaw’s “flush before compaction”

OpenClaw runs a silent pass **before** summarizing so that important context in the conversation block being compacted is written to disk first. Aquila’s pre-trim flush is **similar in spirit** but **only receives the oldest segment** of the thread: the messages that no longer fit in the sliding window (`preview_memory_flush_dropped` in `chat_service.py`). It does **not** include the **latest** user/assistant exchange until those turns have aged out of the window. **Short threads** (fewer messages than the history cap) never produce a dropped segment, so **no** flush runs at all.

That is why durable facts stated in the **current** turn (for example “your name is Agente Áquila”) are **not** covered by this mechanism alone. For that, see **post-turn memory ingestion** below.

## Post-turn memory ingestion

After a completed agent reply, the backend may run a **structured extraction** pass (single JSON completion, not the full tool loop) on the **last user message + assistant reply**, then **upsert** into `agent_memories`. This aligns with OpenClaw’s idea that important dialogue should be **persisted explicitly**, without relying on the main chat turn to call `upsert_memory`.

Configure with **deployment defaults** (environment variables) and optional **per-user overrides** in the app (**Settings → Agent behavior**), stored in `user_ai_settings.agent_runtime_config`. See [AGENT_SETTINGS.md](./AGENT_SETTINGS.md).

| Env | Meaning |
| --- | --- |
| `AGENT_MEMORY_POST_TURN_ENABLED` | Default `true`. Set `false` to disable the extra LLM call entirely. |
| `AGENT_MEMORY_POST_TURN_MODE` | `heuristic` (default): only run extraction when heuristics suggest memory-worthy content (name assignment, “remember”, preferences, etc.). `always`: run extraction after every completed turn (higher cost). |

When `AGENT_MEMORY_POST_TURN_MODE=heuristic`, most turns skip extraction without calling the provider.

## Privacy

Memories live in **your** Postgres. **Warmup** (injecting existing rows into the system prompt) only repeats what the chat already sent to the provider in that turn. **Post-turn extraction** (when enabled and not skipped by heuristics) sends the last user + assistant strings to the provider for a JSON extraction call. The main agent loop also sends full chat context to the provider as usual.

To wipe all stored memories:

```bash
docker compose exec db psql -U app -d app -c "TRUNCATE agent_memories;"
```

