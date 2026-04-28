# 🔍 Agent Aquila — Refactor Plan

> **Purpose:** This document records a complete audit of the Agent Aquila codebase and a prioritized
> plan to remove cruft, simplify architecture, and improve reliability without losing functionality.
> It is written for another agent or human engineer who needs to understand *exactly what exists*,
> *why it's a problem*, and *how to fix it* — with precise file locations, line counts, and
> code snippets.

---

## 1. Codebase Snapshot (as of cleanup)

| Layer | Files | Lines | Notes |
|-------|-------|-------|-------|
| **Backend app code** | 166 `.py` files | ~28K | `backend/app/` only |
| **Backend services** | 95 files | | Largest domain |
| **Routes** | 30 files | | FastAPI endpoints |
| **Models** | 20 files | | SQLAlchemy ORM |
| **Connectors (clients)** | 25 files | | Gmail, Calendar, Drive, etc. |
| **Migrations** | 36 Alembic files | | Migration history |
| **Skills** | 3 directories | | `backend/skills/` |
| **Agent workspace** | 2 files | | `backend/agent_workspace/` (SOUL.md, AGENTS.md) |

### Biggest Files (the pain points)

| File | Lines | What's wrong |
|------|-------|-------------|
| `backend/app/services/agent_service.py` | **3,588** | Contains EVERYTHING: tool handlers, ReAct loop, connection resolution, memory flushing, proposals, tracing, Gmail mutations, credential submission — all in one class |
| `backend/app/services/agent_tools.py` | **1,638** | 60+ tool definitions with verbose descriptions, schema helpers, palette mode filtering |
| `backend/app/services/connector_setup_service.py` | 731 | Connector onboarding — mostly fine |
| `backend/app/services/skills_service.py` | 681 | Skills management — most is fine |
| `backend/app/routes/threads.py` | 810 | Chat thread management — fine |
| `backend/app/services/chat_service.py` | 500 | Chat service — fine |

---

## 2. Architectural Problems (Root Causes)

### 2.1 The Monolith: `agent_service.py` (3,588 lines)

**What's inside this file:**

| Section | Approx Lines | What it does |
|---------|-------------|-------------|
| Imports (line 1–120) | 120 | Imports half the codebase |
| `_IDENTITY_AND_MEMORY_TOOL_NUDGE` | 14 | Hardcoded reminder string injected into prompt |
| `get_tool_palette()` | 15 | Synchronous tool palette (unused in hot path) |
| `resolve_turn_tool_palette()` | 45 | Resolves filtered tool palette per turn (has 4 DIAG debug log lines) |
| `_conversation_trace_snapshot()` | 30 | Compact JSON of recent messages |
| `_trim_step_payload_for_client()` | 35 | Truncate step payloads for HTTP response |
| `_approx_prompt_tokens()` | 7 | Rough token estimate |
| `_is_context_overflow()` | 10 | Check for context overflow errors |
| `_reduce_conversation_for_budget()` | 80 | Context compression logic |
| `_assistant_message_from()` | 18 | Re-encode assistant response |
| Connection resolution helpers (16 methods) | ~200 | `_resolve_connection`, `_gmail_client`, `_calendar_client`, etc. |
| Gmail tools (~16 handlers) | ~500 | `gmail_list_messages`, `gmail_get_message`, `gmail_get_thread`, etc. |
| Calendar tools (~4 handlers) | ~120 | `calendar_list_events`, `calendar_list_calendars`, `calendar_create_event` |
| Drive tools (~3 handlers) | ~80 | `drive_list_files`, `drive_upload_file`, `drive_share_file` |
| Sheets/Docs tools (~2 handlers) | ~60 | `sheets_read_range`, `docs_get_document` |
| YouTube tools (~6 handlers) | ~150 | `youtube_list_my_channels`, `youtube_search_videos`, etc. |
| Tasks tools (~5 handlers) | ~120 | `tasks_list_tasklists`, `tasks_list_tasks`, etc. |
| People tools (~1 handler) | ~20 | `people_search_contacts` |
| GitHub tools (~2 handlers) | ~40 | `github_list_my_repos`, `github_list_repo_issues` |
| Slack tools (~2 handlers) | ~40 | `slack_list_conversations`, `slack_get_conversation_history` |
| Linear tools (~2 handlers) | ~30 | `linear_list_issues`, `linear_get_issue` |
| Notion tools (~2 handlers) | ~30 | `notion_search`, `notion_get_page` |
| Telegram tools (~3 handlers) | ~60 | `telegram_get_me`, `telegram_get_updates`, `telegram_send_message` |
| Discord tools (~3 handlers) | ~60 | `discord_list_guilds`, `discord_list_guild_channels`, `discord_get_channel_messages` |
| iCloud Drive tools (~2 handlers) | ~50 | `icloud_drive_list_folder`, `icloud_drive_get_file` |
| iCloud Contacts tools (~2 handlers) | ~50 | `icloud_contacts_list`, `icloud_contacts_search` |
| iCloud Reminders/Notes/Photos (~3 handlers) | ~90 | `icloud_reminders_list`, `icloud_notes_list`, `icloud_photos_list` |
| Credential submission tools (~7 handlers) | ~100 | `submit_whatsapp_credentials`, `submit_github_credentials`, etc. |
| Outlook/Teams tools (~4 handlers) | ~80 | `outlook_list_messages`, `outlook_get_message`, `teams_list_teams`, etc. |
| Memory tools (~5 handlers) | ~100 | `upsert_memory`, `delete_memory`, `list_memory`, `recall_memory`, `memory_get` |
| Skills/workspace tools (~4 handlers) | ~50 | `list_skills`, `load_skill`, `list_workspace_files`, `read_workspace_file` |
| `describe_harness` (1 handler) | ~70 | Introspects deployment state |
| `list_connectors` (1 handler) | ~15 | Lists connector connections |
| `get_session_time` (1 handler) | ~10 | Returns current time in user timezone |
| Web search/fetch tools (~2 handlers) | ~30 | `web_search`, `web_fetch` |
| Connector setup tools (~3 handlers) | ~50 | `start_connector_setup`, `submit_connector_credentials`, `start_oauth_flow` |
| Scheduled task tools (~4 handlers) | ~200 | `scheduled_task_create`, `scheduled_task_list`, `scheduled_task_update`, `scheduled_task_delete` |
| Proposal tools (~8 handlers) | ~250 | `propose_email_send`, `propose_email_reply`, `propose_whatsapp_send`, etc. |
| `_insert_proposal()` + `_idem()` | ~40 | Proposal creation helper |
| `_DISPATCH` + `_dispatch_tool()` | ~60 | Tool dispatch routing |
| `run_memory_flush_turn()` | ~70 | Runs agent turn before thread compaction |
| `run_agent_invalid_preflight()` | ~40 | Preflight checks (paused, disabled, no API key) |
| `abort_pending_run_queue_unavailable()` | ~25 | Worker queue fallback |
| `create_pending_agent_run()` | ~15 | Creates AgentRun record |
| `run_agent()` | ~50 | Public entry point |
| `_execute_agent_loop()` | **~650** | The ReAct loop — main agent logic |
| `_load_steps()`, `_to_read()`, `list_recent_runs()`, `list_trace_events()`, `get_run()` | ~100 | Read helpers |

**Problems:**

1. **Every developer must read 3,588 lines** to understand any change. A bug fix in Gmail
   handler requires reading the entire file.
2. **Import explosion** — line 1–120 imports half the codebase, making every edit trigger
   circular-import warnings or require careful ordering.
3. **No module-level cohesion** — Gmail handlers are 500 lines mixed in with scheduled tasks.
   There is no natural boundary between concerns.
4. **Static methods everywhere** — `_tool_XXX` are static methods on a class, requiring `AgentService._XXX`
   for access, making unit testing harder (mock the whole class instead of individual functions).
