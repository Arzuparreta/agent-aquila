# Agentic Memory - Implementation Reference

## Overview

This document provides the implementation reference for Agent Aquila's memory system, including canonical markdown memory, post-turn extraction, consolidation, skill autogenesis, and the adapter sandbox contract. For product context, see [VISION.md](./VISION.md). For user-facing memory documentation, see [MEMORY.md](./MEMORY.md).

> **Status**: Parts of this document describe **current code** (canonical memory, post-turn extraction, consolidation) and parts describe **aspirational/optional** features (committee extraction with rubric adaptation, skill autogenesis, adapter sandbox). The refactoring plan ([REFACTOR_PLAN.md](./REFACTOR_PLAN.md)) proposes simplifying post-turn extraction from the current 5-mode system to a single LLM call + heuristic skip.

## Canonical Memory (Source of Truth)

### Memory Artifacts

| Artifact | Location | Purpose | Present in Code? |
| -------- | ---------- | --------- | ----------------- |
| `MEMORY.md` | `data/users/<user_id>/memory_workspace/MEMORY.md` | Long-term durable keys | ✅ |
| `USER.md` | `.../USER.md` | User profile / preferences | ✅ |
| `memory/YYYY-MM-DD.md` | `.../memory/YYYY-MM-DD.md` | Daily-scoped keys | ✅ |
| `DREAMS.md` | `.../DREAMS.md` | Consolidation digest (not tool-synced KV) | ✅ |
| `rubric.json` | `.../rubric.json` | Dynamic importance weights | ✅ (written by agent_rubric.py) |
| `autogenesis/skill_autogenesis_candidates.jsonl` | `.../autogenesis/skill_autogenesis_candidates.jsonl` | Skill autogenesis candidate log | ✅ |

### Canonical Format

Memory files use a structured markdown format with key-value blocks:

```markdown
<!-- aqv1 -->
## Category

**key**: value
**another_key**: another value

## Another Category

**key2**: value2
<!-- aqv1 -->
```

### Database Index

The `agent_memories` table provides an embedding + UI index:

```sql
CREATE TABLE agent_memories (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    key VARCHAR(200) NOT NULL,
    content TEXT NOT NULL,
    importance INTEGER DEFAULT 0,
    tags TEXT[],
    embedding vector(1536),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, key)
);
```

### Sync Mechanism

Consolidation calls `AgentMemoryService.reindex_db_from_canonical()` to align database rows with markdown KV blocks between `<!-- aqv1 -->` markers.

## Post-Turn Extraction

### Current Implementation (5 Modes, 455 Lines)

The system currently supports multiple extraction modes with different behaviors:

| Mode | Behaviour | LLM Calls | Accuracy | Use Case |
| ---- | ----------- | ----------- | ---------- | -------- |
| `heuristic` (legacy) | Keyword-style regex gate + single LLM extraction | 1 | Good for simple facts | Basic extraction |
| `committee` | Proposer + judge (2 LLM calls) every completed turn | 2 | Higher accuracy | Critical information |
| `adaptive` | Committee, but skips extremely short dual-greeting exchanges | 0-2 | Balanced | General use |
| `always` | LLM call every completed turn (no skip) | 1 | Comprehensive | High-precision needs |
| `rubric_adaptation` | Same as committee, with auto-tuning of rubric over time | 2 | Self-improving | Learning systems |

### Proposed Simplification

The refactoring plan ([REFACTOR_PLAN.md](./REFACTOR_PLAN.md) Phase 2.4) proposes simplifying to one mode:

**Target**: Heuristic + single LLM call

**Remove**:
- `agent_memory_committee.py` (261 lines) — multi-judge extraction
- `agent_rubric.py` (~100 lines) — rubric self-tuning
- Mode-switching logic in `agent_memory_post_turn_service.py`

**Benefits**:
- Reduced complexity
- Lower API costs
- Faster execution
- Easier maintenance

### Extraction Process

1. **Trigger**: Agent turn completes successfully
2. **Analysis**: Analyze user message and assistant response
3. **Heuristic Check**: Apply regex-based filtering (if enabled)
4. **LLM Extraction**: Call LLM to extract durable facts
5. **Validation**: Validate extracted facts and importance
6. **Storage**: Upsert to memory system
7. **Notification**: Inject memory receipt into conversation

