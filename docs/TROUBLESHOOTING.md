# Troubleshooting Guide

## Overview

This guide covers common issues, error patterns, and solutions for Agent Aquila. Use this page for startup failures, proxy errors, database issues, and long-running task stalls.

## Quick Diagnostics

### Health Check

```bash
# Check all services
docker compose ps

# Check backend logs
docker compose logs backend

# Check frontend logs
docker compose logs frontend

# Check worker logs
docker compose logs worker

# Check database connection
docker compose exec backend python -c "from app.core.database import get_db; print('DB OK')"
```

### Common Issues Quick Reference

| Symptom | Likely Cause | Quick Fix |
|---------|--------------|-----------|
| Backend exits immediately | Database migration issue | Run `alembic upgrade head` |
| Frontend shows 500 errors | Backend not responding | Check backend logs and restart |
| Chat stalls with "..." | Worker not running | Check Redis and worker status |
| OAuth redirect fails | Redirect URI not registered | Add URI to Google Cloud Console |
| Agent not responding | AI provider not configured | Check AI settings in UI |
| Memory not working | pgvector not installed | Install pgvector extension |

## Startup Issues

### Backend Container Exits Immediately

**Symptoms**: Backend container shows `Exited (1)` right after startup

**Common Causes**:

1. **Database Migration Issues**
   ```bash
   # Check logs
   docker logs backend
   
   # Run migrations manually
   docker compose exec backend alembic upgrade head
   ```

2. **Alembic Version Column Error**
   - **Error**: `StringDataRightTruncationError`, `character varying(32)`, `alembic_version`
   - **Cause**: PostgreSQL `alembic_version.version_num` too short for migration revision
   - **Fix**: The system auto-widens this column, but verify `backend/alembic/env.py` helper exists

3. **Missing Environment Variables**
   ```bash
   # Check required variables
   docker compose config | grep -v "^\s*#"
   
   # Ensure .env file exists
   cp .env.example .env
   ```

### Frontend 500 Errors

**Symptoms**: Frontend shows 500 errors, mentions Next.js proxy or `BACKEND_INTERNAL_URL`

**Diagnosis**:
```bash
# Check if backend is running
curl http://localhost:8000/health

# Check backend logs first
docker compose logs backend --tail 50

# Check frontend logs
docker compose logs frontend --tail 50
```

**Solutions**:
1. Ensure backend is running and healthy
2. Check `BACKEND_INTERNAL_URL` environment variable
3. Verify network connectivity between containers
4. Restart both services: `docker compose restart`

### Database Connection Issues

**Symptoms**: Connection refused, timeout, or authentication errors

**Diagnosis**:
```bash
# Test database connection
docker compose exec db psql -U aquila_user -d aquila_db -c "SELECT 1"

# Check database logs
docker compose logs db

# Verify database is ready
docker compose exec backend python -c "
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
async def test():
    engine = create_async_engine('postgresql+asyncpg://aquila_user:aquila_password@db:5432/aquila_db')
    async with engine.begin() as conn:
        await conn.execute('SELECT 1')
    print('DB OK')
asyncio.run(test())
"
```

**Solutions**:
1. Ensure database container is running: `docker compose up -d db`
2. Check connection string in `.env`
3. Verify database credentials
4. Wait for database to fully start (may take 10-30 seconds)

## Runtime Issues

### Chat Stalls or Hangs

**Symptoms**: Chat interface shows "..." indefinitely, agent responses never complete

**Diagnosis**:
```bash
# Check if worker is running
docker compose ps worker

# Check worker logs
docker compose logs worker --tail 50

# Check Redis connection
docker compose exec redis redis-cli ping

# Check async settings
docker compose exec backend env | grep AGENT_ASYNC_RUNS
```

**Solutions**:
1. Ensure worker is running: `docker compose up -d worker`
2. Verify Redis is accessible: `REDIS_URL` must be set
3. Enable async runs: `AGENT_ASYNC_RUNS=true`
4. Check for stuck jobs in Redis queue

### Agent Not Responding

**Symptoms**: Agent doesn't respond to messages, shows errors

**Diagnosis**:
```bash
# Check AI provider configuration
docker compose logs backend | grep -i "provider\|api.*key\|model"

# Test AI provider connection
# (Use the UI Settings → AI → Test Connection)
```

**Solutions**:
1. Configure AI provider in Settings → AI
2. Verify API key is valid and has credits
3. Check model is available and supported
4. Test connection in UI before using agent

### Step Budget Exceeded

**Symptoms**: Agent stops with "Step budget exceeded" error

**Solutions**:
1. Increase limit: `AGENT_MAX_STEPS=25` in `.env`
2. Reduce tool rounds in current task
3. Break complex task into smaller steps
4. Use more efficient tools (e.g., bulk operations)

