# Gmail API quota and heartbeat

Aquila reads Gmail **live** (no background mirror). Google Cloud Console counts **Gmail API** requests separately from Calendar or Drive, so high Gmail numbers do not mean you used Calendar less—they mean something called the Gmail endpoints often.

## Verify the ARQ worker and heartbeat

1. **Containers / process** — Ensure a worker is running only when you intend it (e.g. `worker` service in Docker Compose). It connects to `REDIS_URL` and runs `agent_heartbeat` on a cron schedule when enabled.

2. **Environment variables** (see [`.env.example`](../.env.example)):

   | Variable | Effect |
   |----------|--------|
   | `AGENT_HEARTBEAT_ENABLED` | When `true`, runs a scheduled agent turn per active user. Default `false`. |
   | `AGENT_HEARTBEAT_MINUTES` | Interval for cron ticks (minutes). |
   | `AGENT_HEARTBEAT_BURST_PER_HOUR` | Max heartbeat runs per user per hour (`0` = unlimited cap disabled). |
   | `AGENT_HEARTBEAT_CHECK_GMAIL` | When `true`, the heartbeat prompt tells the model to scan Gmail. Default **`false`** so background ticks do not burn Gmail quota. |

3. **Logs** — On worker startup you should see a line like: `worker started; redis=... heartbeat=... every=...m`.

## Quantify agent Gmail usage (Postgres)

Heartbeats and chat both create rows in `agent_runs` and `agent_run_steps`.

**Runs whose user message is the default heartbeat (with Gmail prompt):** match on the distinctive opening phrase, or inspect `user_message` for your deployment.

**Tool calls by name (Gmail tools):**

```sql
SELECT s.name, COUNT(*) AS n
FROM agent_run_steps s
WHERE s.kind = 'tool' AND s.name LIKE 'gmail_%'
GROUP BY s.name
ORDER BY n DESC;
```

**Runs in the last 24 hours:**

```sql
SELECT COUNT(*) FROM agent_runs
WHERE created_at > NOW() - INTERVAL '24 hours';
```

## Metadata cache (agent + HTTP)

Repeated `messages.get` / `threads.get` with `format=metadata` are served from an in-process TTL cache shared by the FastAPI `/gmail` routes and agent tools ([`backend/app/services/gmail_metadata_cache.py`](../backend/app/services/gmail_metadata_cache.py)). Full message bodies are never cached there.

## Further reading

- [Gmail watch / Pub/Sub (design)](GMAIL_WATCH.md) — event-driven alternative aligned with OpenClaw-style setups.
