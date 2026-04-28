"""Agent package - refactored from agent_service.py.

Core agent functionality split into focused modules:
- `connection.py` — connection resolution and client factories
- `handlers/` — tool handlers by domain  
- `dispatch.py` — tool dispatch table
"""

from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_run import AgentRun, AgentRunStep
from app.models.chat_message import ChatMessage
from app.models.pending_proposal import PendingProposal
from app.models.scheduled_task import ScheduledTask
from app.models.user import User
from app.schemas.agent import (
    AgentRunAttentionRead, AgentRunRead, AgentRunSummaryRead,
    AgentStepRead, AgentTraceEventRead, PendingProposalRead,
)

# Re-export everything from submodules
from .connection import (
    _resolve_connection, _gmail_client, _calendar_client,
    _drive_client, _youtube_client, _tasks_client, _people_client,
    _sheets_client, _docs_client, _icloud_app_password_creds,
    _icloud_caldav_client, _parse_rfc3339_to_utc_datetime,
    _default_icloud_calendar_url, _graph_client, _github_client,
    _slack_api_client, _linear_client, _notion_client,
    _telegram_client, _discord_client,
    CALENDAR_TOOL_PROVIDERS, DISCORD_TOOL_PROVIDERS,
    DOCS_TOOL_PROVIDERS, DRIVE_TOOL_PROVIDERS,
    GITHUB_TOOL_PROVIDERS, GMAIL_TOOL_PROVIDERS,
    GRAPH_CALENDAR_TOOL_PROVIDERS, ICLOUD_TOOL_PROVIDERS,
    LINEAR_TOOL_PROVIDERS, NOTION_TOOL_PROVIDERS,
    OUTLOOK_MAIL_TOOL_PROVIDERS, PEOPLE_TOOL_PROVIDERS,
    SHEETS_TOOL_PROVIDERS, SLACK_TOOL_PROVIDERS,
    TASKS_TOOL_PROVIDERS, TEAMS_TOOL_PROVIDERS,
    TELEGRAM_TOOL_PROVIDERS, YOUTUBE_TOOL_PROVIDERS,
)

from .handlers import (
    AGENT_TOOL_DISPATCH, AGENT_TOOL_NAMES, AGENT_TOOLS,
    FINAL_ANSWER_TOOL_NAME, filter_tools_for_user_connectors,
    tools_for_palette_mode,
)

