# Agent runtime settings (env vs UI)

User-facing **agent behavior** tunables (rate limits, tool loop, heartbeat participation, prompt tier, chat history windows, memory flush, post-turn extraction, channel gateway, outbound email allowlist, etc.) follow this pattern. For the **V1 agentic memory** (canonical markdown, committee, consolidation), see [AGENTIC_MEMORY.md](./AGENTIC_MEMORY.md) and [MEMORY.md](./MEMORY.md).

1. **Environment variables** on the server define **defaults** for the deployment (first boot, CI, and any user who has not set overrides).
2. **Per-user JSON** in `user_ai_settings.agent_runtime_config` stores **partial overrides**. Missing keys mean “use the env default”.
3. The API and UI expose the **merged effective values** (`AgentRuntimeConfigResolved`) on read. `PATCH /api/v1/ai/settings` with `agent_runtime` performs a **partial merge**; send `null` for a field to clear that override, or `agent_runtime: null` to clear **all** overrides for the user.

Infrastructure and secrets (database, Redis, JWT, OAuth app credentials, workspace paths, registration flags, etc.) remain **environment-only** and are not editable from the Settings UI.

## Operator reference

- **Code**: merge logic in `backend/app/services/agent_runtime_config_service.py`; Pydantic models in `backend/app/schemas/agent_runtime_config.py`.
- **UI**: **Settings → Agent behavior** (`frontend/src/components/features/ai-settings/agent-runtime-section.tsx`).
- **Migration**: Alembic `0027_agent_runtime_cfg` adds `user_ai_settings.agent_runtime_config`.

## Internal-only knobs

Some env vars exist for maintainers or gradual rollout (for example compact JSON for the prompted harness). They stay as server defaults unless exposed in the partial schema; prefer changing deployment env rather than documenting every flag in user-facing copy.
