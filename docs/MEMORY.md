# Memory System - Architecture & Usage

## Overview

Agent Aquila's memory system provides persistent, context-aware storage for user information, preferences, and learned patterns. It combines canonical markdown storage with vector-based semantic search to create a comprehensive memory system that grows with the user over time.

## Core Components

### 1. Canonical Storage (Source of Truth)

The memory system uses markdown files as the primary storage mechanism, ensuring human-readable and editable memory:

| Artifact | Location | Purpose |
|----------|----------|---------|
| `MEMORY.md` | `data/users/<user_id>/memory_workspace/MEMORY.md` | Long-term durable keys and facts |
| `USER.md` | `.../USER.md` | User profile, preferences, and identity |
| `memory/YYYY-MM-DD.md` | `.../memory/YYYY-MM-DD.md` | Daily-scoped memories and events |
| `DREAMS.md` | `.../DREAMS.md` | Consolidation digest and summaries |
| `rubric.json` | `.../rubric.json` | Dynamic importance weights (optional) |

**Location**: Configured via `AQUILA_USER_DATA_DIR` environment variable (defaults to `backend/data`)

### 2. Vector Database (Search Index)

The `agent_memories` table provides semantic search capabilities:

```sql
CREATE TABLE agent_memories (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    key VARCHAR(200) NOT NULL,
    content TEXT NOT NULL,
    importance INTEGER DEFAULT 0,
    tags TEXT[],
    embedding vector(1536),  -- pgvector
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, key)
);
```

**Key Features**:
- **Semantic Search**: Vector similarity search for relevant memories
- **Hybrid Queries**: Combine semantic search with tag filtering
- **Importance Scoring**: Weight results by importance and recency
- **Automatic Sync**: Synced from canonical markdown storage

### 3. Memory Operations

#### Reading Memory

**Agent Tools**:
- `recall_memory(query, tags, limit)` - Semantic search with optional filters
- `list_memory(limit)` - List all memories with pagination
- `memory_get(key)` - Get specific memory by key

**API Endpoints**:
- `GET /api/v1/memory` - List memories
- `POST /api/v1/memory/recall` - Semantic search
- `GET /api/v1/memory/digest` - Get canonical memory block

#### Writing Memory

**Agent Tools**:
- `upsert_memory(key, content, importance, tags)` - Create or update memory
- `delete_memory(key)` - Remove specific memory

**API Endpoints**:
- `POST /api/v1/memory` - Create/update memory
- `DELETE /api/v1/memory/{key}` - Delete memory

## Memory Extraction

### Post-Turn Extraction

After every completed agent turn, the system automatically extracts durable facts:

**Process Flow**:
1. **Trigger**: Agent turn completes successfully
2. **Analysis**: Analyze user message and assistant response
3. **Extraction**: LLM extracts durable facts (identity, preferences, commitments)
4. **Storage**: Upsert extracted facts to memory system
5. **Notification**: Inject memory receipt into conversation

**Configuration**:
- `AGENT_MEMORY_POST_TURN_ENABLED` - Enable/disable extraction
- `AGENT_MEMORY_POST_TURN_MODE` - Extraction mode (heuristic, committee, always)
- `AGENT_MEMORY_POST_TURN_SKIP_THRESHOLD` - Minimum complexity for extraction

**Extraction Modes**:

| Mode | Description | LLM Calls | Accuracy |
|------|-------------|-----------|----------|
| `heuristic` | Regex-based filtering + single LLM call | 1 | Good for simple facts |
| `committee` | Multi-judge extraction with validation | 2 | Higher accuracy |
| `always` | Extract on every completed turn | 1 | Comprehensive but expensive |

### Memory Consolidation

Periodic consolidation keeps memory fresh and prevents unbounded growth:

**Process**:
1. **Schedule**: Runs on configurable interval (`AGENT_MEMORY_CONSOLIDATION_MINUTES`)
2. **Analysis**: Review recent memories and identify patterns
3. **Digest**: Create summary digest of key insights
4. **Storage**: Append digest to `DREAMS.md`
5. **Reindex**: Update vector database with consolidated memories

**Configuration**:
- `AGENT_MEMORY_CONSOLIDATION_ENABLED` - Enable/disable consolidation
- `AGENT_MEMORY_CONSOLIDATION_MINUTES` - Consolidation interval (default: 360)
- `AGENT_MEMORY_CONSOLIDATION_RETENTION_DAYS` - How long to keep raw memories

## Memory Categories

### Identity Information
- User name and preferred name
- Contact information
- Personal details (birthday, location, etc.)
- Professional information (role, company, etc.)

### Preferences
- Communication style (formal/informal)
- Language preferences
- Timezone and working hours
- Notification preferences
- Tool and service preferences

### Relationships
- Important contacts and their roles
- Team members and colleagues
- Family and friends
- Professional relationships

### Patterns & Habits
- Recurring tasks and workflows
- Common requests and responses
- Decision patterns
- Problem-solving approaches

### Commitments & Tasks
- Promises and commitments made
- Deadlines and due dates
- Action items from conversations
- Goals and objectives

## Memory Format

### Canonical Markdown Format

```markdown
<!-- aqv1 -->
## Identity

**Name**: John Doe
**Email**: john@example.com
**Role**: Software Engineer
**Timezone**: America/New_York

## Preferences

**Communication**: Prefer informal, direct responses
**Language**: English
**Working Hours**: 9 AM - 6 PM EST

## Relationships

**Manager**: Jane Smith (jane@company.com)
**Team**: Engineering Team
<!-- aqv1 -->
```

### Key Naming Conventions