5. **Connection resolution is duplicated** — every tool handler repeats:
   ```python
   row = await _resolve_connection(db, user, args, GMAIL_TOOL_PROVIDERS, label="Gmail")
   client = await _gmail_client(db, row)
   ```
   This pattern repeats 20+ times across different tool handler functions.

### 2.2 System Prompt Bloat

**Current prompt assembly (from `build_system_prompt()` in `agent_workspace.py`):**

```
1. SOUL.md (~500 chars) — Persona definition
2. AGENTS.md (~5,300 chars) — Rules of engagement
3. Context-first hint (if non-chat profile)
4. Injected user context block
5. Harness facts section (if enabled)
6. Tool section (full JSON or quick index — varies by harness mode)
7. Epistemic priority host ~500 chars
8. Memory blob (up to ~12K chars — top N memories)
9. DateTime context section (~100 chars)
10. Thread context hint (if present)
```

**Token cost analysis per turn:**

| Component | Tokens (approx) | Notes |
|-----------|----------------|-------|
| SOUL.md | ~125 | Stable |
| AGENTS.md | ~1,400 | Stable |
| Epistemic priority | ~125 | Stable |
| Gmail playbook | ~175 | Only in full tier |
| Tool quick index | ~800–1,500 | 50+ tools × ~30 chars avg |
| Tool JSON embed (prompted mode) | ~8,000–15,000 | **Entire tool schema as JSON in text** |
| Memory blob | ~500–3,000 | Varies by stored memories |
| Harness facts | ~80 | Stable |
| DateTime context | ~25 | Stable |
| System prompt total (native, full) | ~3,000–4,500 | Per turn |
| System prompt total (prompted) | ~10,000–20,000 | **Per turn** |
| + Conversation history | Varies | Additional tokens every turn |
| **Total per LLM call** | **~5,000–25,000** | |

**Problems:**

1. Every tool description averages **150–300 characters**. With 60+ tools, the quick index
   alone is 800–1,500 tokens. These descriptions are read on every single turn.
2. In **prompted mode**, the entire tool JSON schema is embedded literally in the system prompt,
   adding 8,000–15,000 tokens per request — the worst case.
3. The `prompt_tier` system (`full`/`minimal`/`none`) only removes the Gmail playbook and
   epistemic priority — it doesn't reduce the critical problem: **every tool description is read every turn**.
4. `build_harness_facts_markdown()` adds more boilerplate: tool count, max steps,
   harness mode, prompt tier, palette mode, connector gating, linked providers, paused status.
   Most of this is runtime metadata the model already knows from the API.

### 2.3 Dual Harness + Auto-Fallback

**Three execution paths:**

| Path | How it works | Code location |
|------|-------------|---------------|
| `native` | Uses `tools=` parameter, `tool_choice="required"` | `chat_turn_native()` in `agent_harness/native.py` |
| `prompted` | Embeds tool JSON in system prompt, parses `<json>...</json>` blocks | `chat_completion_full()` + `parse_tool_calls_from_content()` in `agent_harness/prompted.py` |
| `auto-fallback` | Native first, if model returns no tool calls: switch to prompted once | L850-880 in `agent_service.py` |

**The fallback logic (lines ~850–880 of `agent_service.py`):**

```python
if (
    effective == "native"
    and allow_native_fallback
    and not response.has_tool_calls
):
    effective = "prompted"
    allow_native_fallback = False
    system_prompt = await _assemble_system("prompted")
    conversation[0] = {"role": "system", content: system_prompt}
    # ... redo the entire LLM call in prompted mode ...
```

**Problems:**

1. The ReAct loop has **three different code paths** for feeding results back:
   - Native: `conversation.append({"role": "tool", "tool_call_id": ..., "content": ...})`
   - Prompted: `conversation.append({"role": "user", "content": format_tool_results_for_prompt(...)})`
   - Fallback: reassembles system prompt, redoes LLM call inside the loop
2. Messages are shaped differently for native vs prompted:
   - Native: assistant → `ChatResponse` → `_assistant_message_from()` → `{"role": "assistant", ...}`
   - Prompted: `{"role": "assistant", "content": raw_text}`
3. `parse_tool_calls_from_content()` does regex-based JSON extraction — fragile, model-dependent.
4. The fallback is a **one-shot**: it only happens once per run (`allow_native_fallback = False`).
   If prompted mode also fails, there's no further recovery.
5. **`prompted` harness adds ~300 lines** of `agent_harness/prompted.py` plus the `parse_json_object()`
   function in `llm_client.py` that does fence-stripping regex extraction.

### 2.4 Over-Engineered Post-Turn Memory Extraction

**Current multi-tier system:**

```
agent_memory_post_turn_service.py (455 lines)
├─ heuristic     → regex check + single LLM call
├─ adaptive      → heuristic + trivial-skip before LLM call  
├─ committee     → multi-judge LLM-based extraction
├─ rubric_adaptation → committee + learns from approval rate
└─ always        → LLM call every completed turn
```

**Supporting files:**

| File | Lines | Purpose |
|------|-------|---------|
| `agent_memory_post_turn_service.py` | 455 | Main orchestration, mode routing, extraction logic |
| `agent_memory_committee.py` | 261 | Multi-judge extraction with 2 LLM calls |
| `agent_rubric.py` | ~100 | Rubric tracking and adaptation |
| `agent_user_context.py` | ~150 | User context snapshots (refreshed after memory writes) |

**Flow:**

```
Agent turn completes → maybe_ingest_post_turn_memory()
    → Checks rt.agent_memory_post_turn_enabled
    → Checks mode (heuristic/adaptive/committee/always)
    → Runs heuristic regex check (if heuristic/adaptive)
    → Calls LLM 1-2x for memory extraction
    → Normalizes JSON → upserts to AgentMemoryService
    → Refreshes user context snapshot
    → Emits trace events (start/skipped/completed)
```

**Problems:**

1. **Second LLM call per turn** — doubles API cost for every agent run.
2. **Committee mode uses 2 LLM calls** — proposer + judge pass.
3. **Rubric adaptation** tracks "approval_count" from upserts and adjusts the rubric over time —
   this is ML research complexity for a personal assistant.
4. **455 lines** of mode-switching, trace emission, and extraction logic.
5. **`agent_memory_committee.py` (261 lines)** is only called when mode == "committee" —
   dead code path for most users.
6. `_EXTRACTION_SYSTEM` and `_EXTRACTION_SYSTEM_RETRY` are 200+ characters of prompt template
   that runs on every non-trivial turn.

### 2.5 Tool Definition Bloat

**`agent_tools.py` — 60+ tool schemas:**

```
READ_ONLY_TOOLS (30 entries):         gmail, calendar, drive, sheets, docs, youtube, tasks,
                                       people, github, slack, linear, notion, telegram, discord,
                                       device files, iCloud (7 tools), outlook, teams,
                                       list_connectors, get_session_time, web_search, web_fetch

_AUTO_APPLY_TOOLS (20 entries):       Gmail mutations (10), Calendar mutations (3),
                                       Drive mutations (2), Sheets append (1), YouTube update (1),
                                       Tasks CRUD (3), credential submissions (7), teams_post_message,
                                       memory CRUD (5), skills (2), connector setup (3),
                                       scheduled_task CRUD (4)

_PROPOSAL_TOOLS (8 entries):          email_send, email_reply, whatsapp_send, youtube_upload,
                                       slack_post, linear_comment, telegram_message, discord_post

_INTROSPECTION_TOOLS (6 entries):     workspace files, read_workspace, describe_harness,
                                       scheduled_task CRUD (4)

_TERMINATOR_TOOLS (1 entry):          final_answer
```

**Problems:**

