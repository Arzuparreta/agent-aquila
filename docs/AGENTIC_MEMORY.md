# Agentic memory (V1) — design reference

This document describes the post–OpenClaw-reform **canonical markdown memory**, **committee
routing**, **adaptive consolidation**, **skill autogenesis policy**, and **adapter sandbox
contract**. It is the implementation companion to the agentic memory plan.

## Canonical memory (source of truth)

| Artifact | Role |
| -------- | ---- |
| `data/users/<user_id>/memory_workspace/MEMORY.md` | Long-term & durable keys (`memory.durable.*`, `agent.identity.*`, …) |
| `.../USER.md` | User profile / preferences (`user.profile.*`, `prefs.*`) |
| `.../memory/YYYY-MM-DD.md` | Daily-scoped keys (`memory.daily.YYYY-MM-DD`) |
| `.../DREAMS.md` | Consolidation digest / human review (not tool-synced KV) |
| `.../rubric.json` | **Dynamic** importance / routing weights + online notes (JSON) |
| `.../autogenesis/skill_autogenesis_candidates.jsonl` | One JSON line per **skill autogenesis** event |

The database table `agent_memories` is an **embedding + UI index**; consolidation calls
`AgentMemoryService.reindex_db_from_canonical` to align rows with the markdown KV blocks
between `<!-- aqv1 -->` markers.

## Post-turn mode (`AGENT_MEMORY_POST_TURN_MODE`)

| Mode | Behaviour |
| ---- | ----------- |
| `heuristic` | Legacy keyword-style gate + single JSON extraction. |
| `always` / `committee` | **Proposer + judge** (2 LLM calls) every completed turn. |
| `adaptive` | Committee, but **skips** extremely short dual-greeting exchanges. |

Rubric text is loaded from `rubric.json` and injected into proposer/judge system prompts. An
optional **rubric adapter** pass runs on a schedule and when new memories are approved
(online self-update; see `maybe_adapt_rubric_after_turn`).

## Consolidation (adaptive hybrid + periodic)

- **Worker** job: `agent_memory_consolidation_tick` (minute-level cron) runs a global sweep when
  `int(time/60) % AGENT_MEMORY_CONSOLIDATION_MINUTES == 0`.
- Each sweep: append one digest line to `DREAMS.md`, then
  `reindex_db_from_canonical` to refresh the DB.

Disable with `AGENT_MEMORY_CONSOLIDATION_ENABLED=false`.

## Skill autogenesis

If a run **completes successfully**, **no** `load_skill` tool step occurred, and there are
**at least 3** non-`final_answer` tool steps, a JSONL line is appended to
`skill_autogenesis_candidates.jsonl` for later review or promotion to `backend/skills/`.

## Adapter sandbox (contract)

`AdapterSandboxPipeline` in `app/services/agent_adapter_sandbox.py` is the **placeholder** for
generate → sandbox → promote. It logs gaps today; implement codegen + your sandbox runner here.

## Observability and reset

- `GET /api/v1/memory/digest` — returns the same canonical block used for the model (transparency
  for periodic digests in the app).
- `POST /api/v1/memory/reset` — deletes **all** `agent_memories` rows for the user and removes
  their `memory_workspace` tree (`rubric`, candidates, everything).

## Environment

| Variable | Meaning |
| -------- | ------- |
| `AQUILA_USER_DATA_DIR` | Root for per-user data (default: `backend/data`). |
| `AGENT_MEMORY_POST_TURN_MODE` | Default: `committee`. |
| `AGENT_MEMORY_CONSOLIDATION_ENABLED` | Default: `true`. |
| `AGENT_MEMORY_CONSOLIDATION_MINUTES` | Default: `360` (6h slot alignment). |
