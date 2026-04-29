"""Agent package — refactored from agent_service.py.

Core agent functionality split into focused modules:
- `connection.py` — connection resolution
- `handlers/` — tool handlers by domain (with @provider_connection decorator)
- `dispatch.py` — tool dispatch table mapping tool names to handler functions
- `handlers/base.py` — @provider_connection decorator and provider config
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User

from .connection import _resolve_connection
from .handlers.base import (
    provider_connection,
    provider_connection_multi,
    UPSTREAM_ERRORS,
    _PROVIDER_CONFIG,
    _make_gmail_client,
    _make_calendar_client,
    _make_calendar_client_for_row,
    _make_drive_client,
    _make_sheets_client,
    _make_docs_client,
    _make_tasks_client,
    _make_people_client,
    _make_graph_client,
    _make_github_client,
    _make_linear_client,
    _make_notion_client,
    _make_slack_client,
    _make_telegram_client,
    _make_discord_client,
    _make_icloud_caldav_client,
    _parse_label_ids,
)
from .dispatch import TOOL_DISPATCH, TOOL_NAMES
from app.services.agent_tools import (
    AGENT_TOOLS,
    AGENT_TOOL_NAMES,
    FINAL_ANSWER_TOOL_NAME,
    filter_tools_for_user_connectors,
    tools_for_palette_mode,
)
from .handlers.loop import (
    _dispatch_tool,
    run_agent_invalid_preflight,
    abort_pending_run_queue_unavailable,
    create_pending_agent_run,
    run_agent,
    _execute_agent_loop,
    _load_steps,
    _to_read,
    list_recent_runs,
    list_trace_events,
    get_run,
    _agent_ctx,
    _replay_ctx,
)

AGENT_TOOL_DISPATCH = TOOL_DISPATCH


class AgentService:
    """Thin wrapper for agent functionality — backward compatible entry point."""

    @staticmethod
    async def run_agent_invalid_preflight(db: AsyncSession, user: User, message: str, **kw) -> Any:
        return await run_agent_invalid_preflight(db, user, message, **kw)

    @staticmethod
    async def abort_pending_run_queue_unavailable(db: AsyncSession, **kw) -> Any:
        return await abort_pending_run_queue_unavailable(db=db, **kw)

    @staticmethod
    async def create_pending_agent_run(db: AsyncSession, user: User, **kw) -> Any:
        return await create_pending_agent_run(db, user, **kw)

    @staticmethod
    async def run_agent(
        db: AsyncSession, user: User,
        *,
        thread_id: int | None = None,
        user_message: str | None = None,
        turn_profile: str | None = None,
        injected_user_context: str | None = None,
        replay_id: int | None = None,
        message: str | None = None,
        prior_messages: list[dict[str, str]] | None = None,
        thread_context_hint: str | None = None,
        replay: Any | None = None,
        agent_ctx: dict[str, Any] | None = None,
    ) -> Any:
        msg = user_message or message or ""
        return await run_agent(
            db, user, msg,
            prior_messages=prior_messages,
            thread_id=thread_id,
            thread_context_hint=thread_context_hint,
            replay=replay,
            turn_profile=turn_profile,
            agent_ctx=agent_ctx,
        )

    @staticmethod
    async def _load_steps(db: AsyncSession, run_id: int) -> Any:
        return await _load_steps(db, run_id)

    @staticmethod
    async def list_recent_runs(db: AsyncSession, user: User, *, limit: int = 30) -> Any:
        return await list_recent_runs(db, user, limit=limit)

    @staticmethod
    async def list_trace_events(db: AsyncSession, user: User, run_id: int) -> Any:
        return await list_trace_events(db, user, run_id)

    @staticmethod
    async def get_run(db: AsyncSession, user: User, run_id: int) -> Any:
        return await get_run(db, user, run_id)