### Extraction Prompts

The system uses specialized prompts for extraction:

```python
_EXTRACTION_SYSTEM = """Extract durable facts from this exchange.
Return ONLY JSON: {"memories":[{key:"string",content:"string",importance:0-10}]}
Key rules: use agent.identity.*/user.profile.*/memory.durable.* prefixes.
Skip transient tool results. Do NOT assert capabilities are impossible —
background/scheduled work is supported. Identity/name changes → importance 8-10.
"""
```

## Consolidation

### Adaptive Hybrid + Periodic Consolidation

**Worker Job**: `agent_memory_consolidation_tick`

**Schedule**: Minute-level cron runs when `int(time/60) % AGENT_MEMORY_CONSOLIDATION_MINUTES == 0`

**Process**:
1. **Trigger**: Consolidation timer fires
2. **Analysis**: Review recent memories and identify patterns
3. **Digest Creation**: Create summary digest of key insights
4. **Storage**: Append digest line to `DREAMS.md`
5. **Reindex**: Call `reindex_db_from_canonical()` to refresh database

**Configuration**:
- `AGENT_MEMORY_CONSOLIDATION_ENABLED` - Enable/disable consolidation
- `AGENT_MEMORY_CONSOLIDATION_MINUTES` - Consolidation interval (default: 360)
- `AGENT_MEMORY_CONSOLIDATION_RETENTION_DAYS` - How long to keep raw memories

### Consolidation Format

```markdown
## Consolidation Digest - 2024-01-15

- User prefers informal communication style
- Working hours: 9 AM - 6 PM EST
- Key relationship: Manager Jane Smith (jane@company.com)
- Important pattern: Weekly email triage on Monday mornings
```

## Skill Autogenesis

### Candidate Recording

**Trigger Conditions**:
- Agent run completes successfully
- No `load_skill` tool step occurred
- At least 3 non-`final_answer` tool steps executed

**Process**:
1. **Analysis**: Analyze the agent run for reusable patterns
2. **Candidate Creation**: Create skill candidate from run pattern
3. **Storage**: Append JSON line to `skill_autogenesis_candidates.jsonl`

**Format**:
```json
{
  "timestamp": "2024-01-15T10:30:00Z",
  "run_id": 123,
  "pattern": "gmail_triage_workflow",
  "steps": [
    {"tool": "gmail_list_messages", "params": {...}},
    {"tool": "gmail_get_thread", "params": {...}}
  ],
  "success_rate": 0.95,
  "user_satisfaction": null
}
```

**Current Code**: `backend/app/services/agent_skill_autogenesis.py`

**Status**: Records candidates from agent turns (web, telegram, worker). Candidate review/publishing is manual.

### Future Plans

**Planned Features**:
- Automatic candidate promotion to skills
- User feedback integration
- Pattern recognition improvements
- Skill template generation

## Adapter Sandbox

### Contract and Placeholder

**Current Implementation**: `AdapterSandboxPipeline` in `app/services/agent_adapter_sandbox.py`

**Purpose**: Placeholder for generate → sandbox → promote of skills

**Current Status**: Logs gaps today; codegen + sandbox runner not yet implemented

**Planned Workflow**:
1. **Generate**: Create skill code from pattern
2. **Sandbox**: Test skill in isolated environment
3. **Promote**: Move skill to production if tests pass

### Future Implementation

**Components Needed**:
- Code generation engine
- Sandbox execution environment
- Test validation framework
- Promotion automation

## Observability and Reset

### Memory Digest API

**Endpoint**: `GET /api/v1/memory/digest`

**Purpose**: Returns the canonical block for transparency digests

**Response**:
```json
{
  "canonical_excerpt": "<!-- aqv1 -->\n## Identity\n**name**: John Doe\n..."
}
```

### Memory Reset API

**Endpoint**: `POST /api/v1/memory/reset`

**Purpose**: Deletes all `agent_memories` rows and removes the user's `memory_workspace` tree

**Response**:
```json
{
  "ok": true,
  "deleted_index_rows": true,
  "report": {
    "deleted_files": ["MEMORY.md", "USER.md", "memory/2024-01-15.md"],
    "hint": "All memory files removed successfully"
  }
}
```

