# Agent Aquila — product vision

Agent Aquila is a **self-hosted** personal and team assistant: one harness that can reach your mail, calendar, files, and many other connectors through a **broad tool surface**, while you keep **your accounts, your keys, and your infrastructure**.

## What we optimize for

1. **Context-first activation** — When something wakes the agent (a message, a channel ping, a scheduler tick, or a future push notification), the default posture is: **understand the signal, relate it to what we already know about the user, then decide** — not an unbounded deep dive through every tool unless the situation calls for it. Runtime controls (turn profiles, step budgets, scoped tool palettes) make that policy enforceable, not just aspirational in the system prompt.

2. **Token efficiency (minimum "TL;DR" overhead)** — Full capabilities stay **registered**; non-chat entry points (channels, heartbeats, automation-class runs) can use a **compact** tool palette and stricter step limits so the model is not repaying the cost of the entire catalogue on every wake. A **user context snapshot** (see below) is maintained asynchronously so the model gets a short working summary instead of re-deriving the user from raw memory on every run.

3. **Observability and control** — Runs log structured **AgentRunStep** records; proposals gate high-risk sends (email replies/sends); and **per-user runtime settings** let operators and users cap behavior without forked codebases. A fine-grained **trace event** system also exists (`AgentTraceEvent`) but is optional — see [AGENT_SETTINGS.md](./AGENT_SETTINGS.md).

4. **Human, coworker feel** — Persona and workspace files (`agent_workspace/`) describe tone and boundaries. The product goal is an assistant that feels like **another person with access to your systems**, with clear safety defaults (e.g. outbound email approval).

## How this relates to OpenClaw

[OpenClaw](https://github.com/openclaw/openclaw) is a strong reference for the **shape** of a personal assistant: gateway, channels, skills, and file-backed workspace culture. Aquila reuses that **metaphor** (memory keys, skills, `final_answer` termination) but ships as a **Python (FastAPI) + Next.js** stack with its own **harness** goals: **leaner** context assembly on automated wakes, a **first-class** user context snapshot, and **metrics-friendly** agent traces in the database.

We do **not** claim channel-for-channel or feature-for-feature parity with OpenClaw's Node gateway; we **do** aim for **omni-channel** use (web, gateway, and integrations such as Telegram) through a **single** API and agent core.

## Non-goals (for this document)

- Replacing your documentation for a specific provider (Gmail, OAuth, quotas).
- Promising a roadmap date for Gmail Pub/Sub push — see [INTEGRATIONS_ROADMAP.md](./INTEGRATIONS_ROADMAP.md) for connector backlog.

## Documentation map

- **Memory mechanics** — [MEMORY.md](./MEMORY.md) and [AGENTIC_MEMORY.md](./AGENTIC_MEMORY.md) (canonical markdown, post-turn extraction).
- **Tunables** — [AGENT_SETTINGS.md](./AGENT_SETTINGS.md) (env vs per-user `agent_runtime_config`).
- **Operator / quota** — [TROUBLESHOOTING.md](./TROUBLESHOOTING.md).
- **All providers** — [PROVIDERS.md](./PROVIDERS.md) (setup guides for Google AI Studio, Ollama, OpenAI, etc.).
- **Connector backlog** — [INTEGRATIONS_ROADMAP.md](./INTEGRATIONS_ROADMAP.md) (feature backlog, not a promise).
- **Skills** — [SKILLS.md](./SKILLS.md) (skill format and authoring guide).
- **Refactors** — [REFACTOR_PLAN.md](./REFACTOR_PLAN.md) (architectural cleanup plan).
