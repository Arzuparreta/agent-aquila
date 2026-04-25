# Scheduled Tasks Implementation Plan

## Problem Statement

The agent misclassifies one-time reminders as recurring scheduled tasks. When a user says "remember me to pick up groceries at 7:00pm", the agent creates a `schedule_type=daily` task that runs every day, with no mechanism to deliver the result back to the user.

### Root Causes

1. **No one-time task type**: Only `interval`, `daily`, `cron`, `rrule` exist — all recurring
2. **No delivery mechanism**: `run_scheduled_tasks()` executes tasks but discards results
3. **Wrong channel**: Results would appear in the last active chat thread, not a dedicated thread

---

## Current Architecture

```
User → Agent → scheduled_task_create(daily 7:00) → DB row created
                                                           ↓
Worker at 7:00 → runs agent with instruction → agent does work
                                                           ↓
                                              results discarded ❌
```

---

## Implementation Phases

### Phase 1: One-Time Task Support (Foundation)
**Goal**: Make `schedule_type="once"` work, auto-disables after execution

#### 1.1 Model - Add scheduled_at field
**File**: `backend/app/models/scheduled_task.py`
```python
scheduled_at: Mapped[datetime | None] = mapped_column(
    DateTime(timezone=True), nullable=True
)
```

#### 1.2 Migration
**File**: `backend/migrations/versions/XXX_add_scheduled_at.py`
```sql
ALTER TABLE scheduled_tasks ADD COLUMN scheduled_at TIMESTAMP WITH TIME ZONE;
```

#### 1.3 Service Logic
**File**: `backend/app/services/scheduled_task_service.py`

`normalize_schedule()` changes:
```python
# Accept "once" type
if st == "once":
    if not scheduled_at:
        raise ValueError("once schedule requires scheduled_at")
    return {
        "schedule_type": "once",
        "timezone": None,
        ...
    }
```

`compute_next_run()` changes:
```python
# Return scheduled_at for "once" type
if st == "once":
    return task.scheduled_at.astimezone(UTC) if task.scheduled_at.tzinfo is None else task.scheduled_at
```

#### 1.4 Tool Definition
**File**: `backend/app/services/agent_tools.py`

`scheduled_task_create` changes:
- Add `"once"` to `schedule_type` enum
- Add `scheduled_at: {"type": "string", "format": "date-time"}` parameter
- Update description: mention "once" for single future execution
- Update description: "Use 'once' when the user asks for a one-time reminder or single future task"

#### 1.5 Worker Auto-Disable
**File**: `backend/app/worker.py`

In `run_scheduled_tasks()`:
```python
if task.schedule_type == "once":
    task.enabled = False  # Auto-disable after execution
```

---

### Phase 2: Dedicated Thread for Automation
**Goal**: Tasks create their own thread, not reuse existing ones

#### 2.1 Thread Creation
**File**: `backend/app/worker.py`

In `run_scheduled_tasks()`:
```python
# Create dedicated thread for automation task
thread = ChatThread(
    user_id=user.id,
    kind="automation",  # New kind for automation tasks
    title=task.name[:255],
)
db.add(thread)
await db.flush()

# Run agent with the new thread context
run = await AgentService.run_agent(
    db,
    user,
    _scheduled_task_prompt(task, now_utc=datetime.now(UTC)),
    turn_profile=TURN_PROFILE_AUTOMATION,
    chat_thread_id=thread.id,  # Pass thread context
)
```

#### 2.2 Update AgentService.run_agent signature
**File**: `backend/app/services/agent_service.py`

Check if `run_agent()` accepts `chat_thread_id` parameter. If not, add it.

---

### Phase 3: Results Delivery
**Goal**: Agent output appears in the new thread + optional Telegram

#### 3.1 Apply Results to Thread
**File**: `backend/app/worker.py`

After agent completion:
```python
# Apply agent response to thread
await apply_agent_run_to_placeholder(
    db, thread, agent_run_id=run.id, run_read=read
)

# Notify via Telegram if bound
await notify_telegram_for_completed_run(
    db,
    user_id=user_id,
    thread_id=thread.id,
    assistant_reply=read.assistant_reply,
    error=read.error,
)
```

#### 3.2 Telegram Binding (if needed)
**File**: `backend/app/models/chat_thread.py`

Add `kind="automation"` to the valid values if needed for filtering.

---

### Phase 4: Smart Delivery Channel (Future)
**Goal**: Detect delivery preference from task instruction

Detect keywords in task instruction:
- "send to telegram" → deliver via Telegram only
- "send to email" → deliver via email (future)
- Default → deliver to the new thread

---

## Design Notes

### Time Parsing
The LLM will parse natural language like "at 7pm tomorrow" into ISO format datetime when calling `scheduled_task_create`. Example:
```json
{
  "name": "Reminder: pick up groceries",
  "instruction": "Tell the user: 'Remember to pick up groceries on your way home'",
  "schedule_type": "once",
  "scheduled_at": "2025-04-26T19:00:00"
}
```

### Auto-Disable Behavior
After a `"once"` task executes:
1. `enabled` is set to `False`
2. `last_run_at` is set
3. Row remains in DB for audit/history
4. `run_count` is incremented

### Thread Title
Uses the `name` field from the task creation (e.g., "Reminder: pick up groceries")

---