### Trace Events

Memory operations emit trace events for observability:

- `memory_extraction_started` - Post-turn extraction begins
- `memory_extraction_completed` - Extraction finished successfully
- `memory_extraction_skipped` - Extraction skipped (heuristic)
- `memory_consolidation_started` - Consolidation begins
- `memory_consolidation_completed` - Consolidation finished

## Environment Variables

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

## Code Architecture

### Service Layer

**Key Services**:
- `AgentMemoryService` - Core memory operations (CRUD, search)
- `CanonicalMemoryService` - Markdown file operations
- `AgentMemoryPostTurnService` - Post-turn extraction orchestration
- `AgentMemoryConsolidationService` - Periodic consolidation
- `AgentSkillAutogenesisService` - Skill candidate recording

### Data Flow

```
Agent Turn Completes
    ↓
Post-Turn Extraction Service
    ↓
Heuristic Check (if enabled)
    ↓
LLM Extraction Call
    ↓
Extracted Facts
    ↓
Upsert to Memory System
    ↓
Canonical Markdown + Database Index
    ↓
Memory Receipt Injection
```

### Consolidation Flow

```
Consolidation Timer Fires
    ↓
Memory Consolidation Service
    ↓
Analyze Recent Memories
    ↓
Create Digest Summary
    ↓
Append to DREAMS.md
    ↓
Reindex Database
    ↓
Update Vector Index
```

## Performance Considerations

### Extraction Performance

- **LLM Calls**: Each extraction mode uses 1-2 LLM calls
- **Heuristic Filtering**: Reduces unnecessary LLM calls
- **Batch Processing**: Multiple memories can be extracted in one call
- **Caching**: Frequently accessed memories are cached

### Consolidation Performance

- **Incremental**: Only processes new or changed memories
- **Scheduled**: Runs on configurable intervals
- **Efficient**: Uses database indexes for fast lookups
- **Background**: Runs in worker process to avoid blocking

### Storage Performance

- **Markdown Files**: Human-readable, easily editable
- **Database Index**: Fast semantic search
- **Vector Embeddings**: Efficient similarity search
- **File System**: Standard file operations for canonical storage

## Security Considerations

### Data Protection

- **Encryption**: Sensitive memory content can be encrypted
- **Access Control**: User-specific memory isolation
- **Audit Logging**: All memory operations are logged
- **Data Retention**: Configurable retention policies

### Privacy Considerations

- **User Consent**: Memory extraction requires user consent
- **Transparency**: Users can see what's stored in memory
- **Control**: Users can delete or modify memory
- **Compliance**: Designed with privacy regulations in mind

## Testing and Validation

### Unit Tests

**Test Coverage**:
- Memory CRUD operations
- Extraction logic
- Consolidation process
- Sync mechanisms

### Integration Tests

**Test Scenarios**:
- End-to-end memory extraction
- Database sync from canonical files
- Consolidation workflows
- API endpoint functionality

### Manual Testing

**Test Procedures**:
1. Create test memories via agent interaction
2. Verify canonical file updates
3. Check database index sync
4. Test memory search functionality
5. Validate consolidation process

## Future Enhancements

### Planned Improvements

1. **Simplified Extraction**: Single LLM call + heuristic skip
2. **Enhanced Consolidation**: Better pattern recognition
3. **Improved Autogenesis**: Automatic skill promotion
4. **Advanced Sandbox**: Full skill testing environment
5. **Better Observability**: Enhanced monitoring and debugging

### Research Areas

1. **Memory Importance Scoring**: Dynamic importance adjustment
2. **Memory Deduplication**: Automatic duplicate detection
3. **Memory Summarization**: Automatic summarization of old memories
4. **Memory Relationships**: Linking related memories
5. **Memory Predictions**: Predictive memory suggestions

## Conclusion

The Agent Aquila memory system provides a comprehensive, context-aware storage solution that grows with the user over time. The current implementation supports multiple extraction modes, periodic consolidation, and skill autogenesis, with plans for simplification and enhancement in future releases.

The system is designed to be extensible, efficient, and privacy-conscious, making it suitable for both personal and team use cases where data sovereignty and control are paramount.