1. **Descriptions are too long** — average 150-300 chars per tool. Written for humans reading
   docs, not for LLM consumption.
2. **`recall_memory` and `memory_search` are duplicates** — same handler, same schema:
   ```python
   "memory_search": ("_tool_recall_memory", False),  # identical to recall_memory
   ```
3. **`describe_harness`** is ~200 characters of description for introspection the agent doesn't need —
   it already knows its tools from the system prompt.
4. **Credential submission tools** (7 of them: `submit_whatsapp_credentials`, `submit_github_credentials`,
   etc.) are exposed to the agent as tools. The agent can't run `start_connector_setup` then type
   credentials — this would fail every time. Better to remove from the tool palette.
5. **No palette_mode metadata on many tools** — `_COMPACT_PALETTE_TOOLS` has only 28 tools.
   Most tools are "full mode only" even though compact mode could use most of them.
6. **`_fn()` helper** creates the same boilerplate pattern every time:
   ```python
   _fn(name, description, properties, required, palette_modes)
   ```
   But there's no compression of shared patterns across similar tools (e.g., all Gmail
   handlers share the same `_CONNECTION_ID` dict).

---

## 3. Detailed Refactor Plan

### Phase 1: Immediate Cuts (Low Risk, High Impact)

#### 1.1 Remove Niche Connector Tool Definitions + Handlers

**Tools to remove** (low usage, low ROI for personal assistant):

| Provider | Tools to Remove | Lines Saved |
|----------|----------------|-------------|
| YouTube (5) | `youtube_list_my_channels`, `youtube_search_videos`, `youtube_get_video`, `youtube_list_playlists`, `youtube_list_playlist_items`, `youtube_update_video` | ~150 (handlers) + ~250 (schema) = **400** |
| Discord (3) | `discord_list_guilds`, `discord_list_guild_channels`, `discord_get_channel_messages` + `propose_discord_post_message` | ~80 + ~100 = **180** |
| iCloud extras (3) | `icloud_reminders_list`, `icloud_notes_list`, `icloud_photos_list` (~90 lines each) | **270** |
| iCloud Drive (2) | `icloud_drive_list_folder`, `icloud_drive_get_file` | **50** |
| Teams (3) | `teams_list_teams`, `teams_list_channels`, `teams_post_message` + `propose_*` variants | **80** |
| Drive share (1) | `drive_share_file` | **15 handlers + 25 schema = 40** |
| Sheets append (1) | `sheets_append_row` | **15 handlers + 35 schema = 50** |
| iCloud contacts (2) | `icloud_contacts_list`, `icloud_contacts_search` | **100** |

**Total lines removed:** ~**1,170** from `agent_service.py` + `agent_tools.py`

**Files to edit:**
1. `backend/app/services/agent_tools.py` — remove tool definitions from `_READ_ONLY_TOOLS`, `_AUTO_APPLY_TOOLS`
2. `backend/app/services/agent_service.py` — remove all `_tool_*` static methods for above tools
3. `backend/app/services/agent_dispatch_table.py` — remove dispatch entries
4. `backend/app/services/connector_tool_registry.py` — remove `YOUTUBE_TOOL_PROVIDERS`, `DISCORD_TOOL_PROVIDERS`,
   `TEAMS_TOOL_PROVIDERS`, `ICLOUD_TOOL_PROVIDERS` entries (or keep for other purposes)
5. `backend/app/services/connectors/` — remove `youtube_client.py`, `discord_bot_client.py` (or keep if
   used elsewhere)

**NOT removing:** `icloud_drive_client.py`, `icloud_caldav_client.py`, `icalendar` — these are still used
by the calendar tool. Only remove the *agent tool handlers* for extras/reminders/notes/photos.

#### 1.2 Remove Duplicate Tool: `memory_search`

`memory_search` is an alias for `recall_memory` — identical handler, identical schema:

```python
# In agent_tools.py — both entries exist:
_remember = _memory_flush_tools,  # (in _MEMORY_FLUSH_NAMES)
"recall_memory": "_tool_recall_memory",
"memory_search": "_tool_recall_memory",  # DUPLICATE

# In _tool_recall_memory handler — same code for both
```

**Action:** Remove `memory_search` from:
- `AGENT_TOOLS` list (the `_fn()` call creating the schema)
- `AGENT_TOOL_DISPATCH` entry in `agent_dispatch_table.py`
- `_MEMORY_FLUSH_NAMES` if it's there (it probably is since `recall` is in there)
- `AGENT_TOOL_NAMES` frozenset (auto-updated from AGENT_TOOLS)

**Lines saved:** ~50 (removing the `_fn()` call + dispatch entry + frozenset update)

#### 1.3 Remove `describe_harness` Tool

This tool exists only for introspection — lets the agent call `"name": "describe_harness"` to get
a dict back with tool palette size, harness mode, linked providers, etc.

But the agent **already knows** this information:
- The tool list is in the system prompt
- Memory is in the memory section of the prompt
- Runtime settings are injected via harness facts
- The only novel info is `describe_harness` returns: `tool_count_this_turn`, `linked_connector_providers`,
  `agent_heartbeat_enabled`, `web_tools.enabled/provider/default_max_results`, etc.

**Every call costs 2-3 LLM rounds** (one to ask, one for the result). For a personal assistant
running daily, this is wasted API spend.

**Action:**
1. Remove `_fn("describe_harness", ...)` from `_INTROSPECTION_TOOLS` in `agent_tools.py`
2. Remove `"describe_harness": ("_tool_describe_harness", False)` from `AGENT_TOOL_DISPATCH`
3. Remove `_tool_describe_harness()` handler (~70 lines) from `agent_service.py`
4. **BUT** keep the `_tool_describe_harness()` function accessible via a new internal API
   endpoint (e.g., `GET /api/v1/agent/status` or `POST /api/v1/agent/describe`) so the frontend
   can still show the user what capabilities exist.

**Lines saved:** ~100 (remove from tools + dispatch + handler)
**Prompt savings:** Removes a tool from the palette, reducing the quick index by ~200 chars.

#### 1.4 Remove `memory_flush` System

`run_memory_flush_turn()` in `agent_service.py` (~70 lines) creates a **separate agent turn**
that runs before thread compaction to extract memories from upcoming-dropped messages.

**How it works:**
1. Builds a special "memory flush" system prompt with `_MEMORY_FLUSH_RULES`
2. Creates a full `AgentRun` record with `turn_profile="memory_flush"`
3. Runs a full ReAct loop with memory tools only
4. Another LLM call

**Problem:** This is a second LLM call per compact-and-extract cycle. The system already has
post-turn memory extraction (`maybe_ingest_post_turn_memory`). Combining both is redundant.

**Action:**
1. Remove `run_memory_flush_turn()` from `agent_service.py`
2. Remove `build_memory_flush_system_prompt()` from `agent_workspace.py`
3. Remove `_MEMORY_FLUSH_RULES` constant from `agent_workspace.py`
4. Remove `memory_flush_tools()` from `agent_tools.py`
5. Remove `TURN_PROFILE_MEMORY_FLUSH` from `agent_turn_profile.py`
6. Remove memory flush logic from `agent_harness_effective.py` (`if tp == TURN_PROFILE_MEMORY_FLUSH`)
7. Remove `_MEMORY_FLUSH_NAMES` frozenset from `agent_tools.py` (merge it with a simpler set if needed)
8. Update the memory flush path in `agent_harness_effective.py` to simply return the standard palette

**Lines saved:** ~150 across 5+ files

**Note:** Keep the canonical markdown sync (`canonical_memory.py`) — that's separate and
writes to `MEMORY.md` / `USER.md` / `memory/YYYY-MM-DD.md` without LLM involvement.

#### 1.5 Prune Diagnostic Logging

These are development debug logs that should never ship:

In `agent_service.py` — `resolve_turn_tool_palette()`:
```python
_logger.warning(
    "DIAG resolve_turn_tool_palette: user_id=%s mode=%s turn_profile=%s tool_count=%s tools=%s",
    user.id, mode, turn_profile, len(base), sorted(tool_names)
)
_logger.warning(
    "DIAG propose_* tools visible: %s",
    [n for n in tool_names if n.startswith("propose_")]
)
```

**Action:** Remove all three `_logger.warning("DIAG ...")` calls.

**Lines saved:** ~10

#### 1.6 Remove `_IDENTITY_AND_MEMORY_TOOL_NUDGE`

This constant (14 lines) is injected into the system prompt when `heuristic_wants_post_turn_extraction()`
returns True — it adds a "Host reminder" section telling the model to call `upsert_memory`
before `final_answer` when the turn looks like naming/remembering.

But this is already handled by:
1. The AGENTS.md rules (section about identity and memory)
2. The post-turn extraction LLM prompt (`_EXTRACTION_SYSTEM` already has identity rules)

**Action:** Remove the constant and the injection point (~5 lines) in `_execute_agent_loop()`:
```python
# Remove:
if heuristic_wants_post_turn_extraction(message, ""):
    conversation[0] = {
        "role": "system",
        "content": (conversation[0].get("content") or "") + _IDENTITY_AND_MEMORY_TOOL_NUDGE,
    }
```

**Lines saved:** ~20

---

### Phase 2: Structural Simplification

#### 2.1 Split `agent_service.py` into Modules

**Current state:** One 3,588-line file containing 6 static classes of tools + 15 static handler methods
per tool domain + ReAct loop + connection resolution + proposal management + trace emission.

**New structure:**

```
backend/app/services/agent/
├── __init__.py              # AgentService class with: run_agent(), run_agent_invalid_preflight(),
                              # create_pending_agent_run(), list_recent_runs(), list_trace_events(), get_run()
├── loop.py                  # _execute_agent_loop() — the ReAct loop (~650 lines, standalone)
├── connection.py            # _resolve_connection(), _gmail_client(), _calendar_client(), etc.
                              # All connection resolver helpers (~250 lines)
├── handlers/
│   ├── __init__.py          # Export all handlers, AGENT_TOOL_DISPATCH dict
│   ├── base.py              # Base handler pattern, decorator for connection resolution
│   ├── gmail.py             # Gmail handlers only (~25 methods, ~500 lines)
│   ├── calendar.py          # Calendar handlers (~4 methods, ~120 lines)
│   ├── drive.py             # Drive handlers (~3 methods, ~80 lines)
│   ├── sheets_docs.py       # Sheets + Docs handlers (35+ lines)
│   ├── tasks.py             # Tasks handlers (~5 methods, ~120 lines)
│   ├── people.py            # People handlers (~20 lines)
│   ├── search.py            # web_search, web_fetch (~30 lines)
│   ├── social.py            # telegram, whatsapp, discord (if kept), slack, teams (if kept)
│   ├── third_party.py       # github, linear, notion, people
│   ├── icloud.py            # iCloud handlers (if kept) (~150 lines)
│   ├── memory.py            # upsert_memory, delete_memory, list_memory, recall_memory, memory_get
│   ├── skills.py            # list_skills, load_skill, list_workspace_files, read_workspace_file
│   ├── proposal.py          # propose_* handlers (~250 lines total)
│   ├── misc.py              # get_session_time, list_connectors, _insert_proposal, _idem
│   └── scheduled_tasks.py   # scheduled_task CRUD (~200 lines)
├── proposal.py              # _insert_proposal() helper, PendingProposal helpers (if moved out of handlers)
├── replay.py                # AgentReplayContext (moved from agent_service.py or removed)
└── attention.py             # (moved from existing file if needed)
```

**Refactoring steps:**

1. **Create the directory structure** — `backend/app/services/agent/`
2. **Extract connection.py** — Move all `_resolve_connection` and `_client()` helpers to `connection.py`
3. **Extract group by domain** — For each tool group (gmail, calendar, etc.):
   - Move `_tool_*` static methods from `AgentService` class to a new module
   - Remove the `@staticmethod` decorator — make them plain async functions
   - Update `AGENT_TOOL_DISPATCH` entries to reference new function paths: `"gmail_list_messages": "agent.handlers.gmail._tool_gmail_list_messages"`
4. **Extract the ReAct loop** — Move `_execute_agent_loop()` to `loop.py` as a module function
5. **Extract helpers** — Move `_reduce_conversation_for_budget()`, `_assistant_message_from()`,
   `_conversation_trace_snapshot()`, `_trim_step_payload_for_client()`, `_approx_prompt_tokens()`,
   `_is_context_overflow()` to `helpers.py` or wherever they fit
6. **Update the main module** — `agent/__init__.py` has the thin `AgentService` wrapper class with
   public entry points that delegates to the new modules
7. **Update imports** — Replace all `from app.services.agent_service import ...` with paths to
   new modules

**This is the single biggest leverage point** — every subsequent refactor becomes trivial once
the code is split into logical modules.

#### 2.2 Replace Prefix-Matching `required_providers_for_tool()` with Explicit Dict

Current approach (in `connector_tool_registry.py`):

```python
def required_providers_for_tool(tool_name: str) -> frozenset[str] | None:
    n = (tool_name or "").lower()
    if n.startswith("gmail_") or n.startswith("propose_email"):
        return frozenset(GMAIL_TOOL_PROVIDERS)
    if n.startswith("calendar_"):
        return CALENDAR_TOOL_PROVIDERS_FROZEN
    if n.startswith("drive_"):
        return frozenset(DRIVE_TOOL_PROVIDERS)
    # ... ~20 prefix-match branches ...
    return None
```

**Problems:**
- New tool needs to be added in BOTH `AGENTS.md` description AND this function
- Typos in prefixes silently break gating (e.g., `notion_search` matches `n.startswith("notion_")`,
  but a new tool `notion_create` would also match — correct behavior, but implicit)
- Can't see at a glance which tools exist

**New approach:**

```python
# In connector_tool_registry.py
TOOL_PROVIDER_MAP: dict[str, frozenset[str]] = {
    "gmail_list_messages": GMAIL_TOOL_PROVIDERS_FROZEN,
    "gmail_get_message": GMAIL_TOOL_PROVIDERS_FROZEN,
    # ... explicit mapping for every tool ...
}

def tool_required_connector_providers(tool_name: str) -> frozenset[str] | None:
    return TOOL_PROVIDER_MAP.get(tool_name)
```

**Action:**
1. Build the explicit dict by iterating over `AGENT_TOOLS` names and mapping them with prefix logic as seed
2. Replace `required_providers_for_tool()` and `tool_required_connector_providers()` calls
3. Keep the prefix-matching as a *fallback* for edge cases, but explicit should be the source

**Lines saved:** Negligible (more lines), but **clarity** increase is massive.

#### 2.3 Collapse Dual Harness → Native Only

**What to remove:**

1. **`prompted` harness mode** — entire `agent_harness/prompted.py`:
   - `format_tool_results_for_prompt()`
   - `parse_tool_calls_from_content()` 
   - `_parse_tool_calls_for_prompted()`
   - JSON-in-text tool schema generation

2. **Auto-fallback logic** in `agent_service.py`:
   - The `effective = "prompted"` reassign
   - `_assemble_system("prompted")` re-call
   - The entire fallback LLM call inside `_execute_agent_loop()`

3. **Harness selector simplification:**
   - `resolve_effective_mode()` always returns `"native"` 
   - Or keep `auto` as "always native" for semantic clarity

4. **Remove `_PROMPTED_TOOL_INSTRUCTIONS`** from `agent_workspace.py`
5. **Remove `palette_to_prompt_json()`** from `agent_workspace.py` (compact tool JSON generation)
6. **Remove `build_tools_section_prompted()`** from `agent_workspace.py`
7. **Remove `prompted_compact_json`** from runtime config and all references