### Harness Mode Errors

**Symptoms**: Errors related to tool calling, harness mode, or LLM compatibility

**Solutions**:
1. Agent Aquila uses native tool calling only
2. If provider doesn't support `tools=` parameter:
   - Switch to Ollama with supporting model (watt-tool-8B, qwen3-coder)
   - Use OpenRouter or LiteLLM as proxy
   - See [PROVIDERS.md](./PROVIDERS.md) for details

## OAuth Issues

### OAuth Redirect Fails

**Symptoms**: OAuth redirect points to wrong URL, authentication fails

**Diagnosis**:
```bash
# Check OAuth configuration
docker compose logs backend | grep -i "oauth\|redirect"

# Verify redirect base URL
docker compose exec backend env | grep REDIRECT_BASE
```

**Solutions**:
1. Register the exact redirect URIs in Google Cloud Console. The origin must match **Settings → Connectors → Public URL** (Google rejects raw private IPs). Typical cases:
   - `http://localhost:3002/api/v1/oauth/google/callback` (local browser on the Docker host only)
   - `https://your-domain.com/api/v1/oauth/google/callback` (VPS or reverse proxy)
   - `https://your-machine.your-tailnet.ts.net/api/v1/oauth/google/callback` when using **Tailscale Serve** on the host (`tailscale serve --bg 3002`) — use **Serve**, not **Funnel**, unless you want a public URL

2. For Microsoft OAuth, register URIs in Azure AD app registration (same origin pattern, path `/api/v1/oauth/microsoft/callback`).

3. Google and Microsoft require exact URI matching; set **Public URL** in Aquila to the same HTTPS origin you registered.

### Token Refresh Errors

**Symptoms**: "Connector needs re-authentication", token expired errors

**Solutions**:
1. Re-authenticate the connector in Settings → Connectors
2. Check OAuth app credentials are valid
3. Verify redirect URIs are properly configured
4. Check for revoked permissions in provider console

## Memory Issues

### Memory Not Working

**Symptoms**: Agent doesn't remember information, memory search returns nothing

**Diagnosis**:
```bash
# Check pgvector extension
docker compose exec db psql -U aquila_user -d aquila_db -c "SELECT * FROM pg_extension WHERE extname = 'vector'"

# Check memory table
docker compose exec db psql -U aquila_user -d aquila_db -c "\d agent_memories"

# Check memory files
ls -la backend/data/users/*/memory_workspace/
```

**Solutions**:
1. Install pgvector extension:
   ```sql
   docker compose exec db psql -U aquila_user -d aquila_db -c "CREATE EXTENSION IF NOT EXISTS vector;"
   ```

2. Verify memory extraction is enabled: `AGENT_MEMORY_POST_TURN_ENABLED=true`

3. Check memory files exist and are readable

4. Reindex memory from canonical files

### Memory Growing Too Large

**Symptoms**: Memory system slow, excessive disk usage

**Solutions**:
1. Enable consolidation: `AGENT_MEMORY_CONSOLIDATION_ENABLED=true`
2. Reduce consolidation interval: `AGENT_MEMORY_CONSOLIDATION_MINUTES=180`
3. Manually review and delete old memories
4. Adjust importance thresholds

## Performance Issues

### Slow Agent Responses

**Symptoms**: Agent takes long time to respond, high latency

**Diagnosis**:
```bash
# Check system resources
docker stats

# Check database performance
docker compose exec db psql -U aquila_user -d aquila_db -c "SELECT * FROM pg_stat_activity;"

# Check Redis performance
docker compose exec redis redis-cli INFO stats
```

**Solutions**:
1. Enable async runs: `AGENT_ASYNC_RUNS=true`
2. Reduce history window: `AGENT_CHAT_HISTORY_WINDOW=5`
3. Use compact palette: `AGENT_TOOL_PALETTE=compact`
4. Enable token-aware history: `AGENT_TOKEN_AWARE_HISTORY=true`
5. Check for slow database queries

### High Resource Usage

**Symptoms**: High CPU, memory, or disk usage

**Solutions**:
1. Check for stuck jobs or infinite loops
2. Reduce concurrent operations
3. Optimize database queries
4. Clear old logs and temporary files
5. Adjust worker concurrency settings

## Connector Issues

### Gmail API Quota Exceeded

**Symptoms**: Gmail rate limit errors, quota exceeded messages

**Solutions**:
1. Reduce Gmail API calls in skills and workflows
2. Use batch operations when possible
3. Implement exponential backoff for retries
4. Consider Gmail API quota increases for production use

### Connector Not Responding

**Symptoms**: Connector timeouts, connection errors

