# Aquila gateway (skeleton)

This directory is a **thin control-plane stub** that mirrors the OpenClaw-style topology: a long-lived process that holds channel connections and forwards user messages to the Aquila API.

## Contract with the core API

1. **Auth**: obtain a JWT the same way the web app does (`POST /api/v1/auth/login` or registration flow). The gateway stores the bearer token and sends `Authorization: Bearer <token>` on every request.

2. **Deliver a message** (when `AGENT_CHANNEL_GATEWAY_ENABLED=true` on the server):

   - `POST /api/v1/channels/gateway/deliver`
   - JSON body: `{ "channel": "gateway_stub" | "telegram" | "slack" | "discord" | "whatsapp" | "matrix" | "web", "external_key": "<stable-conversation-id>", "text": "..." }`  
     (`channel` must match a value from the API enum; the agent run is tagged with `turn_profile=channel_inbound` for scoped tools and trace correlation.)
   - Response: `{ "run_id", "chat_thread_id", "root_trace_id", "status", "turn_profile" }`

3. **Trace events** (evals / observability):

   - `GET /api/v1/agent/runs/{run_id}/trace-events`
   - Returns versioned rows (`event_type`: `run.started`, `llm.request`, `llm.response`, `tool.started`, `tool.finished`, `run.completed`, `run.failed`).

4. **Thread binding**: the first message for a given `(channel, external_key)` creates a `ChatThread` and a `channel_thread_bindings` row; later messages reuse the same thread.

## Local run

```bash
export AQUILA_API_BASE=http://localhost:8000
export AQUILA_TOKEN='<jwt>'
python gateway/main.py --text "hello from gateway"
```

Enable the HTTP endpoint in the API: `AGENT_CHANNEL_GATEWAY_ENABLED=true` in `.env`.

## Production notes

- Run the gateway in systemd/Docker with restart policies; scale horizontally with one consumer per channel type if needed.
- Prefer Redis or a queue between the gateway and API if you need backpressure; this skeleton uses direct HTTP.
