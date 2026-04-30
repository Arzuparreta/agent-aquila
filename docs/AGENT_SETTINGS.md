# Agent Runtime Settings - Configuration Guide

## Overview

Agent Aquila provides comprehensive configuration options for agent behavior through a two-tier system: **environment variables** for deployment defaults and **per-user settings** for individual customization. This guide covers all available settings, their purposes, and how to configure them.

## Configuration Architecture

### Two-Tier System

1. **Environment Variables** - Server-wide defaults that apply to all users
2. **Per-User Settings** - Individual overrides stored in the database

### Merge Logic

```
Effective Value = User Override (if set) OR Environment Default (if set) OR Code Default
```

- **Missing keys** in user settings fall back to environment defaults
- **Partial updates** via API merge with existing settings
- **Clear overrides** by sending `null` for specific fields or entire config

## Configuration Categories

### 1. Agent Behavior Settings

#### Rate Limiting

| Setting | Environment Variable | Default | Description |
|---------|---------------------|---------|-------------|
| Max runs per hour | `AGENT_MAX_RUNS_PER_HOUR` | 30 | Maximum agent runs per user per hour |
| Rate limit window | `AGENT_RATE_LIMIT_WINDOW_HOURS` | 1 | Time window for rate limiting |

#### Tool Execution

| Setting | Environment Variable | Default | Description |
|---------|---------------------|---------|-------------|
| Max steps per run | `AGENT_MAX_STEPS` | 20 | Maximum tool calls per agent run |
| Tool palette mode | `AGENT_TOOL_PALETTE` | `full` | Tool palette: `full`, `compact`, `minimal` |
| Connector gating | `AGENT_CONNECTOR_GATED_TOOLS` | `true` | Only show tools for connected providers |

#### Memory & Context

| Setting | Environment Variable | Default | Description |
|---------|---------------------|---------|-------------|
| Memory post-turn enabled | `AGENT_MEMORY_POST_TURN_ENABLED` | `true` | Enable automatic memory extraction |
| Memory post-turn mode | `AGENT_MEMORY_POST_TURN_MODE` | `committee` | Extraction mode: `heuristic`, `committee`, `always` |
| Memory flush enabled | `AGENT_MEMORY_FLUSH_ENABLED` | `true` | Enable memory flush before compaction |
| Memory flush max steps | `AGENT_MEMORY_FLUSH_MAX_STEPS` | 8 | Max steps for memory flush run |
| User context injection | `AGENT_INJECT_USER_CONTEXT_IN_CHAT` | `true` | Inject user context in chat turns |

#### Harness & Prompt

| Setting | Environment Variable | Default | Description |
|---------|---------------------|---------|-------------|
| Harness mode | `AGENT_HARNESS_MODE` | `native` | LLM harness: `native`, `prompted`, `auto` |
| Prompt tier | `AGENT_PROMPT_TIER` | `full` | Prompt detail: `full`, `minimal`, `none` |
| Include harness facts | `AGENT_INCLUDE_HARNESS_FACTS` | `true` | Include harness metadata in prompt |

#### Chat & History

| Setting | Environment Variable | Default | Description |
|---------|---------------------|---------|-------------|
| Chat history window | `AGENT_CHAT_HISTORY_WINDOW` | 10 | Number of messages to include in context |
| Token-aware history | `AGENT_TOKEN_AWARE_HISTORY` | `true` | Use token counting for history selection |
| Context budget v2 | `AGENT_CONTEXT_BUDGET_V2` | `true` | Use improved context budgeting |

#### Async & Background

| Setting | Environment Variable | Default | Description |
|---------|---------------------|---------|-------------|
| Async runs enabled | `AGENT_ASYNC_RUNS` | `true` | Enable async agent execution |
| Non-chat compact palette | `AGENT_NON_CHAT_USES_COMPACT_PALETTE` | `true` | Use compact palette for non-chat turns |

### 2. Heartbeat & Automation Settings

