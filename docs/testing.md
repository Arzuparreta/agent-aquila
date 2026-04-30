# Testing Guide

## Overview

This guide covers the testing framework for Agent Aquila, including automated tests, test organization, and best practices. Automated tests live under `backend/tests/` and use **[pytest](https://pytest.org)** with **pytest-asyncio** (`asyncio_mode = auto` in `backend/pyproject.toml`).

The **frontend** has no unit/e2e test script; use `npm run lint` (Next.js ESLint) for frontend validation.

Background **Redis** and the **ARQ worker** are only used for the optional `agent_heartbeat` cron — they are **not** required to run `pytest`.

## Prerequisites

### Python Environment

- **Python** ≥ 3.11
- **Backend dev dependencies**: install with the `dev` extra. On **PEP 668** systems, use a venv first:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

### Database Setup

**Postgres + pgvector** (for integration tests using `db_session`): migrated schema (`alembic upgrade head`). If the DB is unreachable, those tests **skip** (see `backend/tests/conftest.py`).

**Default test DB URL** (overridable):
```bash
export TEST_DATABASE_URL="postgresql+asyncpg://aquila_user:aquila_password@127.0.0.1:5433/aquila_db"
```

**Typical local setup** (matches the main README):
```bash
docker compose up -d db
cd backend && alembic upgrade head
```

A full `docker compose up` (API + frontend) also runs `alembic upgrade head` when the backend container starts, so pytest against Compose Postgres only needs the one-off `alembic upgrade head` when you are **not** starting the API container.

## Running Tests

### Basic Test Execution

From `backend/`:
```bash
cd backend
pytest
```

### Useful Test Commands

| Command | Purpose |
|----------|---------|
| `pytest -q` | Quiet summary |
| `pytest tests/test_ai_providers.py` | One file |
| `pytest -k "openai"` | Tests whose name contains `openai` |
| `pytest --tb=short` | Shorter tracebacks |
| `pytest -v` | Verbose output |
| `pytest -s` | Show print statements |
| `pytest --cov=app` | Generate coverage report |
| `pytest --cov-report=html` | HTML coverage report |

### Test Organization

```
backend/tests/
├── conftest.py                 # Shared fixtures and configuration
├── test_alembic_version_column.py  # Alembic version column tests
├── test_agent_tools.py          # Agent tool catalog tests
├── test_ai_providers.py         # AI provider adapter tests
├── test_ai_routes.py             # AI API route tests
├── test_capability_registry.py   # Capability registry tests
├── test_chat_threads_list.py     # Chat thread tests
├── test_embedding_vector.py      # Embedding vector tests
├── test_gmail_client.py          # Gmail client tests
├── test_gmail_routes.py          # Gmail API route tests
├── test_gmail_silence_sender.py # Gmail silence sender tests
├── test_agent_trace_channel.py   # Agent trace channel tests
└── test_workspace_sandbox.py     # Workspace sandbox tests
```

## Shared Fixtures

### Available Fixtures (`backend/tests/conftest.py`)

| Fixture | Role | Database Required |
|---------|------|-------------------|
| `anyio_backend` | Asyncio backend for anyio-using code | No |
| `db_session` | Async SQLAlchemy session in a **transaction rolled back** after each test | Yes |
| `aquila_user` | User with Ollama provider and AI enabled (agent tool tests) | Yes |
| `agent_run` | Minimal `AgentRun` row tied to `aquila_user` | Yes |

### Using Fixtures

```python
import pytest
from app.services.agent_service import AgentService

@pytest.mark.asyncio
async def test_agent_execution(db_session, aquila_user):
    # Test agent execution with database session
    result = await AgentService.run_agent(
        db_session,
        aquila_user,
        "test message"
    )
    assert result is not None
```

## Test Modules

### Non-Exhaustive Test Coverage

| Module | DB | Summary |
|--------|----|---------|
| `test_alembic_version_column.py` | No | `alembic_version.version_num` guard in `alembic/env.py` |
| `test_capability_registry.py` | No | Registry keys for proposal kinds |
| `test_ai_providers.py` | No | AI provider adapters (OpenAI, Ollama, Anthropic, OpenRouter, Azure, LiteLLM, custom) |
| `test_ai_routes.py` | No | Provider registry enumeration, API key resolution |
| `test_agent_tools.py` | No | Catalogue structure: bucket disjointness + dispatch coverage |
| `test_gmail_client.py` | No | Gmail 429 parsing; mocked REST JSON shapes |
| `test_gmail_routes.py` | No | FastAPI `TestClient`: body forwarding |
| `test_gmail_silence_sender.py` | Yes | Gmail filter action never adds `SPAM` |
| `test_chat_threads_list.py` | Yes | Thread listing |
| `test_agent_trace_channel.py` | Yes | Trace event ordering |
| `test_embedding_vector.py` | No | Embedding padding to 1536 dims |
| `test_workspace_sandbox.py` | No | Agent workspace file safety |
| `test_github_client.py` | No | GitHub client mocked |
| `test_whatsapp_client.py` | No | WhatsApp client mocked |
| `test_icloud_*` | No | iCloud client mocks |

## Test Categories

### Unit Tests

**Characteristics**:
- No external dependencies
- Fast execution
- Isolated functionality
- Mocked external services

**Examples**:
- `test_ai_providers.py` - AI provider adapter logic
- `test_agent_tools.py` - Tool catalog structure
- `test_capability_registry.py` - Capability registry

### Integration Tests

**Characteristics**:
- Require database connection
- Test component interactions
- Slower execution
- Real database operations

**Examples**:
- `test_chat_threads_list.py` - Thread listing with database
- `test_gmail_silence_sender.py` - Gmail filter operations
- `test_agent_trace_channel.py` - Trace event ordering

### API Tests

**Characteristics**:
- Test HTTP endpoints
- Use FastAPI TestClient
- Validate request/response

**Examples**:
- `test_ai_routes.py` - AI provider API endpoints
- `test_gmail_routes.py` - Gmail API endpoints

## Writing Tests

### Test Structure

```python
import pytest
from app.services.some_service import SomeService

@pytest.mark.asyncio
async def test_service_operation(db_session):
    # Arrange
    service = SomeService(db_session)
    
    # Act
    result = await service.do_something()
    
    # Assert
    assert result is not None
    assert result.status == "success"
```

### Async Tests

```python
@pytest.mark.asyncio
async def test_async_operation():
    # Test async functionality
    result = await some_async_function()
    assert result is not None
```

### Database Tests

```python
@pytest.mark.asyncio
async def test_database_operation(db_session):
    # Test with database session
    from app.models.user import User
    
    user = User(email="test@example.com", hashed_password="hash")
    db_session.add(user)
    await db_session.commit()
    
    assert user.id is not None
```

### Mock Tests

```python
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_with_mock():
    # Mock external service
    with patch('app.services.external_service.call_api') as mock_api:
        mock_api.return_value = {"result": "success"}
        
        result = await some_function()
        
        assert result == "success"
        mock_api.assert_called_once()
```

## Test Configuration

### Pytest Configuration

**File**: `backend/pyproject.toml`

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

### Environment Variables

**Test-specific variables**:
```bash
# Test database URL
export TEST_DATABASE_URL="postgresql+asyncpg://test:test@localhost:5433/test_db"

# Disable certain features for testing
export AGENT_ASYNC_RUNS=false
export AGENT_HEARTBEAT_ENABLED=false
```

## Frontend Testing

### Linting

```bash
cd frontend
npm install
npm run lint
```

### Type Checking

```bash
cd frontend
npm run type-check
```

### Build Verification

```bash
cd frontend
npm run build
```

## Smoke Tests

### AI Provider Smoke Test

After configuring any provider, verify end-to-end:

```bash
docker compose exec backend python -m app.scripts.smoke_ai_provider
```

This exercises the same code paths the agent uses: tool calling, JSON mode, and embeddings.

### Database Smoke Test

```bash
docker compose exec backend python -c "
from app.core.database import get_db
print('Database connection OK')
"
```

### API Smoke Test

```bash
curl http://localhost:8000/health
```

## Test Coverage

### Coverage Report

```bash
cd backend
pytest --cov=app --cov-report=html
```

**Coverage Report Location**: `backend/htmlcov/index.html`

### Coverage Targets

**Minimum Coverage Goals**:
- Core services: 80%+
- API routes: 70%+
- Utilities: 90%+

## Continuous Integration

### CI Pipeline

**Recommended CI Steps**:
1. Install dependencies
2. Run database migrations
3. Execute test suite
4. Generate coverage report
5. Check coverage thresholds
6. Run linting

### GitHub Actions Example

```yaml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          cd backend
          pip install -e ".[dev]"
      - name: Run tests
        run: |
          cd backend
          pytest --cov=app --cov-report=xml
```

## Debugging Tests

### Running Tests in Debug Mode

```bash
# Run with verbose output
pytest -v -s tests/test_specific_module.py

# Run with debugger
pytest --pdb tests/test_specific_module.py
```

### Test Isolation

```bash
# Run specific test
pytest tests/test_specific_module.py::test_specific_function

# Run with specific marker
pytest -m "integration"
```

### Test Database Issues

```bash
# Reset test database
docker compose exec db psql -U aquila_user -d aquila_db -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
docker compose exec backend alembic upgrade head
```

## Best Practices

### Test Organization

1. **One Test Per File**: Keep tests focused and isolated
2. **Descriptive Names**: Use clear, descriptive test names
3. **Arrange-Act-Assert**: Structure tests clearly
4. **Independent Tests**: Tests should not depend on each other
5. **Fast Tests**: Keep tests fast for quick feedback

### Test Maintenance

1. **Update Tests**: Keep tests updated with code changes
2. **Remove Dead Tests**: Delete tests for removed functionality
3. **Refactor Tests**: Improve test quality and maintainability
4. **Document Tests**: Add comments for complex test logic
5. **Review Coverage**: Monitor and improve test coverage

### Test Quality

1. **Edge Cases**: Test boundary conditions and edge cases
2. **Error Handling**: Test error conditions and exceptions
3. **Performance**: Consider test execution time
4. **Reliability**: Ensure tests are stable and repeatable
5. **Comprehensive**: Cover happy paths and error paths

## Troubleshooting

### Common Issues

**Tests Failing with Database Errors**:
- Verify database is running: `docker compose ps db`
- Check database connection string
- Ensure migrations are applied: `alembic upgrade head`

**Tests Timing Out**:
- Check for slow database queries
- Verify external service availability
- Increase test timeout if needed

**Import Errors**:
- Verify virtual environment is activated
- Check package dependencies are installed
- Ensure PYTHONPATH includes project directory

**Fixture Not Found**:
- Verify conftest.py exists in tests directory
- Check fixture is properly defined
- Ensure pytest can discover fixtures

## Summary

| Area | Runner | Needs DB |
|------|--------|----------|
| `test_alembic_version_column`, `test_capability_registry`, `test_ai_providers`, `test_ai_routes`, `test_agent_tools`, `test_gmail_client`, `test_gmail_routes` | `pytest` | No |
| `test_gmail_silence_sender`, `test_chat_threads_list`, `test_agent_trace_channel` | `pytest` | Yes (skips if unreachable) |
| Frontend | `npm run lint` | No |

## Conclusion

The Agent Aquila testing framework provides comprehensive coverage of backend functionality with a focus on reliability, maintainability, and speed. By following the guidelines and best practices in this document, you can ensure that your code changes are properly tested and validated before deployment.

Regular testing helps catch bugs early, ensures code quality, and provides confidence in the stability and reliability of the Agent Aquila system.
