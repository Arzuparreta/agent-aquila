"""Agent tool handlers - exports."""

from . import (
    gmail, calendar, drive, sheets_docs, tasks, people,
    social, third_party, icloud, memory, skills, proposal,
    scheduled, misc, loop_core,
)

# Re-export all handler functions
from .gmail import _tool_gmail_list_messages
from .gmail import _tool_gmail_get_message
from .gmail import _tool_gmail_get_thread
from .gmail import _tool_gmail_list_labels
from .gmail import _tool_gmail_list_filters
from .gmail import _tool_gmail_modify_message
from .gmail import _tool_gmail_modify_thread
from .gmail import _tool_gmail_trash_message
from .gmail import _tool_gmail_untrash_message
from .gmail import _tool_gmail_trash_thread
from .gmail import _tool_gmail_untrash_thread
from .gmail import _tool_gmail_trash_bulk_query
from .gmail import _tool_gmail_mark_read
from .gmail import _tool_gmail_mark_unread
from .gmail import _tool_gmail_silence_sender
from .gmail import _tool_gmail_create_filter
from .gmail import _tool_gmail_delete_filter
from .calendar import _tool_calendar_list_calendars
from .calendar import _tool_calendar_list_events
from .calendar import _tool_calendar_create_event
from .calendar import _tool_calendar_update_event
from .calendar import _tool_calendar_delete_event
from .drive import _tool_drive_list_files
from .drive import _tool_drive_upload_file
from .sheets_docs import _tool_sheets_read_range
from .sheets_docs import _tool_docs_get_document
from .tasks import _tool_tasks_list_tasklists
from .tasks import _tool_tasks_list_tasks
from .tasks import _tool_tasks_create_task
from .tasks import _tool_tasks_update_task
from .tasks import _tool_tasks_delete_task
from .people import _tool_people_search_contacts
from .social import _tool_slack_list_conversations
from .social import _tool_slack_get_conversation_history
from .social import _tool_telegram_get_me
from .social import _tool_telegram_get_updates
from .social import _tool_telegram_send_message
from .social import _tool_outlook_list_messages
from .social import _tool_outlook_get_message
from .third_party import _tool_github_list_my_repos
from .third_party import _tool_github_list_repo_issues
from .third_party import _tool_linear_list_issues
from .third_party import _tool_linear_get_issue
from .third_party import _tool_notion_search
from .third_party import _tool_notion_get_page
from .memory import _tool_upsert_memory
from .memory import _tool_delete_memory
from .memory import _tool_list_memory
from .memory import _tool_recall_memory
from .memory import _tool_memory_get
from .skills import _tool_list_skills
from .skills import _tool_load_skill
from .skills import _tool_list_workspace_files
from .skills import _tool_read_workspace_file
from .proposal import _tool_propose_email_send
from .proposal import _tool_propose_email_reply
from .proposal import _tool_propose_whatsapp_send
from .proposal import _tool_propose_slack_post_message
from .proposal import _tool_propose_linear_create_comment
from .proposal import _tool_propose_telegram_send_message
from .scheduled import _tool_scheduled_task_create
from .scheduled import _tool_scheduled_task_list
from .scheduled import _tool_scheduled_task_update
from .scheduled import _tool_scheduled_task_delete
from .misc import _scheduled_task_to_dict
from .misc import _tool_device_list_ingested_files
from .misc import _tool_device_get_ingested_file
from .misc import _tool_list_connectors
from .misc import _tool_get_session_time
from .misc import _tool_web_search
from .misc import _tool_web_fetch
from .misc import _tool_start_connector_setup
from .misc import _tool_submit_connector_credentials
from .misc import _tool_start_oauth_flow
from .misc import _idem
from .loop_core import _parse_label_ids
from .loop_core import _insert_proposal
from .loop_core import _dispatch_tool
from .loop_core import run_agent_invalid_preflight
from .loop_core import abort_pending_run_queue_unavailable
from .loop_core import create_pending_agent_run
from .loop_core import run_agent
from .loop_core import _execute_agent_loop
from .loop_core import _load_steps
from .loop_core import _to_read
from .loop_core import list_recent_runs
from .loop_core import list_trace_events
from .loop_core import get_run

AGENT_TOOL_NAMES = [
  "_tool_gmail_list_messages",
  "_tool_gmail_get_message",
  "_tool_gmail_get_thread",
  "_tool_gmail_list_labels",
  "_tool_gmail_list_filters",
  "_tool_gmail_modify_message",
  "_tool_gmail_modify_thread",
  "_tool_gmail_trash_message",
  "_tool_gmail_untrash_message",
  "_tool_gmail_trash_thread",
  "_tool_gmail_untrash_thread",
  "_tool_gmail_trash_bulk_query",
  "_tool_gmail_mark_read",
  "_tool_gmail_mark_unread",
  "_tool_gmail_silence_sender",
  "_tool_gmail_create_filter",
  "_tool_gmail_delete_filter",
  "_tool_calendar_list_calendars",
  "_tool_calendar_list_events",
  "_tool_calendar_create_event",
  "_tool_calendar_update_event",
  "_tool_calendar_delete_event",
  "_tool_drive_list_files",
  "_tool_drive_upload_file",
  "_tool_sheets_read_range",
  "_tool_docs_get_document",
  "_tool_tasks_list_tasklists",
  "_tool_tasks_list_tasks",
  "_tool_tasks_create_task",
  "_tool_tasks_update_task",
  "_tool_tasks_delete_task",
  "_tool_people_search_contacts",
  "_tool_slack_list_conversations",
  "_tool_slack_get_conversation_history",
  "_tool_telegram_get_me",
  "_tool_telegram_get_updates",
  "_tool_telegram_send_message",
  "_tool_outlook_list_messages",
  "_tool_outlook_get_message",
  "_tool_github_list_my_repos",
  "_tool_github_list_repo_issues",
  "_tool_linear_list_issues",
  "_tool_linear_get_issue",
  "_tool_notion_search",
  "_tool_notion_get_page",
  "_tool_upsert_memory",
  "_tool_delete_memory",
  "_tool_list_memory",
  "_tool_recall_memory",
  "_tool_memory_get",
  "_tool_list_skills",
  "_tool_load_skill",
  "_tool_list_workspace_files",
  "_tool_read_workspace_file",
  "_tool_propose_email_send",
  "_tool_propose_email_reply",
  "_tool_propose_whatsapp_send",
  "_tool_propose_slack_post_message",
  "_tool_propose_linear_create_comment",
  "_tool_propose_telegram_send_message",
  "_tool_scheduled_task_create",
  "_tool_scheduled_task_list",
  "_tool_scheduled_task_update",
  "_tool_scheduled_task_delete",
  "_scheduled_task_to_dict",
  "_tool_device_list_ingested_files",
  "_tool_device_get_ingested_file",
  "_tool_list_connectors",
  "_tool_get_session_time",
  "_tool_web_search",
  "_tool_web_fetch",
  "_tool_start_connector_setup",
  "_tool_submit_connector_credentials",
  "_tool_start_oauth_flow",
  "_idem",
  "_parse_label_ids",
  "_insert_proposal",
  "_dispatch_tool",
  "run_agent_invalid_preflight",
  "abort_pending_run_queue_unavailable",
  "create_pending_agent_run",
  "run_agent",
  "_execute_agent_loop",
  "_load_steps",
  "_to_read",
  "list_recent_runs",
  "list_trace_events",
  "get_run"
]

AGENT_TOOLS = []  # Will be populated at runtime
AGENT_TOOL_DISPATCH = {}  # Will be populated at runtime