| Setting | Environment Variable | Default | Description |
|---------|---------------------|---------|-------------|
| Heartbeat enabled | `AGENT_HEARTBEAT_ENABLED` | `false` | Enable scheduled heartbeat runs |
| Heartbeat cron | `AGENT_HEARTBEAT_CRON` | `0 9 * * 1` | Cron schedule for heartbeat |
| Heartbeat check Gmail | `AGENT_HEARTBEAT_CHECK_GMAIL` | `false` | Include Gmail in heartbeat |
| Heartbeat skill | `AGENT_HEARTBEAT_SKILL` | `weekly-review` | Skill to run on heartbeat |

### 3. Channel & Gateway Settings

| Setting | Environment Variable | Default | Description |
|---------|---------------------|---------|-------------|
| Channel gateway enabled | `AGENT_CHANNEL_GATEWAY_ENABLED` | `false` | Enable channel gateway endpoint |
| Telegram enabled | `TELEGRAM_BOT_ENABLED` | `false` | Enable Telegram bot integration |

### 4. Safety & Approval Settings

| Setting | Environment Variable | Default | Description |
|---------|---------------------|---------|-------------|
| Proposal system enabled | `AGENT_PROPOSAL_SYSTEM_ENABLED` | `true` | Enable proposal system for sensitive actions |
| Outbound email allowlist | `AGENT_OUTBOUND_EMAIL_ALLOWLIST` | `*` | Allowed email domains for outbound |
| Auto-approve low risk | `AGENT_AUTO_APPROVE_LOW_RISK` | `false` | Auto-approve low-risk proposals |

### 5. Memory System Settings

| Setting | Environment Variable | Default | Description |
|---------|---------------------|---------|-------------|
| Consolidation enabled | `AGENT_MEMORY_CONSOLIDATION_ENABLED` | `true` | Enable periodic memory consolidation |
| Consolidation minutes | `AGENT_MEMORY_CONSOLIDATION_MINUTES` | 360 | Consolidation interval in minutes |
| Post-turn extraction enabled | `AGENT_MEMORY_POST_TURN_ENABLED` | `true` | Enable post-turn memory extraction |

### 6. Performance & Optimization Settings

| Setting | Environment Variable | Default | Description |
|---------|---------------------|---------|-------------|
| Dynamic model limits | `AGENT_DYNAMIC_MODEL_LIMITS` | `true` | Use dynamic model context limits |
| Compact history on overflow | `AGENT_COMPACT_HISTORY_ON_OVERFLOW` | `true` | Compact history when context overflows |
| Max transcript chars | `AGENT_MAX_TRANSCRIPT_CHARS` | 16000 | Maximum transcript characters |

## API Configuration

### Get Current Settings

```http
GET /api/v1/ai/settings
```

**Response**:
```json
{
  "agent_runtime": {
    "agent_max_runs_per_hour": 30,
    "agent_max_steps": 20,
    "agent_tool_palette": "full",
    "agent_memory_post_turn_enabled": true,
    "agent_async_runs": true,
    "agent_harness_mode": "native",
    "agent_prompt_tier": "full"
  }
}
```

### Update Settings

```http
PATCH /api/v1/ai/settings
Content-Type: application/json

{
  "agent_runtime": {
    "agent_max_steps": 25,
    "agent_tool_palette": "compact"
  }
}
```

**Response**: Updated settings with merged values

### Clear Override

```http
PATCH /api/v1/ai/settings
Content-Type: application/json

{
  "agent_runtime": {
    "agent_max_steps": null
  }
}
```

**Result**: Falls back to environment default for `agent_max_steps`

### Clear All Overrides

```http
PATCH /api/v1/ai/settings
Content-Type: application/json

{
  "agent_runtime": null
}
```

**Result**: All settings revert to environment defaults

## UI Configuration

### Settings → Agent Behavior

The web UI provides a user-friendly interface for configuring agent settings:

- **Rate Limits**: Configure maximum runs per hour
- **Tool Execution**: Adjust tool palette and connector gating
- **Memory & Context**: Enable/disable memory features
- **Harness & Prompt**: Choose harness mode and prompt tier
- **Chat & History**: Configure history window and context budgeting
- **Async & Background**: Enable/disable async execution

## Environment Configuration

### Docker Compose