**Fallback strategy for local models:**
- Use **LiteLLM** proxy that normalizes tool calling to OpenAI format
- Or use **OpenRouter** with models that support native tool calling
- If truly needed, one-shot fallback to prompted is fine, but remove the complex retry logic

**Impact:**
- Removes ~300 lines from `prompted.py`
- Removes ~50 lines of fallback logic from `agent_service.py`
- Removes ~100 lines of prompted tool formatting from `agent_workspace.py`
- **Reduces ReAct loop branching** to exactly one path

**Total lines removed:** ~450-500

#### 2.4 Simplify Post-Turn Memory to Single Path

**Current system:** 5 modes (heuristic, adaptive, committee, rubric_adaptation, always) with
1-2 LLM calls per non-trivial turn.

**New system:** Keep one LLM call, guarded by heuristic skip.

```python
async def extract_post_turn_memory(
    db, user, user_message, assistant_message, run_id=None
) -> PostTurnMemoryResult:
    # 1. Skip if disabled
    if not rt.agent_memory_post_turn_enabled:
        return PostTurnMemoryResult(skipped=True, reason="disabled", upserts=0)
    
    # 2. Quick heuristic skip (saves LLM call on greetings/trivial)
    if heuristic_wants_post_turn_extraction(user_message, assistant_message):
        return PostTurnMemoryResult(skipped=True, reason="heuristic_skip", upserts=0)
    
    # 3. Single LLM call — extract memories
    items = await _run_single_extraction(...)
    
    # 4. Upsert extracted items to memory
    # 5. Return result
```

**What to remove:**
1. `agent_memory_committee.py` (261 lines) — entire file
2. `maybe_adapt_rubric_after_turn()` from `agent_rubric.py`
3. `adaptive_trivial_skip()` from committee module
4. Mode-switching logic in `maybe_ingest_post_turn_memory()`
5. `_EXTRACTION_SYSTEM_RETRY` — single LLM call with retry in a try/except is sufficient
6. `run_committee_memory_extraction()` wrapper
7. Rubric tracking state in `AgentRuntimeConfigResolved`

**New extraction prompt:** Simplify `_EXTRACTION_SYSTEM` to a single 150-char system prompt:

```python
_EXTRACTION_SYSTEM = """Extract durable facts from this exchange.
Return ONLY JSON: {"memories":[{key:"string",content:"string",importance:0-10}]}
Key rules: use agent.identity.*/user.profile.*/memory.durable.* prefixes.
Skip transient tool results. Do NOT assert capabilities are impossible —
background/scheduled work is supported. Identity/name changes → importance 8-10.
"""
```

**Lines saved:** ~500 across 3+ files.

#### 2.5 Remove Debugging/Development Files

| File | Remove? | Reason |
|------|---------|--------|
| `backend/scripts/smoke_ai_provider.py` | Move to tests | Proper pytest test |
| `docs/GMAIL_QUOTA.md` | Remove | Outdated operational doc |
| `docs/GMAIL_WATCH.md` | Remove | Outdated operational doc |
| `docs/MANUAL_QA.md` | Remove | Replace with automated tests |
| `docs/TOOL_PALETTE_DIAGNOSTICS.md` | Remove | Internal debugging info |
| `docs/MEMORY_POST_TURN_DIAGNOSTICS.md` | Remove | Internal debugging info |
| `docs/SCHEDULED_TASKS_PLAN.md` | Remove | Plan, not reference doc |
| `docs/runbooks/PHASE_A_MANUAL_CHECKLIST.md` | Remove | Runbook not needed for production |

**Total:** ~10 files, ~2-3K doc chars. Clean up after refactoring is complete.

#### 2.6 Remove `agent_replay.py` from Production

`agent_replay.py` creates a `ContextVar` that intercepts the ReAct loop — when a `replay`
parameter is set, tool calls consume script results instead of hitting real APIs.

**Problems:**
- Lives in `services/` alongside production code
- Creates a `ContextVar` that's set/reset around every tool call inside the loop
- The `_replay_ctx` and `_agent_ctx` ContextVars add indirection to the hot path

**Action:** Move to `backend/tests/agent_replay.py` as a test utility module. If the test
suite doesn't use it much, remove entirely.

**Lines saved:** ~100 (move to tests: 0 production lines removed)

---

### Phase 3: Deep Simplification

#### 3.1 Consolidate Handler Boilerplate with a Decorator

**Current pattern in every handler:**

```python
@staticmethod
async def _tool_gmail_list_messages(db, user, args):
    row = await _resolve_connection(db, user, args, GMAIL_TOOL_PROVIDERS, label="Gmail")
    client = await _gmail_client(db, row)
    return await client.list_messages(...)
```

This pattern repeats 15+ times with variations. After splitting `agent_service.py`,
create a decorator to eliminate it:

```python
def gmail_connection(handler):
    """Decorator: resolve Gmail connection + client, translate errors."""
    @wraps(handler)
    async def wrapper(db, user, args):
        row = await _resolve_connection(db, user, args, GMAIL_TOOL_PROVIDERS, label="Gmail")
        client = await _gmail_client(db, row)
        try:
            return await handler(db, user, client, args)
        except GmailAPIError as e:
            return {"error": f"Gmail API {e.status_code}: {e.detail[:300]}"}
        except ConnectorNeedsReauth as e:
            return {"error": f"connector_needs_reauth: {e}"}
        except OAuthError as e:
            return {"error": f"oauth_error: {e}"}
        except Exception as e:
            return {"error": str(e)[:500]}
    return wrapper

# Usage:
@gmail_connection
async def _tool_gmail_list_messages(db, user, client, args):
    return await client.list_messages(...)
```

**For a generic decorator that works across providers:**

```python
def provider_connection(provider_key, label):
    """Generic decorator for any connection-gated handler."""
    def decorator(handler):
        @wraps(handler)
        async def wrapper(db, user, args):
            providers = required_providers_for_tool(handler.__name__ or "") or PROVIDER_MAP[provider_key]
            row = await _resolve_connection(db, user, args, providers, label=label)
            client = await _resolve_client(row, provider_key)
            return await handler(db, user, client, args)
        return wrapper
    return decorator

# Usage:
@provider_connection("gmail", "Gmail")
async def _tool_gmail_list_messages(db, user, client, args):
    return await client.list_messages(...)

@provider_connection("calendar", "calendar")
async def _tool_calendar_list_events(db, user, client, args):
    return await client.list_events(...)
```

**This reduces handler boilerplate by ~60%** — each handler goes from ~15 lines to ~5 lines
of actual logic.

#### 3.2 Template-Based Prompt Assembly

Current `build_system_prompt()` (100+ lines of manual string concatenation):

```python
parts: list[str] = []
if soul:
    parts.append(soul)
parts.append(agents)
if tprof not in ("user_chat", "memory_flush"):
    parts.append("## Context-first (automated turn)\n...")
if injected_user_context and str(injected_user_context).strip():
    parts.append(str(injected_user_context).strip())
if rt.agent_include_harness_facts:
    # ... 20-line block building harness facts ...
parts.append(tools)
if tier != "none":
    parts.append(_EPISTEMIC_PRIORITY_HOST)
# ... more conditionals ...
return "\n\n".join(parts)
```

**Replace with a template:**

```python
SYSTEM_PROMPT_TEMPLATE = """{SOUL}{AGENTS}{CONTEXTFIRST}{EPISTEMIC_PRIORITY}{HARNESS_FACTS}{TOOLS}{MEMORY}{CLOCK}{THREAD_HINT}"""

def build_system_prompt(**sections):
    return SYSTEM_PROMPT_TEMPLATE.format(**{
        k: v for k, v in sections.items() if v
    })
```