## Testing Checklist

### Phase 1 Tests
- [ ] Create a "once" task with `scheduled_at` in the past → should run immediately
- [ ] Create a "once" task with `scheduled_at` in the future → should appear in due tasks at correct time
- [ ] "once" task executes → `enabled` becomes `False`
- [ ] "once" task does NOT re-run on next tick

### Phase 2 Tests
- [ ] Task execution creates a new `ChatThread(kind="automation")`
- [ ] Thread title matches task name
- [ ] Agent runs with correct `chat_thread_id`

### Phase 3 Tests
- [ ] Agent output appears in the new thread as a message
- [ ] Telegram notification sent if channel is bound
- [ ] No notification sent if Telegram not configured

---

## Files to Modify

| Phase | File | Changes |
|-------|------|---------|
| 1.1 | `backend/app/models/scheduled_task.py` | Add `scheduled_at` field |
| 1.2 | `backend/migrations/versions/XXX_add_scheduled_at.py` | New migration file |
| 1.3 | `backend/app/services/scheduled_task_service.py` | Handle `"once"` type |
| 1.4 | `backend/app/services/agent_tools.py` | Update tool definition |
| 1.5 | `backend/app/worker.py` | Auto-disable `"once"` tasks |
| 2.1 | `backend/app/worker.py` | Create dedicated thread |
| 3.1 | `backend/app/worker.py` | Apply results + notify |

---

## Status

- [x] Phase 1: One-Time Task Support
  - [x] 1.1 Add `scheduled_at` field to `ScheduledTask` model
  - [x] 1.2 Create migration file `0035_scheduled_task_scheduled_at.py`
  - [x] 1.3 Update `normalize_schedule()` and `compute_next_run()` for `"once"` type
  - [x] 1.4 Update `scheduled_task_create` tool definition with `"once"` enum + `scheduled_at` param
  - [x] 1.5 Worker auto-disables `"once"` tasks after execution
  - [x] Tests pass (99 passed, 36 skipped)
- [x] Phase 2: Dedicated Thread Creation
  - [x] 2.1 Worker creates `ChatThread(kind="automation")` before running agent
  - [x] 2.2 Agent runs with `thread_id` passed to `run_agent()`
  - [x] 2.3 Results appended to thread via `append_message()`
  - [x] 2.4 Telegram notification sent via `notify_telegram_for_completed_run()`
  - [x] Tests pass (99 passed, 36 skipped)
- [ ] Phase 3: Results Delivery (Complete - integrated in Phase 2)
- [x] Phase 4: Smart Delivery Channel
  - [x] 4.1 Add `source_channel` field to `ScheduledTask` model
  - [x] 4.2 Create migration `0036_scheduled_task_source_channel.py`
  - [x] 4.3 Pass `source_channel` from web/telegram/channel routes via `agent_ctx`
  - [x] 4.4 Implement `_parse_delivery_preference()` to detect "send to telegram"/"email me"
  - [x] 4.5 Implement smart routing: instruction > source_channel > web fallback
  - [x] Tests pass (99 passed, 36 skipped)

---

## Deployment Checklist

After pulling these changes:

1. **Run both migrations:**
   ```bash
   cd backend
   alembic upgrade head
   ```

2. **Restart the ARQ worker** to pick up the new code:
   ```bash
   docker compose restart worker
   # or
   arq app.worker.WorkerSettings
   ```

3. **Test the flow:**
   - Ask the agent from Telegram: "Remember me at 7pm to pick up groceries"
   - Verify the task has `source_channel="telegram"` in the database
   - At 7pm, verify:
     - Message appears in Telegram (delivery_channel=telegram)
     - A new `ChatThread(kind="automation")` is created (for history)
   
   - Ask the agent from web: "Remember me at 8pm to call mom"
   - Verify the task has `source_channel="web"` in the database
   - At 8pm, verify:
     - Message appears in Telegram (fallback because source_channel="web")
     - A new `ChatThread(kind="automation")` is created

   - Ask the agent: "Send me the weather at 9am via telegram"
   - Verify the task instruction contains "telegram"
   - At 9am, verify:
     - Message appears in Telegram (instruction preference)

---

## Files Modified

| File | Changes |
|------|---------|
| `backend/app/models/scheduled_task.py` | Added `scheduled_at` + `source_channel` fields |
| `backend/alembic/versions/0035_scheduled_task_scheduled_at.py` | Migration for `scheduled_at` |
| `backend/alembic/versions/0036_scheduled_task_source_channel.py` | Migration for `source_channel` |
| `backend/app/services/scheduled_task_service.py` | `"once"` type + `source_channel` support |
| `backend/app/services/agent_tools.py` | Tool definition with `"once"` + `scheduled_at` |
| `backend/app/services/agent_service.py` | ContextVar + `scheduled_at` parsing + `agent_ctx` param |
| `backend/app/worker.py` | Thread creation + smart delivery routing |
| `backend/app/routes/threads.py` | Pass `agent_ctx={"source_channel": "web"}` |
| `backend/app/routes/channels.py` | Pass `agent_ctx={"source_channel": ...}` |
| `backend/app/routes/agent.py` | Pass `agent_ctx={"source_channel": "api"}` |
| `backend/app/services/telegram_inbound_service.py` | Pass `agent_ctx={"source_channel": "telegram"}` |