```yaml
# docker-compose.yml
services:
  backend:
    environment:
      - AGENT_MAX_RUNS_PER_HOUR=30
      - AGENT_MAX_STEPS=20
      - AGENT_TOOL_PALETTE=full
      - AGENT_MEMORY_POST_TURN_ENABLED=true
      - AGENT_ASYNC_RUNS=true
      - AGENT_HEARTBEAT_ENABLED=false
```

### .env File

```bash
# Agent Behavior
AGENT_MAX_RUNS_PER_HOUR=30
AGENT_MAX_STEPS=20
AGENT_TOOL_PALETTE=full
AGENT_CONNECTOR_GATED_TOOLS=true

# Memory & Context
AGENT_MEMORY_POST_TURN_ENABLED=true
AGENT_MEMORY_POST_TURN_MODE=committee
AGENT_INJECT_USER_CONTEXT_IN_CHAT=true

# Harness & Prompt
AGENT_HARNESS_MODE=native
AGENT_PROMPT_TIER=full
AGENT_INCLUDE_HARNESS_FACTS=true

# Chat & History
AGENT_CHAT_HISTORY_WINDOW=10
AGENT_TOKEN_AWARE_HISTORY=true
AGENT_CONTEXT_BUDGET_V2=true

# Async & Background
AGENT_ASYNC_RUNS=true
AGENT_NON_CHAT_USES_COMPACT_PALETTE=true

# Heartbeat & Automation
AGENT_HEARTBEAT_ENABLED=false
AGENT_HEARTBEAT_CRON="0 9 * * 1"
AGENT_HEARTBEAT_CHECK_GMAIL=false

# Channel & Gateway
AGENT_CHANNEL_GATEWAY_ENABLED=false
TELEGRAM_BOT_ENABLED=false

# Safety & Approval
AGENT_PROPOSAL_SYSTEM_ENABLED=true
AGENT_OUTBOUND_EMAIL_ALLOWLIST="*"
AGENT_AUTO_APPROVE_LOW_RISK=false

# Memory System
AGENT_MEMORY_CONSOLIDATION_ENABLED=true
AGENT_MEMORY_CONSOLIDATION_MINUTES=360

# Performance & Optimization
AGENT_DYNAMIC_MODEL_LIMITS=true
AGENT_COMPACT_HISTORY_ON_OVERFLOW=true
AGENT_MAX_TRANSCRIPT_CHARS=16000
```

## Common Configuration Patterns

### Development Setup

```bash
# Relaxed limits for development
AGENT_MAX_RUNS_PER_HOUR=100
AGENT_MAX_STEPS=50
AGENT_ASYNC_RUNS=false  # Sync for easier debugging
AGENT_INCLUDE_HARNESS_FACTS=true  # More visibility
```

### Production Setup

```bash
# Conservative limits for production
AGENT_MAX_RUNS_PER_HOUR=30
AGENT_MAX_STEPS=20
AGENT_ASYNC_RUNS=true  # Better performance
AGENT_PROPOSAL_SYSTEM_ENABLED=true  # Safety first
AGENT_RATE_LIMIT_WINDOW_HOURS=1
```

### Resource-Constrained Setup

```bash
# Optimized for limited resources
AGENT_MAX_STEPS=15
AGENT_TOOL_PALETTE=compact
AGENT_PROMPT_TIER=minimal
AGENT_CHAT_HISTORY_WINDOW=5
AGENT_TOKEN_AWARE_HISTORY=true
```

### Privacy-Focused Setup

```bash
# Maximum privacy and control
AGENT_PROPOSAL_SYSTEM_ENABLED=true
AGENT_AUTO_APPROVE_LOW_RISK=false
AGENT_OUTBOUND_EMAIL_ALLOWLIST="example.com"
AGENT_MEMORY_POST_TURN_ENABLED=false  # Manual memory only
```

## Troubleshooting

### Settings Not Taking Effect

**Symptoms**: Changes to settings not reflected in agent behavior

**Solutions**:
1. Check if user override is set (takes precedence over env vars)
2. Verify environment variables are properly loaded
3. Restart backend service after changing environment variables
4. Check for conflicting settings in different configuration sources

### Rate Limiting Issues