**Or even simpler — since prompts are just string concatenation:**

```python
async def build_system_prompt(...):
    blocks = []
    if tier != "none":
        blocks.append(await load_soul(user))
        blocks.append(await load_agents())
        blocks.append(_EPISTEMIC_PRIORITY_HOST)
    
    # Context block
    if context_hint:
        blocks.append(f"Thread context: {context_hint}")
    
    # Memory — canonical markdown or DB fallback
    memory_blob = await AgentMemoryService.recent_for_prompt(db, user)
    if memory_blob:
        blocks.append(memory_blob)
    
    # Clock
    blocks.append(build_clock_section(user_timezone, time_format))
    
    # Tools section (separate — injected at different position)
    tool_section = build_tools_section(palette, harness_mode, prompt_tier)
    
    return "\n\n".join(blocks + [tool_section])
```

**Key change:** Keep tool section **separate** from "content" blocks. Tools are injected as a
distinct block so they don't bloat the semantic part of the prompt.

#### 3.3 Remove Trace System or Gate It Behind Feature Flag

**Current trace emission points** (per agent turn):

| Event | When |
|-------|------|
| `EV_RUN_STARTED` | Start of every turn |
| `EV_LLM_REQUEST` | Every LLM API call |
| `EV_LLM_RESPONSE` | Every LLM response |
| `EV_TOOL_STARTED` | Every tool call |
| `EV_TOOL_FINISHED` | Every tool call |
| `EV_RUN_COMPLETED` | Turn ends successfully |
| `EV_RUN_FAILED` | Turn fails |
| `EV_POST_TURN_STARTED` | Post-turn extraction starts |
| `EV_POST_TURN_SKIPPED` | Post-turn extraction skipped |
| `EV_POST_TURN_COMPLETED` | Post-turn extraction done |
| `AgentRunStep` | Every LLM/Tool step |

That's **at least 10-12 database writes per agent turn** on top of the `AgentRun` insert/update.

**For a single-user self-hosted assistant, this is overkill.**

**Simplified approach:**
1. Keep `AgentRun` model with: `id`, `user_id`, `status`, `user_message`, `assistant_reply`, `error`, `root_trace_id`, `chat_thread_id`, `turn_profile`, `created_at`, `updated_at`
2. Keep `AgentRunStep` model but make it **optional** — only emit steps for errors and `final_answer`
3. Remove `AgentTraceEvent` model entirely — or keep behind env var `AGENT_TRACING_ENABLED`

**Lines to remove** (if removing completely):
- `agent_trace.py` — all trace event emission
- `AgentTraceEvent` model
- `list_trace_events()` endpoint and helper
- Trace event imports and emission calls from `agent_service.py` (~50 lines of trace calls)

**Lines to simplify** (if keeping but gating):
- Remove trace from happy-path tool execution (emit only on errors)

#### 3.4 Remove Credential Submission Tools from Agent Palette

7 tools for the agent to accept connector credentials:

```python
"submit_whatsapp_credentials",
"submit_github_credentials",
"submit_slack_credentials",
"submit_linear_credentials",
"submit_notion_credentials",
"submit_telegram_bot_credentials",
"submit_discord_bot_credentials",
```

**Problem:** The agent cannot run `start_connector_setup()` then type the credentials back.
The agent has no way to receive OAuth redirects. These tools would fail every time.

**Action:** Remove from:
1. `_AUTO_APPLY_TOOLS` in `agent_tools.py` (~150 lines of `_fn()` calls)
2. `AGENT_TOOL_DISPATCH` in `agent_dispatch_table.py` (~7 entries)
3. Handler methods in `agent_service.py` (~100 lines)

**Keep as backend-only service functions** in `connector_setup_service.py` — they're still called
by the `/api/v1/connectors/credentials` endpoints, just not exposed to the agent.

---

### Phase 4: Cleanup & Hardening

#### 4.1 Remove Debug Logging in `resolve_turn_tool_palette()`

See Phase 1.1.5 above. Specific lines in `agent_service.py` to remove:

```python
# Lines after the DIAG warning block:
_logger.warning(
    "DIAG resolve_turn_tool_palette: user_id=%s mode=%s turn_profile=%s tool_count=%s tools=%s",
    ...
)
_logger.warning(
    "DIAG propose_* tools visible: %s",
    [n for n in tool_names if n.startswith("propose_")]
)
_logger.warning("DIAG: no connector gating, returning base tools")
_logger.warning("DIAG: connector gating active, filtered to %d tools", len(filtered))
```

#### 4.2 Remove Developer Documentation (After Refactor)

| File | Action |
|------|--------|
| `docs/GMAIL_QUOTA.md` | Remove |
| `docs/GMAIL_WATCH.md` | Remove |
| `docs/MANUAL_QA.md` | Remove |
| `docs/TOOL_PALETTE_DIAGNOSTICS.md` | Remove |
| `docs/MEMORY_POST_TURN_DIAGNOSTICS.md` | Remove |
| `docs/SCHEDULED_TASKS_PLAN.md` | Remove |
| `docs/testing.md` | Keep but re-title to testing.md |

#### 4.3 Remove `_safe_rel_path` Path Traversal Protection

The `_safe_rel_path()` function in `agent_workspace.py` guards against `..` in workspace reads.
Since we're keeping the workspace optional (defaults baked into code), this function can be
simplified to just check if the filename is plain (no path separators):

```python
def _is_safe_filename(name: str) -> bool:
    return bool(name) and name == Path(name).name  # ensures no path components
```

This removes 10 lines of path traversal protection that's now unnecessary since we require
external workspace via env var (not default), and external files are validated on read.

#### 4.4 Remove Duplicate `chain_of_density` Path in Budget Service

