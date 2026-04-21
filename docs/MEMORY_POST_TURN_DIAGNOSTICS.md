# Post-turn memory diagnostics

Use these against your app Postgres to see whether durable facts were extracted and why.

## Recent memories for a user

```sql
SELECT key, content, importance, updated_at
FROM agent_memories
WHERE user_id = :user_id
ORDER BY updated_at DESC
LIMIT 30;
```

## Recent agent runs

```sql
SELECT id, status, left(user_message, 120) AS user_preview,
       left(assistant_reply, 80) AS reply_preview,
       root_trace_id, created_at
FROM agent_runs
WHERE user_id = :user_id
ORDER BY id DESC
LIMIT 30;
```

## Post-turn trace events (after deployment with `post_turn.*` events)

```sql
SELECT e.run_id, e.event_type, e.payload, e.created_at
FROM agent_trace_events e
WHERE e.run_id = :run_id
   OR e.event_type LIKE 'post_turn.%'
ORDER BY e.id;
```

Narrow to one run:

```sql
SELECT event_type, payload
FROM agent_trace_events
WHERE run_id = :run_id
ORDER BY id;
```

Payload `reason` values include: `disabled`, `heuristic_skip`, `empty_extraction`, `no_api_key`, `llm_error`, `ok` (on `post_turn.completed`).

## Log grep (API / worker)

Search for `post_turn_memory:` in backend logs. Lines include `done`, `no items`, `retry_after_empty` (second LLM pass when the first returned no memories on a heuristic-matched turn), and exception traces for LLM or upsert failures.
