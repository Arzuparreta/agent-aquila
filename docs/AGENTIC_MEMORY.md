# Agentic memory — design reference

Product context: [VISION.md](./VISION.md). This is the **implementation reference**
for canonical markdown memory, post-turn extraction, consolidation, skill autogenesis,
and the adapter sandbox contract.

> **Status:** Parts of this document describe **current code** (canonical memory, post-turn
> extraction, consolidation) and parts describe **aspirational/optional** features
> (committee extraction with rubric adaptation, skill autogenesis, adapter sandbox).
> The refactoring plan ([REFACTOR_PLAN.md](./REFACTOR_PLAN.md)) proposes simplifying
> post-turn extraction from the current 5-mode system to a single LLM call + heuristic skip.

## Canonical memory (source of truth)

| Artifact | Role | Present in code? |
| -------- | ---- | ---------------- |
| `data/users/<user_id>/memory_workspace/MEMORY.md` | Long-term durable keys | ✅ |
| `.../USER.md` | User profile / preferences | ✅ |
| `.../memory/YYYY-MM-DD.md` | Daily-scoped keys | ✅ |
| `.../DREAMS.md` | Consolidation digest (not tool-synced KV) | ✅ |
| `.../rubric.json` | Dynamic importance weights | ✅ (written by agent_rubric.py) |
| `.../autogenesis/skill_autogenesis_candidates.jsonl` | Skill autogenesis candidate log | ✅ |

The database table `agent_memories` is an embedding + UI index; consolidation calls
`AgentMemoryService.reindex_db_from_canonical` to align rows with markdown KV blocks
between `<!-- aqv1 -->` markers.

## Post-turn extraction (`AGENT_MEMORY_POST_TURN_MODE`)

**Current implementation** (5 modes, 455 lines):

| Mode | Behaviour |
| ---- | ----------- |
| `heuristic` (legacy) | Keyword-style regex gate + single LLM extraction |
| `committee` | Proposer + judge (2 LLM calls) every completed turn |
| `adaptive` | Committee, but skips extremely short dual-greeting exchanges |
| `always` | LLM call every completed turn (no skip) |
| `rubric_adaptation` | Same as committee, with auto-tuning of rubric over time |

**Proposed simplification** (see REFACTOR_PLAN.md Phase 2.4):

Drop to one mode: heuristic + single LLM call. Remove:
- `agent_memory_committee.py` (261 lines) — multi-judge extraction
- `agent_rubric.py` (~100 lines) — rubric self-tuning
- Mode-switching logic in `agent_memory_post_turn_service.py`

## Consolidation (adaptive hybrid + periodic)

- **Worker** job: `agent_memory_consolidation_tick` (minute-level cron) runs when
  `int(time/60) % AGENT_MEMORY_CONSOLIDATION_MINUTES == 0`.
- Each sweep: appends one digest line to `DREAMS.md`, then
  `reindex_db_from_canonical` to refresh the DB.

Disable with `AGENT_MEMORY_CONSOLIDATION_ENABLED=false`.

## Skill autogenesis

If a run **completes successfully**, **no** `load_skill` tool step occurred, and there are
**at least 3** non-`final_answer` tool steps, a JSON line is appended to
`skill_autogenesis_candidates.jsonl` for later review or promotion to `backend/skills/`.

**Current code:** `backend/app/services/agent_skill_autogenesis.py` — records candidates
from agent turns (web, telegram, worker). Candidate review/publishing is manual.

## Adapter sandbox (contract)

`AdapterSandboxPipeline` in `app/services/agent_adapter_sandbox.py` is the placeholder for
generate → sandbox → promote of skills. Logs gaps today; codegen + sandbox runner not yet
implemented.

## Observability and reset

- `GET /api/v1/memory/digest` — returns the canonical block (transparency for digests).
- `POST /api/v1/memory/reset` — deletes all `agent_memories` rows and removes the user's
  `memory_workspace` tree.

## Environment variables

| Variable | Default | Meaning |
| -------- | ------- | ------- |
| `AQUILA_USER_DATA_DIR` | `backend/data` | Root for per-user memory workspace |
| `AGENT_MEMORY_POST_TURN_ENABLED` | `true` | Enable/disable post-turn extraction |
| `AGENT_MEMORY_POST_TURN_MODE` | `committee` | Extraction mode (see table above) |
| `AGENT_MEMORY_CONSOLIDATION_ENABLED` | `true` | Enable/disable periodic consolidation |
| `AGENT_MEMORY_CONSOLIDATION_MINUTES` | `360` | Slot alignment for consolidation cron |
| `AGENT_MEMORY_FLUSH_ENABLED` | `true` | Enable/disable memory flush before compaction |
| `AGENT_MEMORY_FLUSH_MAX_STEPS` | `8` | Max steps for flush run |
| `AGENT_MEMORY_FLUSH_MAX_TRANSCRIPT_CHARS` | `16000` | Max transcript chars for flush |
