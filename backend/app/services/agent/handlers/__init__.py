"""Agent tool handlers — clean exports from domain modules."""

from .base import provider_connection, provider_connection_multi, UPSTREAM_ERRORS, _parse_label_ids

from .gmail import (
    _tool_gmail_list_messages,
    _tool_gmail_get_message,
    _tool_gmail_get_thread,
    _tool_gmail_list_labels,
    _tool_gmail_list_filters,
    _tool_gmail_modify_message,
    _tool_gmail_modify_thread,
    _tool_gmail_trash_message,
    _tool_gmail_untrash_message,
    _tool_gmail_trash_thread,
    _tool_gmail_untrash_thread,
    _tool_gmail_trash_bulk_query,
    _tool_gmail_mark_read,
    _tool_gmail_mark_unread,
    _tool_gmail_silence_sender,
    _tool_gmail_create_filter,
    _tool_gmail_delete_filter,
)

from .calendar import (
    _tool_calendar_list_calendars,
    _tool_calendar_list_events,
    _tool_calendar_create_event,
    _tool_calendar_update_event,
    _tool_calendar_delete_event,
)

from .drive import (
    _tool_drive_list_files,
    _tool_drive_upload_file,
)

from .sheets_docs import (
    _tool_sheets_read_range,
    _tool_docs_get_document,
)

from .tasks import (
    _tool_tasks_list_tasklists,
    _tool_tasks_list_tasks,
    _tool_tasks_create_task,
    _tool_tasks_update_task,
    _tool_tasks_delete_task,
)

from .people import _tool_people_search_contacts

from .social import (
    _tool_slack_list_conversations,
    _tool_slack_get_conversation_history,
    _tool_telegram_get_me,
    _tool_telegram_get_updates,
    _tool_telegram_send_message,
    _tool_outlook_list_messages,
    _tool_outlook_get_message,
)

from .third_party import (
    _tool_github_list_my_repos,
    _tool_github_list_repo_issues,
    _tool_linear_list_issues,
    _tool_linear_get_issue,
    _tool_notion_search,
    _tool_notion_get_page,
)

from .memory import (
    _tool_upsert_memory,
    _tool_delete_memory,
    _tool_list_memory,
    _tool_recall_memory,
    _tool_memory_get,
)

from .skills import (
    _tool_list_skills,
    _tool_load_skill,
    _tool_list_workspace_files,
    _tool_read_workspace_file,
)

from .proposal import (
    _tool_propose_email_send,
    _tool_propose_email_reply,
    _tool_propose_whatsapp_send,
    _tool_propose_slack_post_message,
    _tool_propose_linear_create_comment,
    _tool_propose_telegram_send_message,
    _insert_proposal,
    _idem,
)

from .scheduled_tasks import (
    _tool_scheduled_task_create,
    _tool_scheduled_task_list,
    _tool_scheduled_task_update,
    _tool_scheduled_task_delete,
    _scheduled_task_to_dict,
)

from .misc import (
    _tool_device_list_ingested_files,
    _tool_device_get_ingested_file,
    _tool_list_connectors,
    _tool_get_session_time,
    _tool_web_search,
    _tool_web_fetch,
    _tool_start_connector_setup,
    _tool_submit_connector_credentials,
    _tool_start_oauth_flow,
)

# Import loop functions from the existing loop module
from .loop import (
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
