"""Agent tool dispatch — maps tool names to handler functions."""

from __future__ import annotations

from .handlers.gmail import (
    _tool_gmail_list_messages, _tool_gmail_get_message, _tool_gmail_get_thread,
    _tool_gmail_list_labels, _tool_gmail_list_filters,
    _tool_gmail_modify_message, _tool_gmail_modify_thread,
    _tool_gmail_trash_message, _tool_gmail_untrash_message,
    _tool_gmail_trash_thread, _tool_gmail_untrash_thread,
    _tool_gmail_trash_bulk_query, _tool_gmail_mark_read, _tool_gmail_mark_unread,
    _tool_gmail_silence_sender, _tool_gmail_create_filter, _tool_gmail_delete_filter,
)
from .handlers.calendar import (
    _tool_calendar_list_calendars, _tool_calendar_list_events,
    _tool_calendar_create_event, _tool_calendar_update_event,
    _tool_calendar_delete_event,
)
from .handlers.drive import _tool_drive_list_files, _tool_drive_upload_file
from .handlers.sheets_docs import _tool_sheets_read_range, _tool_docs_get_document
from .handlers.tasks import (
    _tool_tasks_list_tasklists, _tool_tasks_list_tasks,
    _tool_tasks_create_task, _tool_tasks_update_task, _tool_tasks_delete_task,
)
from .handlers.people import _tool_people_search_contacts
from .handlers.social import (
    _tool_slack_list_conversations, _tool_slack_get_conversation_history,
    _tool_telegram_get_me, _tool_telegram_get_updates, _tool_telegram_send_message,
    _tool_outlook_list_messages, _tool_outlook_get_message,
)
from .handlers.third_party import (
    _tool_github_list_my_repos, _tool_github_list_repo_issues,
    _tool_linear_list_issues, _tool_linear_get_issue,
    _tool_notion_search, _tool_notion_get_page,
)
from .handlers.memory import (
    _tool_upsert_memory, _tool_delete_memory, _tool_list_memory,
    _tool_recall_memory, _tool_memory_get,
)
from .handlers.skills import (
    _tool_list_skills, _tool_load_skill,
    _tool_list_workspace_files, _tool_read_workspace_file,
)
from .handlers.proposal import (
    _tool_propose_email_send, _tool_propose_email_reply,
    _tool_propose_whatsapp_send, _tool_propose_slack_post_message,
    _tool_propose_linear_create_comment, _tool_propose_telegram_send_message,
)
from .handlers.scheduled_tasks import (
    _tool_scheduled_task_create, _tool_scheduled_task_list,
    _tool_scheduled_task_update, _tool_scheduled_task_delete,
)
from .handlers.misc import (
    _tool_device_list_ingested_files, _tool_device_get_ingested_file,
    _tool_list_connectors, _tool_get_session_time,
    _tool_web_search, _tool_web_fetch,
    _tool_start_connector_setup, _tool_submit_connector_credentials,
    _tool_start_oauth_flow,
)