- **Identity**: `identity.name`, `identity.email`, `identity.role`
- **Preferences**: `prefs.communication`, `prefs.language`, `prefs.timezone`
- **Relationships**: `relationships.manager`, `relationships.team`
- **Patterns**: `patterns.email_triage`, `patterns.meeting_prep`
- **Commitments**: `commitments.deadline_2024-01-15`, `commitments.action_item_123`

## Memory Management

### Viewing Memory

**Web UI**: Settings → Memory viewer
- Browse all memories by category
- Search and filter memories
- Edit and delete memories
- View memory statistics

**API**: `GET /api/v1/memory`
- List memories with pagination
- Filter by tags and importance
- Export memory data

### Editing Memory

**Manual Editing**:
1. Navigate to `data/users/<user_id>/memory_workspace/`
2. Edit markdown files directly
3. Changes automatically sync to vector database

**Web UI**:
1. Go to Settings → Memory
2. Find the memory entry
3. Edit content, importance, or tags
4. Save changes

### Resetting Memory

**Warning**: This is irreversible and deletes all memory data.

**API**: `POST /api/v1/memory/reset`
- Deletes all `agent_memories` rows
- Removes entire `memory_workspace` directory
- Returns confirmation with deletion summary

## Memory Best Practices

### For Users

1. **Be Specific**: Use clear, descriptive memory keys
2. **Add Context**: Include relevant context in memory content
3. **Use Tags**: Tag memories for easy filtering and retrieval
4. **Review Regularly**: Periodically review and update memories
5. **Set Importance**: Use importance scores to prioritize memories

### For Developers

1. **Canonical First**: Always write to canonical markdown first
2. **Sync After**: Reindex vector database after canonical changes
3. **Handle Conflicts**: Resolve conflicts between canonical and vector data
4. **Monitor Growth**: Watch memory size and consolidate regularly
5. **Backup Regularly**: Keep backups of canonical memory files

## Memory API Reference

### List Memories

```http
GET /api/v1/memory?limit=200
```

**Response**:
```json
[
  {
    "id": 1,
    "key": "identity.name",
    "content": "John Doe",
    "importance": 10,
    "tags": ["identity", "personal"],
    "updated_at": "2024-01-15T10:30:00Z"
  }
]
```

### Recall Memory

```http
POST /api/v1/memory/recall
Content-Type: application/json

{
  "query": "what's my name",
  "tags": ["identity"],
  "limit": 5
}
```

**Response**:
```json
{
  "hits": [
    {
      "key": "identity.name",
      "content": "John Doe",
      "similarity": 0.95,
      "importance": 10
    }
  ]
}
```

### Upsert Memory

```http
POST /api/v1/memory
Content-Type: application/json

{
  "key": "prefs.communication",
  "content": "Prefer informal, direct responses",
  "importance": 5,
  "tags": ["preferences", "communication"]
}
```

### Delete Memory

```http
DELETE /api/v1/memory/{key}
```

## Troubleshooting

### Memory Not Updating

**Symptoms**: Changes to memory not reflected in agent responses

**Solutions**:
1. Check vector database sync: `AgentMemoryService.reindex_db_from_canonical()`
2. Verify memory extraction is enabled: `AGENT_MEMORY_POST_TURN_ENABLED=true`
3. Check agent logs for extraction errors

### Poor Search Results

**Symptoms**: Memory search returning irrelevant results

**Solutions**:
1. Improve memory content with more context
2. Use more specific queries
3. Add relevant tags to memories
4. Check embedding model is working correctly

### Memory Growing Too Large

**Symptoms**: Memory system becoming slow or unwieldy

**Solutions**:
1. Enable consolidation: `AGENT_MEMORY_CONSOLIDATION_ENABLED=true`
2. Reduce consolidation interval: `AGENT_MEMORY_CONSOLIDATION_MINUTES=180`
3. Manually review and delete old memories
4. Adjust importance thresholds

## Advanced Topics

### Custom Memory Extraction

Implement custom extraction logic by extending `AgentMemoryPostTurnService`:

```python
class CustomMemoryExtraction(AgentMemoryPostTurnService):
    async def extract_custom_facts(self, user_message, assistant_message):
        # Custom extraction logic
        pass
```

### Memory Plugins

Create memory plugins for specific domains:

```python
class EmailMemoryPlugin:
    def extract_email_patterns(self, email_content):
        # Extract email-specific patterns
        pass
```

### Cross-User Memory

Share memories between users with appropriate permissions:

```python
async def share_memory(source_user, target_user, memory_key):
    # Share memory with permission checks
    pass
```

## Performance Considerations

### Vector Search Performance

- **Indexing**: Ensure pgvector indexes are properly configured
- **Batching**: Batch multiple memory operations for efficiency
- **Caching**: Cache frequently accessed memories
- **Limit Results**: Use appropriate limits for search queries

### Memory Storage Efficiency

- **Compression**: Compress old memory files
- **Archiving**: Archive rarely-accessed memories
- **Cleanup**: Regular cleanup of temporary memories
- **Monitoring**: Monitor memory growth and performance

## Security & Privacy

### Data Protection

- **Encryption**: Encrypt sensitive memory content
- **Access Control**: Implement proper user permissions
- **Audit Logging**: Log all memory access and modifications
- **Data Retention**: Implement appropriate data retention policies

### Privacy Considerations

- **Consent**: Obtain user consent for memory collection
- **Transparency**: Make memory collection and usage transparent
- **Control**: Provide users with control over their memory data
- **Compliance**: Ensure compliance with relevant privacy regulations

## Conclusion

The Agent Aquila memory system provides a comprehensive, context-aware storage solution that grows with the user over time. By combining canonical markdown storage with vector-based semantic search, it offers both human readability and machine-queryable memory that enhances the agent's ability to provide personalized, contextually relevant assistance.

The system is designed to be extensible, efficient, and privacy-conscious, making it suitable for both personal and team use cases where data sovereignty and control are paramount.
