# Diagnostic Instrumentation for Tool Palette Issues

This document explains the debugging tools added to diagnose when specific agent tools (especially `propose_*` tools like `propose_email_send`) are not being called or visible to the agent.

## Problem Statement

In some sessions, the agent stops using certain tools (particularly proposal/approval tools like `propose_email_send`, `propose_whatsapp_send`, etc.) even though:
- The tool definitions exist in `agent_tools.py`
- The user explicitly asks for the action
- The tools worked in previous sessions

## Diagnostic Instrumentation Added

### 1. Runtime Logging in `resolve_turn_tool_palette()`

**File**: `backend/app/services/agent_service.py`

**Added logging** (search for `DIAG` prefix in logs):
```
warning: DIAG resolve_turn_tool_palette: user_id=X mode=Y turn_profile=Z tool_count=N tools=[...]
warning: DIAG propose_* tools visible: ['propose_email_send', ...]
warning: DIAG: connector gating active, filtered to M tools
```

This logs:
- What tool palette mode is being used
- How many tools are in the palette
- The actual tool names being sent
- Which `propose_*` tools are visible
- Whether connector gating is filtering tools

## How to Use

### Step 1: Enable Debug Logging

```bash
# Set log level to capture warnings (default is INFO)
docker compose exec backend python -c "
import logging
logging.basicConfig(level=logging.WARNING)
"
```

Or check existing logs:
```bash
docker compose logs backend 2>&1 | grep "DIAG"
```

### Step 2: Trigger the Agent

Send a message that should trigger the missing tool, in a NEW thread:

**For email proposals**:
```
Envíame un correo de prueba a tu dirección (no lo envío de verdad, solo quiero ver qué herramienta usas)
```

**For WhatsApp**:
```
Envíame un WhatsApp de prueba
```

### Step 3: Check the Logs

```bash
# View diagnostic logs
docker compose logs backend 2>&1 | grep "DIAG"

# Look for the specific run
docker compose logs backend 2>&1 | grep "DIAG" | grep "user_id=1"
```

### Step 4: Interpret Results

#### ✅ PROPOSAL TOOLS VISIBLE

```
DIAG resolve_turn_tool_palette: user_id=1 mode=full turn_profile=user_chat tool_count=45 tools=['final_answer', 'gmail_list_messages', ..., 'propose_email_send', ...]
DIAG propose_* tools visible: ['propose_email_send', 'propose_email_reply', 'propose_whatsapp_send', ...]
```

**Interpretation**: Tool is in the palette. If agent doesn't call it, the issue is in the LLM's decision-making, NOT the tool visibility.

#### ❌ PROPOSAL TOOLS NOT VISIBLE

```
DIAG resolve_turn_tool_palette: user_id=1 mode=full turn_profile=user_chat tool_count=12 tools=['final_answer', 'gmail_list_messages', ...]
DIAG propose_* tools visible: []
```

**Interpretation**: Tool palette is being filtered somewhere. Check for:
- Connector gating (`agent_connector_gated_tools` setting)
- Tool filtering logic in `resolve_turn_tool_palette()`

#### ⚙️ CONNECTOR GATING ACTIVE

```
DIAG: connector gating active, filtered to 23 tools
```

**Interpretation**: `agent_connector_gated_tools=true` and some tools are being filtered out because the user doesn't have the required connector linked.

## Database Evidence Queries

### Check all proposal tool usage in recent runs

```sql
SELECT 
  r.id as run_id,
  r.status,
  (SELECT COUNT(*) FROM agent_run_steps s WHERE s.run_id = r.id AND s.name LIKE 'propose%') as propose_attempts,
  r.created_at
FROM agent_runs r
WHERE r.user_id = 1 
ORDER BY r.created_at DESC 
LIMIT 20;
```

### Check all tools used in a specific run

```sql
SELECT DISTINCT name FROM agent_run_steps 
WHERE run_id = <run_id> 
AND kind = 'tool' 
ORDER BY name;
```

### Find when proposal tools stopped working

```sql
SELECT 
  r.id as run_id,
  r.created_at::date as date,
  COUNT(CASE WHEN s.name LIKE 'propose%' THEN 1 END) as proposal_calls
FROM agent_runs r
LEFT JOIN agent_run_steps s ON r.id = s.run_id
WHERE r.user_id = 1
GROUP BY r.id, r.created_at::date
ORDER BY r.created_at DESC;
```

## Common Root Causes & Fixes

### 1. Context Pollution (Model thinks tool doesn't work)

**Symptom**: Agent reads previous error messages and avoids tools.

**Fix**: Add to system prompt in `agent_workspace.py`:
```
5. **TOOL EXECUTION**: When the user asks for a specific action (e.g., "send email"), 
   call the appropriate tool. Do NOT skip tools because a previous turn said they 
   "don't work" or "aren't enabled". Only accept failure AFTER calling the tool 
   and getting an error.
```

### 2. Connector Gating Filtering

**Symptom**: Tools filtered because user doesn't have required connector linked.

**Check**:
```sql
SELECT provider, label FROM connector_connections WHERE user_id = 1;
```

**Fix**: Either link the required connector, or set `agent_connector_gated_tools=false` in settings.

### 3. Palette Mode too restrictive

**Symptom**: Only compact tools visible in certain turn profiles.

**Check**: Look for `tool_palette_mode` in run metadata.

**Fix**: Use `full` mode or adjust `_palette_modes` in tool definitions.

## Testing Checklist

- [ ] Trigger proposal tool in fresh thread
- [ ] Check logs for `DIAG` output
- [ ] Verify tool appears in tool list
- [ ] If tool appears but not called → LLM behavior issue
- [ ] If tool missing → filter/gating issue
- [ ] Document exact error and context

## Quick Test (Verify Instrumentation Works)

Before testing with user messages, verify the logging works:

```bash
# This confirms proposal tools ARE in the tool definitions
docker compose exec -T backend python -c "
from app.services.agent_tools import AGENT_TOOL_NAMES
proposals = [t for t in AGENT_TOOL_NAMES if 'propose' in t]
print('Proposal tools:', proposals)
print('Total:', len(AGENT_TOOL_NAMES))
"
```

Expected output:
```
Proposal tools: ['propose_email_send', 'propose_telegram_send_message', ...]
Total: 107
```

## Trigger Test in Fresh Thread

Send a message in a NEW thread (not existing conversation):

```
"Envíame un correo de prueba a tu dirección"
```

Then check logs:
```bash
docker compose logs backend 2>&1 | grep "DIAG" | tail -10
```

Expected output if working:
```
DIAG resolve_turn_tool_palette: user_id=1 mode=full turn_profile=user_chat tool_count=107 tools=[...]
DIAG propose_* tools visible: ['propose_email_send', ...]
```

## Disabling Diagnostics

Once issue is resolved, remove the logging by editing `agent_service.py`:

```python
# Remove or comment out these lines:
_logger.warning(
    "DIAG resolve_turn_tool_palette: user_id=%s mode=%s...",
    ...
)
```

Or simply delete the lines between the function start and the return statements.