# Tool name → (handler_function, takes_run_id)
# takes_run_id=True only for proposal tools that need the current AgentRun ID.
TOOL_DISPATCH: dict[str, tuple[object, bool]] = {
    "gmail_list_messages": (_tool_gmail_list_messages, False),
    "gmail_get_message": (_tool_gmail_get_message, False),
    "gmail_get_thread": (_tool_gmail_get_thread, False),
    "gmail_list_labels": (_tool_gmail_list_labels, False),
    "gmail_list_filters": (_tool_gmail_list_filters, False),
    "gmail_modify_message": (_tool_gmail_modify_message, False),
    "gmail_modify_thread": (_tool_gmail_modify_thread, False),
    "gmail_trash_message": (_tool_gmail_trash_message, False),
    "gmail_untrash_message": (_tool_gmail_untrash_message, False),
    "gmail_trash_thread": (_tool_gmail_trash_thread, False),
    "gmail_untrash_thread": (_tool_gmail_untrash_thread, False),
    "gmail_trash_bulk_query": (_tool_gmail_trash_bulk_query, False),
    "gmail_mark_read": (_tool_gmail_mark_read, False),
    "gmail_mark_unread": (_tool_gmail_mark_unread, False),
    "gmail_silence_sender": (_tool_gmail_silence_sender, False),
    "gmail_create_filter": (_tool_gmail_create_filter, False),
    "gmail_delete_filter": (_tool_gmail_delete_filter, False),
    "calendar_list_calendars": (_tool_calendar_list_calendars, False),
    "calendar_list_events": (_tool_calendar_list_events, False),
    "calendar_create_event": (_tool_calendar_create_event, False),
    "calendar_update_event": (_tool_calendar_update_event, False),
    "calendar_delete_event": (_tool_calendar_delete_event, False),
    "drive_list_files": (_tool_drive_list_files, False),
    "drive_upload_file": (_tool_drive_upload_file, False),
    "sheets_read_range": (_tool_sheets_read_range, False),
    "docs_get_document": (_tool_docs_get_document, False),
    "tasks_list_tasklists": (_tool_tasks_list_tasklists, False),
    "tasks_list_tasks": (_tool_tasks_list_tasks, False),
    "tasks_create_task": (_tool_tasks_create_task, False),
    "tasks_update_task": (_tool_tasks_update_task, False),
    "tasks_delete_task": (_tool_tasks_delete_task, False),
    "people_search_contacts": (_tool_people_search_contacts, False),
    "outlook_list_messages": (_tool_outlook_list_messages, False),
    "outlook_get_message": (_tool_outlook_get_message, False),
    "github_list_my_repos": (_tool_github_list_my_repos, False),
    "github_list_repo_issues": (_tool_github_list_repo_issues, False),
    "slack_list_conversations": (_tool_slack_list_conversations, False),
    "slack_get_conversation_history": (_tool_slack_get_conversation_history, False),
    "linear_list_issues": (_tool_linear_list_issues, False),
    "linear_get_issue": (_tool_linear_get_issue, False),
    "notion_search": (_tool_notion_search, False),
    "notion_get_page": (_tool_notion_get_page, False),
    "telegram_get_me": (_tool_telegram_get_me, False),
    "telegram_get_updates": (_tool_telegram_get_updates, False),
    "telegram_send_message": (_tool_telegram_send_message, False),
    "upsert_memory": (_tool_upsert_memory, False),
    "delete_memory": (_tool_delete_memory, False),
    "list_memory": (_tool_list_memory, False),
    "recall_memory": (_tool_recall_memory, False),
    "memory_get": (_tool_memory_get, False),
    "list_skills": (_tool_list_skills, False),
    "load_skill": (_tool_load_skill, False),
    "list_workspace_files": (_tool_list_workspace_files, False),
    "read_workspace_file": (_tool_read_workspace_file, False),
    "device_list_ingested_files": (_tool_device_list_ingested_files, False),
    "device_get_ingested_file": (_tool_device_get_ingested_file, False),
    "list_connectors": (_tool_list_connectors, False),
    "get_session_time": (_tool_get_session_time, False),
    "web_search": (_tool_web_search, False),
    "web_fetch": (_tool_web_fetch, False),
    "start_connector_setup": (_tool_start_connector_setup, False),
    "submit_connector_credentials": (_tool_submit_connector_credentials, False),
    "start_oauth_flow": (_tool_start_oauth_flow, False),
    "scheduled_task_create": (_tool_scheduled_task_create, False),
    "scheduled_task_list": (_tool_scheduled_task_list, False),
    "scheduled_task_update": (_tool_scheduled_task_update, False),
    "scheduled_task_delete": (_tool_scheduled_task_delete, False),
    # Proposal tools take run_id
    "propose_email_send": (_tool_propose_email_send, True),
    "propose_email_reply": (_tool_propose_email_reply, True),
    "propose_whatsapp_send": (_tool_propose_whatsapp_send, True),
    "propose_slack_post_message": (_tool_propose_slack_post_message, True),
    "propose_linear_create_comment": (_tool_propose_linear_create_comment, True),
    "propose_telegram_send_message": (_tool_propose_telegram_send_message, True),
}


TOOL_NAMES: frozenset[str] = frozenset(TOOL_DISPATCH.keys())