**Symptoms**: Agent runs being blocked or rate limit errors

**Solutions**:
1. Increase `AGENT_MAX_RUNS_PER_HOUR` for legitimate use cases
2. Adjust `AGENT_RATE_LIMIT_WINDOW_HOURS` for different time windows
3. Check for stuck rate limit counters in Redis
4. Verify user-specific overrides aren't too restrictive

### Memory Issues

**Symptoms**: Memory not being extracted or consolidated

**Solutions**:
1. Verify `AGENT_MEMORY_POST_TURN_ENABLED=true`
2. Check `AGENT_MEMORY_POST_TURN_MODE` is appropriate
3. Ensure consolidation is enabled: `AGENT_MEMORY_CONSOLIDATION_ENABLED=true`
4. Check worker process is running for consolidation

### Performance Issues

**Symptoms**: Slow agent responses or high resource usage

**Solutions**:
1. Enable async runs: `AGENT_ASYNC_RUNS=true`
2. Reduce history window: `AGENT_CHAT_HISTORY_WINDOW=5`
3. Use compact palette: `AGENT_TOOL_PALETTE=compact`
4. Enable token-aware history: `AGENT_TOKEN_AWARE_HISTORY=true`

## Advanced Configuration

### Custom Rate Limiting

Implement custom rate limiting logic:

```python
# backend/app/services/custom_rate_limit.py
class CustomRateLimitService:
    async def check_custom_limits(self, user_id: int):
        # Custom rate limiting logic
        pass
```

### Dynamic Settings

Implement settings that change based on conditions:

```python
# backend/app/services/dynamic_settings.py
class DynamicSettingsService:
    async def get_dynamic_settings(self, user_id: int):
        # Return settings based on user tier, usage, etc.
        pass
```

### Settings Validation

Add validation for settings values:

```python
# backend/app/schemas/agent_runtime_config.py
class AgentRuntimeConfig(BaseModel):
    agent_max_steps: int = Field(ge=1, le=100)
    agent_max_runs_per_hour: int = Field(ge=1, le=1000)
    # Add validation for other settings
```

## Migration & Upgrades

### Settings Migration

When adding new settings:

1. Add environment variable with sensible default
2. Update Pydantic models in `agent_runtime_config.py`
3. Add UI components in `agent-runtime-section.tsx`
4. Update documentation
5. Test with both environment and user overrides

### Backward Compatibility

Maintain backward compatibility:

1. Keep old environment variables working
2. Provide migration paths for deprecated settings
3. Document breaking changes clearly
4. Test upgrade scenarios

## Security Considerations

### Sensitive Settings

Some settings should be environment-only:

- Database credentials
- API keys and secrets
- OAuth application credentials
- Encryption keys

### User Overrides

Limit what users can override:

- Rate limits (within reasonable bounds)
- Tool palette (but not security-critical tools)
- Memory settings (but not security features)
- UI preferences (full control)

### Audit Logging

Log settings changes:

```python
# backend/app/services/audit_service.py
async def log_settings_change(user_id: int, old_settings, new_settings):
    # Log settings changes for audit trail
    pass
```

## Best Practices

### For Operators

1. **Use Environment Variables**: Set sensible defaults via environment
2. **Document Changes**: Keep documentation updated with new settings
3. **Test Thoroughly**: Test settings changes in staging first
4. **Monitor Impact**: Watch for performance and user experience impact
5. **Provide Guidance**: Help users understand settings implications

### For Users

1. **Start with Defaults**: Use default settings initially
2. **Adjust Gradually**: Make small changes and observe effects
3. **Understand Trade-offs**: Each setting has pros and cons
4. **Monitor Usage**: Watch your usage patterns and adjust accordingly
5. **Reset if Needed**: Clear overrides to return to defaults

## Conclusion

Agent Aquila's configuration system provides flexible, granular control over agent behavior while maintaining sensible defaults and safety guards. The two-tier architecture allows operators to set deployment-wide standards while giving users the freedom to customize their experience.

By understanding the available settings and their implications, you can optimize Agent Aquila for your specific use case, whether that's development, production, resource-constrained environments, or privacy-focused deployments.
