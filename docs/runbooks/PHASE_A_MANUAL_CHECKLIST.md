# Phase A manual checklist (stabilize + instrument)

Run after deploying backend/worker changes that touch the agent loop or HTTP client.

1. **Unit tests** — `cd backend && pytest`
2. **Smoke provider** — optional: `python -m app.scripts.smoke_ai_provider` (with a real or Ollama key)
3. **Chat happy path** — send one short message in the web UI; confirm assistant reply and no stuck “…” (worker + Redis running if `AGENT_ASYNC_RUNS=true`)
4. **Trace timing** — open a completed run’s trace events (`GET /api/v1/agent/runs/{id}/trace-events`); confirm `llm.response` payloads include `duration_ms`
5. **Long Gmail task** — optional: run a multi-step Gmail ask; confirm no unexpected `Step budget exceeded` (tune `AGENT_MAX_TOOL_STEPS` if needed)
6. **Rollback** — if anything regresses, revert the commit and re-run migrations down if a migration was applied