# Re-export all handlers for backwards compatibility
from .handlers import _tool_gmail_list_messages
from .handlers import _tool_gmail_get_message
from .handlers import _tool_gmail_get_thread
from .handlers import _tool_gmail_list_labels
from .handlers import _tool_gmail_list_filters
from .handlers import _tool_gmail_modify_message
from .handlers import _tool_gmail_modify_thread
from .handlers import _tool_gmail_trash_message
from .handlers import _tool_gmail_untrash_message
from .handlers import _tool_gmail_trash_thread
from .handlers import _tool_gmail_untrash_thread
from .handlers import _tool_gmail_trash_bulk_query
from .handlers import _tool_gmail_mark_read
from .handlers import _tool_gmail_mark_unread
from .handlers import _tool_gmail_silence_sender
from .handlers import _tool_gmail_create_filter
from .handlers import _tool_gmail_delete_filter
from .handlers import _tool_calendar_list_calendars
from .handlers import _tool_calendar_list_events
from .handlers import _tool_calendar_create_event
from .handlers import _tool_calendar_update_event
from .handlers import _tool_calendar_delete_event
from .handlers import _tool_drive_list_files
from .handlers import _tool_drive_upload_file
from .handlers import _tool_sheets_read_range
from .handlers import _tool_docs_get_document
from .handlers import _tool_tasks_list_tasklists
from .handlers import _tool_tasks_list_tasks
from .handlers import _tool_tasks_create_task
from .handlers import _tool_tasks_update_task
from .handlers import _tool_tasks_delete_task
from .handlers import _tool_people_search_contacts
from .handlers import _tool_slack_list_conversations
from .handlers import _tool_slack_get_conversation_history
from .handlers import _tool_telegram_get_me
from .handlers import _tool_telegram_get_updates
from .handlers import _tool_telegram_send_message
from .handlers import _tool_outlook_list_messages
from .handlers import _tool_outlook_get_message
from .handlers import _tool_github_list_my_repos
from .handlers import _tool_github_list_repo_issues
from .handlers import _tool_linear_list_issues
from .handlers import _tool_linear_get_issue
from .handlers import _tool_notion_search
from .handlers import _tool_notion_get_page
from .handlers import _tool_upsert_memory
from .handlers import _tool_delete_memory
from .handlers import _tool_list_memory
from .handlers import _tool_recall_memory
from .handlers import _tool_memory_get
from .handlers import _tool_list_skills
from .handlers import _tool_load_skill
from .handlers import _tool_list_workspace_files
from .handlers import _tool_read_workspace_file
from .handlers import _tool_propose_email_send
from .handlers import _tool_propose_email_reply
from .handlers import _tool_propose_whatsapp_send
from .handlers import _tool_propose_slack_post_message
from .handlers import _tool_propose_linear_create_comment
from .handlers import _tool_propose_telegram_send_message
from .handlers import _tool_scheduled_task_create
from .handlers import _tool_scheduled_task_list
from .handlers import _tool_scheduled_task_update
from .handlers import _tool_scheduled_task_delete
from .handlers import _scheduled_task_to_dict
from .handlers import _tool_device_list_ingested_files
from .handlers import _tool_device_get_ingested_file
from .handlers import _tool_list_connectors
from .handlers import _tool_get_session_time
from .handlers import _tool_web_search
from .handlers import _tool_web_fetch
from .handlers import _tool_start_connector_setup
from .handlers import _tool_submit_connector_credentials
from .handlers import _tool_start_oauth_flow
from .handlers import _idem
from .handlers import _parse_label_ids
from .handlers import _insert_proposal
from .handlers import _dispatch_tool
from .handlers import run_agent_invalid_preflight
from .handlers import abort_pending_run_queue_unavailable
from .handlers import create_pending_agent_run
from .handlers import run_agent
from .handlers import _execute_agent_loop
from .handlers import _load_steps
from .handlers import _to_read
from .handlers import list_recent_runs
from .handlers import list_trace_events
from .handlers import get_run

# Also export loop functions
from .handlers.loop_core import (
    _execute_agent_loop, _dispatch_tool, _insert_proposal, _idem,
    run_agent_invalid_preflight, abort_pending_run_queue_unavailable,
    create_pending_agent_run, run_agent, _load_steps,
    list_recent_runs, list_trace_events, get_run,
)

from .handlers.loop_core import (
    _to_read, _assistant_message_from, _approx_prompt_tokens,
    _conversation_trace_snapshot, _is_context_overflow,
    _reduce_conversation_for_budget, _trim_step_payload_for_client,
)

from .handlers.misc import _parse_label_ids


class AgentService:
    """Thin wrapper for agent functionality."""

    @staticmethod
    async def run_agent_invalid_preflight(db: AsyncSession, user: User) -> Any:
        return await run_agent_invalid_preflight(db, user)

    @staticmethod  
    async def abort_pending_run_queue_unavailable() -> Any:
        return await abort_pending_run_queue_unavailable()

    @staticmethod
    async def create_pending_agent_run(db: AsyncSession, user: User) -> Any:
        return await create_pending_agent_run(db, user)

    @staticmethod
    async def run_agent(
        db: AsyncSession, user: User,
        *, thread_id: int | None = None,
        user_message: str | None = None,
        turn_profile: str | None = None,
        injected_user_context: str | None = None,
        replay_id: int | None = None,
    ) -> Any:
        return await run_agent(
            db, user, thread_id=thread_id, user_message=user_message,
            turn_profile=turn_profile, injected_user_context=injected_user_context,
            replay_id=replay_id,
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

    @staticmethod
    async def _to_read(run: AgentRun, steps: list[AgentStepRead],
                      proposals: list[PendingProposalRead],
                      attention: AgentRunAttentionRead | None = None) -> AgentRunRead:
        return _to_read(run, steps, proposals, attention=attention)