`token_budget_service.py` has `select_history_by_budget()` which does a complex selection
of which messages to keep based on token budget. This is essentially doing its own summarization
to save tokens. For most users, this is unnecessary — the real fix is reducing prompt bloat
(which we're already doing in Phases 1-3).

**Keep the budget service** but simplify: instead of complex "head+tail" selection with
compaction summaries, do a simpler "keep last N messages + first system prompt":

```python
def select_history_by_budget(messages, budget_tokens):
    """Keep system prompt + last N messages that fit budget."""
    system = messages[0] if messages else {}
    remaining = messages[1:]
    # Keep latest 8 messages that fit in budget
    keep = []
    for msg in reversed(remaining):
        cost = estimate_message_tokens([{"role": msg["role"], "content": msg["content"]}])
        if cost <= budget_tokens:
            keep.insert(0, msg)
            budget_tokens -= cost
    return [system] + keep
```

This removes ~40 lines of complex history selection logic.

---

## 4. Files to Delete Entirely (After Migrating Their Contents)

| File | Lines | What to do with it |
|------|-------|-------------------|
| `backend/app/services/agent_memory_committee.py` | 261 | Remove — replaced by single LLM call |
| `backend/app/services/agent_rubric.py` | ~100 | Remove — rubric adaptation not needed |
| `backend/app/services/agent_replay.py` | ~100 | Move to tests or remove |
| `backend/app/services/agent_adapter_sandbox.py` | ? | Check if used elsewhere; likely dev-only |
| `backend/app/services/connector_dry_run_service.py` | ? | Check usage; likely dev-only |

To find exact line counts and usage:
```bash
# Count lines for remaining files
wc -l backend/app/services/*.py

# Find imports from a file
grep -r "from app.services.agent_rubric" backend/
grep -r "from app.services.agent_replay" backend/
grep -r "from app.services.connector_dry_run_service" backend/
grep -r "from app.services.agent_adapter_sandbox" backend/
```

---

## 5. Files to Merge

| Merge Into | Source | Reason |
|-----------|--------|--------|
| `llm_client.py` | `parse_json_object()` from `agent_harness/prompted.py` | Both parse JSON from text — keep one copy |
| `connector_tool_registry.py` | `TOOL_PROVIDER_MAP` (after refactor) | Replace prefix-matching with explicit dict |
| `agent_runtime_config_service.py` | `runtime_from_row()` from `user_ai_settings_service.py` | Avoids duplicate deserialization |

---

## 6. Estimated Impact Summary

### Lines of Code Removed (Production)

| Refactor | Lines Removed | Files Affected |
|----------|--------------|----------------|
| Remove niche tools (youtube, discord, iCloud extras, teams, drive_share, sheets_append) | ~1,200 | agent_service.py, agent_tools.py, agent_dispatch_table.py, connector_tool_registry.py |
| Remove duplicate `memory_search` | ~50 | agent_tools.py, agent_dispatch_table.py |
| Remove `describe_harness` tool | ~100 | agent_service.py, agent_tools.py, agent_dispatch_table.py |
| Remove `memory_flush` system | ~150 | agent_service.py, agent_workspace.py, agent_tools.py, agent_turn_profile.py, agent_harness_effective.py |
| Remove diagnostic logging | ~10 | agent_service.py |
| Remove `_IDENTITY_AND_MEMORY_TOOL_NUDGE` | ~20 | agent_service.py |
| **Phase 1 subtotal** | **~1,530** | |

| Refactor | Lines Removed | Files Affected |
|----------|--------------|----------------|
| Split agent_service.py (move to modules, no deletion yet) | 0 | N/A — restructuring |
| Drop prompted harness | ~450 | prompted.py, agent_service.py, agent_workspace.py |
| Simplify post-turn memory | ~500 | post_turn_service.py, committee.py, rubric.py |
| Remove credential submission tools from agent | ~250 | agent_tools.py, agent_dispatch_table.py, agent_service.py |
| Move agent_replay to tests | ~100 | agent_replay.py, agent_service.py |
| Remove trace events on happy path | ~100 | agent_service.py, trace.py |
| **Phase 2 subtotal** | **~1,400** | |

| Refactor | Lines Removed | Files Affected |
|----------|--------------|----------------|
| Simplify history selection | ~40 | token_budget_service.py |
| Remove `_safe_rel_path` complexity | ~10 | agent_workspace.py |
| Remove debug docs | ~500 chars | docs/ |
| Remove memory_search alias | Already counted | |
| **Phase 3 subtotal** | **~550** | |

**Total lines removed from production (before restructuring):** ~**2,880** (**~10% reduction**)

**After Phase 1 restructuring (module split):** code is organized logically — no lines removed,
but effectively "simplified" because each module is 100-500 lines vs 3,588.

### System Prompt Token Savings

| Component | Before | After | Savings |
|-----------|--------|-------|---------|
| Tool count | 60+ tools | 45-48 tools | ~-12 tools × ~30 chars = ~360 chars |
| Prompted mode | Removed (native only) | N/A | Eliminates worst case of ~12K tokens |
| `describe_harness` tool | In palette | Removed | ~-30 chars in tool index |
| Tool descriptions | ~150-300 chars avg | ~80-120 chars avg | ~-40% per tool |
| Memory blob | Up to 12K chars | Same (kept) | Zero change |
| Memory alias `memory_search` | 1 tool | Removed | ~-30 chars in tool index |

**Net per-turn savings (native mode, full tier):** ~500-800 chars **~125-200 tokens**
**Net per-turn savings (prompted mode removed):** Eliminates worst case entirely

### LLM API Cost Savings

| Scenario | Before | After | Savings |
|----------|--------|-------|---------|
| Single agent turn (1 ReAct loop) | 3-5 LLM calls | 3-5 LLM calls | Same |
| Post-turn memory extraction | 1-2 LLM calls | 1 LLM call (with quick skip) | ~2-3 API calls/turn |
| Tool introspection turns | 1-3 extra turns (describe_harness calls) | None | 1-3 turns/week |
| Memory flush turns | 1 extra turn before compaction | None | 1 turn/compaction cycle |

**Estimated monthly savings (500 agent turns/month):** ~6,000-10,000 LLM API calls
For Gemini 2.0 Flash: ~$0.10 → ~$1.60
For GPT-4o: ~$10 → ~$160 per month

---

## 7. Execution Order (Do These First)

### Step 1: Audit and Document (Day 1)

```bash
# Verify what we're touching
find /mnt/storage/Git-projects-storage/agent-aquila/backend -type f -name "*.py" | grep -v __pycache__ | wc -l
find /mnt/storage/Git-projects-storage/agent-aquila/backend -type f -name "*.py" | grep -v __pycache__ | xargs wc -l | tail -1

# Find references to files/directories we plan to modify
grep -r "describe_harness" backend/app/ --include="*.py"
grep -r "agent_memory_committee" backend/app/ --include="*.py"
grep -r "agent_replay" backend/app/ --include="*.py"
grep -r "prompted" backend/app/ --include="*.py" | grep -v __pycache__
grep -r "memory_flush" backend/app/ --include="*.py" | grep -v __pycache__
grep -r "_IDENTITY_AND_MEMORY" backend/app/ --include="*.py"
grep -r "DIAG" backend/app/ --include="*.py" | grep -v __pycache__
grep -r "submit_.*_credentials" backend/app/ --include="*.py" | grep -v __pycache__
```

### Step 2: Remove Dead/Redundant Code (Day 2)

1. Remove `describe_harness` tool, handler, and dispatch entry
2. Remove `memory_search` alias from tool defs and dispatch
3. Remove `_IDENTITY_AND_MEMORY_TOOL_NUDGE` constant and injection point
4. Remove diagnostic `DIAG` log lines
5. Remove all niche connector tool definitions (youtube, discord, iCloud extras, teams, etc.) AND their handlers
6. Remove memory_flush system (`run_memory_flush_turn()`, `_MEMORY_FLUSH_RULES`, etc.)
7. Remove credential submission tools from agent palette
8. Move `agent_replay.py` to tests
9. Remove debug docs

### Step 3: Simplify Post-Turn Memory (Day 3)

1. Delete `agent_memory_committee.py` entirely
2. Delete `agent_rubric.py` entirely (or keep if rubric logic is used elsewhere)
3. Rewrite `maybe_ingest_post_turn_memory()` to use single LLM call + heuristic skip
4. Simplify `_EXTRACTION_SYSTEM` prompt to 150 chars
5. Update `agent_runtime_config_service.py` to remove rubric-related fields
6. Remove `adaptive_trivial_skip()` from any remaining committee code
7. Update tests to match new post-turn behavior

### Step 4: Drop Prompted Harness (Day 4)

1. Delete `backend/app/services/agent_harness/prompted.py` entirely
2. Remove fallback logic from `_execute_agent_loop()` in `agent_service.py`
3. Simplify `resolve_effective_mode()` in `selector.py` to always return "native"
4. Remove `build_tools_section_prompted()` and `palette_to_prompt_json()` from `agent_workspace.py`
5. Remove `prompted_compact_json` from runtime config and all references
6. Remove `_PROMPTED_TOOL_INSTRUCTIONS` constant from `agent_workspace.py`
7. Clean up all harness-mode `if/else` branches to only `if native`
8. Remove `parse_tool_calls_from_content()` import in `agent_service.py`

### Step 5: Restructure `agent_service.py` (Day 5-7)

1. Create `backend/app/services/agent/` directory
2. Extract `connection.py` — all `_resolve_connection` and `_client()` helpers
3. Extract `handlers/gmail.py` — all Gmail handlers
4. Extract `handlers/calendar.py` — all Calendar handlers
5. Extract `handlers/drive.py` — all Drive handlers
6. Continue for each tool domain (sheets/docs, tasks, people, search, social, third_party, icloud, memory, skills, proposal, misc, scheduled_tasks)
7. Extract `loop.py` — `_execute_agent_loop()` as standalone function
8. Extract helpers to appropriate files
9. Create `agent/__init__.py` with thin `AgentService` wrapper
10. Update all import paths in routes and other services
11. Update `AGENT_TOOL_DISPATCH` to reference new module paths

### Step 6: Add Handler Decorator (Day 8)

1. Create `agent/handlers/base.py` with `@provider_connection()` decorator
2. Rewrite simple Gmail handlers to use decorator (verify it works)
3. Gradually migrate other handlers (low priority, can be done incrementally)

### Step 7: Simplify Prompt Assembly (Day 9)

1. Replace `build_system_prompt()` with template-based approach
2. Keep tool section separate from content blocks
3. Measure actual prompt size with `repr()` logging in development
4. Remove `build_harness_facts_markdown()` — move essential facts directly into the prompt

### Step 8: Remove Trace System or Gate Behind Flag (Day 10)

1. Add `AGENT_TRACING_ENABLED` env var to config
2. Wrap all trace event emissions in `if TRACING_ENABLED:` gates
3. Or delete trace system entirely (AgentTraceEvent model, trace emissions, list_traces endpoint)
4. Keep only essential `AgentRun` records with status/error/assistant_reply

### Step 9: Simplify Budget Service (Day 11)

1. Replace complex `select_history_by_budget()` with simple head+tail approach
2. Verify budget computation still works with real conversations
3. Remove chain_of_density-style compaction summaries

### Step 10: Test Everything (Day 12-13)

1. Run full test suite: `docker compose exec backend pytest`
2. Run agent turn tests with replay to verify ReAct loop still works
3. Test prompt assembly produces valid prompts for LLM
4. Test all connector tool gating works (gmail, calendar, drive, etc.)
5. Test memory extraction still extracts identity/preference correctly
6. Verify no import errors in the restructured codebase
7. Performance test: measure actual token counts in prompts

### Step 11: Clean Up (Day 14)

1. Remove debug docs
2. Remove `backend/scripts/smoke_ai_provider.py` → write pytest
3. Run linter (ruff/flake8) on all changed files
4. Run type checker (mypy) on all changed files
5. Update any remaining references to removed tools/constants
6. Write migration docs if database schema changed

---

## 8. Risk Assessment

| Refactor | Risk | Mitigation |
|----------|------|------------|
| Remove niche tools | **Low** | Only affects users connected to those connectors; they already have limited value |
| Remove `describe_harness` | **Low** | Replace with admin API endpoint; agent doesn't need this |
| Remove `memory_search` alias | **Low** | Exact duplicate — removing one leaves `recall_memory` |
| Remove `memory_flush` system | **Medium** | Test that post-turn extraction captures all necessary facts |
| Remove `_IDENTITY_AND_MEMORY_TOOL_NUDGE` | **Low** | AGENTS.md rules + post-turn extraction handle this |
| Remove diagnostic logs | **Low** | Logs are DEBUG level, not production-impacting |
| Simplify post-turn memory | **Medium** | Test identity extraction with various name/preference turns |
| Drop prompted harness | **Medium** | Verify no users are relying on Ollama with broken tool calling. Provide LiteLLM proxy recommendation. |
| Restructure `agent_service.py` | **High** | Most lines moved, none deleted yet. Thorough testing required. Keep `agent_service.py` as thin wrapper. |
| Remove credential tools from agent | **Low** | Agents can't use them anyway; move to API-only |
| Remove trace system | **Low-Medium** | Keep `AgentRun` + `AgentRunStep`; only remove fine-grained events |
| Simplify budget service | **Low** | Complex history selection was speculative optimization |

---

## 9. Validation Checklist

After each phase, verify:

- [ ] `docker compose up --build` starts without errors
- [ ] `docker compose exec backend pytest` passes
- [ ] `docker compose exec backend python -m app.scripts.smoke_ai_provider` works
- [ ] Agent can run a new turn (chat endpoint responds)
- [ ] Tools dispatch correctly (Gmail → `gmail_list_messages` etc.)
- [ ] Memory tools work (`upsert_memory`, `recall_memory`)
- [ ] Proposal tools work (`propose_email_send` creates PendingProposal)
- [ ] Scheduled task tools work
- [ ] Connector gating works (only tools for connected providers are visible)
- [ ] Prompt assembly produces valid, non-empty system prompt
- [ ] Token estimates make sense (not crashing or returning 0)
- [ ] No new linting errors from ruff/mypy

---

## 10. Files with Heavy `from app.services.agent_service import` Imports

These files will need import path updates after Phase 5 (restructuring):

```bash
grep -r "from app.services.agent_service import" backend/ --include="*.py" | grep -v __pycache__
```

Likely targets:
- `backend/app/routes/agent.py` — most likely heavy user
- `backend/app/worker.py` — calls `AgentService.run_agent()`
- `backend/app/services/chat_service.py` — may call agent
- `backend/app/services/telegram_inbound_service.py` — agent calls
- `backend/app/services/scheduled_task_service.py` — agent calls
- `backend/app/services/agent_memory_post_turn_service.py` — may reference agent
- Tests — multiple test files reference `AgentService` directly

After restructuring, most imports will become:
```python
# Before
from app.services.agent_service import AgentService

# After
from app.services.agent import AgentService
```

---

## 11. Database Schema Considerations

The following models may no longer be needed or may need field removal:

| Model | Change | Notes |
|-------|--------|-------|
| `AgentRunStep` | Keep | Still useful; fewer writes per turn after trace removal |
| `AgentTraceEvent` | Remove or gate | Only needed if `AGENT_TRACING_ENABLED` is on |
| `AgentRun.turn_profile` | Keep | Still used for profile-aware behavior |
| `AgentRuntimeConfig.rubric_*` | Remove | Post rubric adaptation |
| `AgentRuntimeConfig.memory_flush_enabled` | Remove | After memory_flush removal, replaced by post-turn settings |
| `AgentRuntimeConfig.memory_flush_max_steps` | Remove | Same as above |
| `AgentRuntimeConfig.memory_flush_max_transcript_chars` | Remove | Same as above |

Verify each field with:
```sql
-- Check if columns exist and what defaults they have
\d agent_runtime_configs
```

---

## 12. Summary: The Big Picture

### What We're Achieving

| Before | After |
|--------|-------|
| One 3,588-line `agent_service.py` with all tool handlers | Cleanly split `agent/` package with separate modules |
| 60+ tools, ~800 chars descriptions, duplicate `memory_search` | ~45-48 tools, ~50% shorter descriptions, no duplicates |
| Dual harness + auto-fallback | Native only |
| 5-tier post-turn memory with committee/rubric | Single LLM call + heuristic skip |
| System prompt: 5-25K tokens per turn | System prompt: 2-8K tokens per turn |
| 12 DB writes per turn (tracing) | 2-3 DB writes per turn (minimal tracing) |
| 60+ tool descriptions in every prompt | ~30-40 relevant tools + concise schema |
| ~28K lines of app code | ~25K lines of app code (10% reduction) |
| Hard to review any change | Easy to review any change |
| ~$160/month API cost (hypothetical) | ~$50-70/month API cost |

### What We're NOT Changing

- **Core functionality:** Agent turns, tool dispatch, ReAct loop, memory, connectors, proposals
- **OAuth/connector infrastructure:** All connector clients remain intact
- **Database models:** Keep them (only possibly remove trace events)
- **API endpoints:** Keep them (only add/remove small fields)
- **Skills system:** Unchanged
- **Scheduled tasks:** Unchanged
- **Frontend:** Unchanged
- **Docker/compose:** Unchanged

**The system remains a fully capable personal assistant — just simpler, cheaper to run, and easier to modify.**
