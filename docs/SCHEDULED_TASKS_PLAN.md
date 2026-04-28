# Scheduled Tasks

> **Note:** This entire feature is complete. All four phases are implemented and
> running in production. This file is kept as a historical record only.

## Status

- [x] Phase 1: One-Time task support (`schedule_type="once"`)
- [x] Phase 2: Dedicated automation threads
- [x] Phase 3: Results delivery
- [x] Phase 4: Smart delivery channel + `source_channel` field

## How it works today

1. User tells agent: *"remember me at 7pm to pick up groceries"*
2. Agent creates a `ScheduledTask` with `schedule_type="once"` and `scheduled_at`
3. Worker runs at the scheduled time, creates a `ChatThread(kind="automation")`, and runs the agent turn
4. Results are posted back to the automation thread and delivered via `source_channel` (Telegram) or fallback

## Key env vars

| Variable | Default | Purpose |
|----------|---------|---------|
| `AGENT_HEARTBEAT_ENABLED` | `false` | Enable/disable heartbeat cron |
| `AGENT_HEARTBEAT_MINUTES` | 15 | Worker sweep interval |

Workers call `run_scheduled_tasks()` on each heartbeat tick.