**Diagnosis**:
```bash
# Test connector connection
# (Use Settings → Connectors → Test Connection)

# Check connector logs
docker compose logs backend | grep -i "connector\|gmail\|calendar"
```

**Solutions**:
1. Re-authenticate the connector
2. Check network connectivity to provider
3. Verify OAuth scopes are sufficient
4. Check for provider service outages

## Configuration Issues

### Settings Not Taking Effect

**Symptoms**: Changes to settings not reflected in behavior

**Solutions**:
1. Check for user overrides vs environment defaults
2. Restart backend after changing environment variables
3. Clear browser cache for UI settings
4. Verify settings are properly saved in database

### Environment Variables Not Loading

**Symptoms**: Default values used instead of configured values

**Solutions**:
1. Verify `.env` file exists and is properly formatted
2. Check for syntax errors in `.env` file
3. Ensure environment variables are properly passed to containers
4. Restart services after changing `.env` file

## Database Issues

### Schema Out of Date

**Symptoms**: API returns 503 with `schema_out_of_date` error

**Solutions**:
1. Run Alembic migrations: `docker compose exec backend alembic upgrade head`
2. Restart backend service
3. Check for failed migrations
4. Verify database schema matches expected version

### Database Lock Issues

**Symptoms**: Operations hang, lock timeout errors

**Solutions**:
1. Check for long-running transactions
2. Identify and kill blocking queries
3. Restart database if necessary
4. Optimize database queries and indexes

## Network Issues

### Container Communication Issues

**Symptoms**: Containers can't communicate, connection refused errors

**Solutions**:
1. Verify Docker network configuration
2. Check container names and DNS resolution
3. Ensure services are on same Docker network
4. Restart Docker network if needed

### External API Access Issues

**Symptoms**: Can't reach external APIs, timeout errors

**Solutions**:
1. Check internet connectivity from containers
2. Verify DNS resolution from containers
3. Check firewall and proxy settings
4. Verify external API endpoints are accessible

## Debugging Tools

### Log Analysis

```bash
# Real-time log monitoring
docker compose logs -f

# Filter logs by component
docker compose logs backend | grep -i "error\|exception"

# Check recent logs
docker compose logs --tail 100 backend
```

### Database Inspection

```bash
# Connect to database
docker compose exec db psql -U aquila_user -d aquila_db

# List tables
\dt

# Inspect table schema
\d agent_runs

# Run queries
SELECT * FROM agent_runs ORDER BY created_at DESC LIMIT 10;
```

### Redis Inspection

```bash
# Connect to Redis
docker compose exec redis redis-cli

# Check keys
KEYS *

# Monitor commands
MONITOR

# Check queue status
LLEN arq:queue
```

### API Testing

```bash
# Test health endpoint
curl http://localhost:8000/health

# Test API with authentication
curl -H "Authorization: Bearer <token>" http://localhost:8000/api/v1/agent/runs

# Test WebSocket connection
wscat -c ws://localhost:8000/ws
```

## Getting Help

### Collect Diagnostic Information

```bash
# Create diagnostic bundle
mkdir -p diagnostics
docker compose logs > diagnostics/docker-compose.log
docker compose ps > diagnostics/docker-compose-ps.log
docker stats --no-stream > diagnostics/docker-stats.log
docker compose exec backend env > diagnostics/backend-env.log
```

### Useful Search Terms

- `StringDataRightTruncation` - Alembic version column issues
- `alembic_version` - Migration version tracking
- `_widen_alembic_version_num` - Version column widening
- `AGENT_ASYNC_RUNS` - Async execution settings
- `AGENT_MAX_STEPS` - Tool step limits
- `pgvector` - Vector database extension
- `OAuth redirect` - Authentication redirect issues

### Regression Tests

Reference test files for validation:
- `backend/tests/test_alembic_version_column.py` - Version column tests
- `backend/tests/test_agent_tools.py` - Tool functionality tests
- `backend/tests/test_ai_providers.py` - AI provider tests

## Prevention and Maintenance

### Regular Maintenance Tasks

1. **Database Backups**: Regular database dumps and backups
2. **Log Rotation**: Prevent disk space issues from growing logs
3. **Health Monitoring**: Set up monitoring for critical services
4. **Dependency Updates**: Keep dependencies updated for security

### Monitoring Setup

Consider setting up monitoring for:
- Container health and resource usage
- Database performance and connections
- Redis queue depth and processing time
- API response times and error rates
- Agent success/failure rates

## Conclusion

Most issues with Agent Aquila can be resolved by following the diagnostic steps and solutions in this guide. The key is to identify the component that's failing (backend, frontend, database, worker, or external services) and then apply the appropriate solution.

For issues not covered here, check the logs for specific error messages and consult the relevant documentation for the affected component.
