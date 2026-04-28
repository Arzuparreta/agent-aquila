"""OpenAI-format tool definitions for the agent (native or prompted harness).

The palette is large and opinionated, filtered per user by connector links and by **turn profile**
(see ``tools_for_palette_mode``, ``AgentService.resolve_turn_tool_palette``, and
``connector_tool_registry.required_providers_for_tool``):

- **Live read tools** for every connector (Gmail / unified ``calendar_*`` for
  Google Calendar, Microsoft Graph, and iCloud CalDAV / Drive /
  YouTube / Tasks / People / Outlook mail / Teams). Nothing reads
  from a local mirror because none
  exists — every call goes straight to the upstream API.
- **Live write tools** for everything *except* outbound email/Teams
  sends and high-risk outbound (email, WhatsApp text, YouTube upload). Label / trash / mute / filter / calendar / drive uploads run
  immediately because the user explicitly opted into ``send_only_gated``
  approval policy for those channels.
- **Proposal tools** for operations that require
  a human nod: ``propose_email_send``, ``propose_email_reply``, ``propose_whatsapp_send``, ``propose_youtube_upload``, ``propose_slack_post_message``.
  These create a ``PendingProposal`` row that the user approves from
  the chat UI before it actually goes out.
- **Memory tools** (``upsert_memory`` / ``recall_memory`` / ``memory_search`` /
  ``memory_get`` / ``delete_memory`` / ``list_memory``) — backed by ``agent_memory``.
- **Skills tools** (``list_skills`` / ``load_skill``) — read markdown
  recipe files from ``backend/skills/``.
- **Connector setup tools** (``start_connector_setup`` /
  ``submit_connector_credentials`` / ``start_oauth_flow``) — kept
  because new users still need to onboard their accounts.
- **Terminator** (``final_answer``) — every turn ends in this so we
  can use ``tool_choice="required"`` on the model and structurally
  forbid free-form text leaks.

Native tool/function calling is dramatically more reliable than asking
the model to author a custom JSON envelope freehand. The structured
choice is biased into the decoder, so the model can't "go off-script"
by inventing a phase name, omitting required fields, or returning a
vague natural-language reply when it should be calling a tool.

This module is the single source of truth for the **schemas** presented to
the model. Which providers unlock which tools is defined in
``connector_tool_registry``. Handlers live in ``AgentService._dispatch_tool``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.connector_tool_registry import required_providers_for_tool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fn(
    name: str,
    description: str,
    properties: dict[str, dict[str, Any]] | None = None,
    required: list[str] | None = None,
    palette_modes: set[str] | None = None,
) -> dict[str, Any]:
    """Build one OpenAI-format function tool definition.
    
    Args:
        palette_modes: Set of palette modes this tool belongs to.
                        If None, defaults to {"full"} (excluded from compact).
                        Add "compact" to include in compact palette.
    """
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties or {},
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    tool: dict[str, Any] = {
        "type": "function",
        "function": {
            "name": name,
            "description": description.strip(),
            "parameters": schema,
        },
    }
    # Store palette_modes at top level (not in "function" to avoid API issues)
    if palette_modes:
        tool["_palette_modes"] = frozenset(palette_modes)
    return tool


_IDEMPOTENCY = {
    "idempotency_key": {
        "type": "string",
        "maxLength": 128,
        "description": (
            "Optional client-side dedup key. Re-sending the same key returns the existing "
            "pending operation instead of creating a duplicate."
        ),
    }
}

# Almost every connector tool accepts an optional ``connection_id``;
# when omitted the dispatcher falls back to the user's single connection
# of the right provider type.
_CONNECTION_ID = {
    "connection_id": {
        "type": "integer",
        "description": (
            "Optional. The numeric id of the connector connection. When the user has "
            "exactly one connection of the right kind it is auto-detected; pass "
            "explicitly only for users with multiple accounts."
        ),
    }
}


# ---------------------------------------------------------------------------
# Live READ tools (no local mirror — everything fetches from the provider)
# ---------------------------------------------------------------------------

_READ_ONLY_TOOLS: list[dict[str, Any]] = [
    _fn(
        "gmail_list_messages",
        "Use whenever you need to look at the user's Gmail inbox — for triage, "
        "to find a recent message, or to count unread items. Calls the live "
        "Gmail API; there is no local mirror. "
        "Use the powerful Gmail ``q`` syntax (e.g. ``is:unread``, "
        "``from:bob@example.com``, ``newer_than:7d``, ``has:attachment``) — "
        "the same operators that work in the Gmail web search bar. "
        "Returns: a page of message ids + thread ids + snippets. Call "
        "``gmail_get_message`` on any id to read the body.",
        {
            **_CONNECTION_ID,
            "q": {
                "type": "string",
                "description": "Gmail search query, e.g. 'is:unread in:inbox newer_than:7d'.",
            },
            "label_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional Gmail label ids to filter by (e.g. ['INBOX']).",
            },
            "page_token": {"type": "string"},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 100},
        },
    ),
    _fn(
        "gmail_get_message",
        "Use to read the full payload of a specific Gmail message you already "
        "located via ``gmail_list_messages`` (or that the user pasted into "
        "chat). Returns headers, snippet, and the body. "
        "Inputs: ``message_id`` (required), optional ``connection_id``, "
        "optional ``format`` (``full`` returns the full body, ``metadata`` "
        "skips the body — use metadata for cheap fan-out during triage).",
        {
            **_CONNECTION_ID,
            "message_id": {"type": "string"},
            "format": {"type": "string", "enum": ["full", "metadata", "minimal", "raw"]},
        },
        required=["message_id"],
    ),
    _fn(
        "gmail_get_thread",
        "Use when you need the full back-and-forth of a Gmail thread (every "
        "message, oldest first). Cheaper than calling ``gmail_get_message`` "
        "for each message id. "
        "Inputs: ``thread_id`` (required), optional ``connection_id``, "
        "optional ``format`` (``full`` or ``metadata``).",
        {
            **_CONNECTION_ID,
            "thread_id": {"type": "string"},
            "format": {"type": "string", "enum": ["full", "metadata", "minimal"]},
        },
        required=["thread_id"],
    ),
    _fn(
        "gmail_list_labels",
        "Use to list every Gmail label (system + user-created) — needed when "
        "you want to add/remove a label by name (look up the id first) or to "
        "show the user what labels exist. "
        "Inputs: optional ``connection_id``.",
        {**_CONNECTION_ID},
    ),
    _fn(
        "gmail_list_filters",
        "Use to list the user's existing Gmail server-side filters. Helpful "
        "before creating a new filter to avoid duplicates, or to confirm a "
        "previous silencing action stuck. Requires the "
        "``gmail.settings.basic`` scope. "
        "Inputs: optional ``connection_id``.",
        {**_CONNECTION_ID},
    ),
    _fn(
        "calendar_list_events",
        "Use whenever the user asks about their calendar — what's scheduled "
        "this week, conflicts, free slots. Works with **Google Calendar**, **Microsoft 365 / Outlook "
        "(Graph)**, or **iCloud (CalDAV)** depending on which calendar connection is linked (see "
        "``list_connectors`` / ``calendar_list_calendars``). "
        "Google: ordered by start from ``time_min`` (default now UTC). "
        "iCloud: pass ``calendar_url`` from ``calendar_list_calendars`` when not using the default "
        "calendar; window uses ``time_min`` / ``time_max`` as RFC3339 dates (same as Google). "
        "Microsoft Graph: uses ``time_min`` / ``time_max`` as ISO bounds on ``/me/calendarView``. "
        "Inputs: optional ``connection_id``, ``calendar_id`` (Google calendar id, default "
        "``primary``), ``calendar_url`` (iCloud CalDAV URL), ``time_min`` / ``time_max``, "
        "``page_token`` (Google only), ``max_results`` (1-250).",
        {
            **_CONNECTION_ID,
            "calendar_id": {"type": "string"},
            "calendar_url": {
                "type": "string",
                "description": "iCloud only: CalDAV calendar URL from calendar_list_calendars.",
            },
            "time_min": {
                "type": "string",
                "description": "RFC3339 lower bound; omit to use current time (upcoming events).",
            },
            "time_max": {"type": "string", "description": "RFC3339 upper bound (optional)."},
            "page_token": {"type": "string"},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 250},
        },
    ),
    _fn(
        "calendar_list_calendars",
        "List calendars available on the user's linked **calendar** connection (Google Calendar "
        "list, iCloud CalDAV calendars, or Microsoft Graph calendars). "
        "Call before ``calendar_list_events`` when you need ``calendar_url`` (iCloud) or a "
        "non-default Google ``calendar_id``. Optional ``connection_id``, ``page_token`` / "
        "``max_results`` where the upstream supports paging.",
        {
            **_CONNECTION_ID,
            "page_token": {"type": "string"},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 250},
        },
    ),
    _fn(
        "drive_list_files",
        "Use when the user asks 'what files do I have' or to find a Drive "
        "file by name/keyword. Calls Google Drive live; supports the Drive "
        "``q`` syntax (e.g. ``name contains 'rider'``, ``mimeType='application/pdf'``). "
        "Inputs: optional ``connection_id``, ``q`` (Drive query), "
        "``page_token``, ``page_size`` (1-200).",
        {
            **_CONNECTION_ID,
            "q": {"type": "string", "description": "Drive search query."},
            "page_token": {"type": "string"},
            "page_size": {"type": "integer", "minimum": 1, "maximum": 200},
        },
    ),
    _fn(
        "sheets_read_range",
        "Read a range from a Google Sheet (A1 notation, e.g. ``Sheet1!A1:D10``). "
        "Requires a **google_sheets** connection. "
        "Inputs: ``spreadsheet_id`` (required), ``range`` (required), optional ``connection_id``.",
        {
            **_CONNECTION_ID,
            "spreadsheet_id": {"type": "string", "description": "Spreadsheet id from the URL or Drive."},
            "range": {"type": "string", "description": "A1 range including sheet name if needed."},
        },
        required=["spreadsheet_id", "range"],
    ),
    _fn(
        "docs_get_document",
        "Read a Google Doc as structured plain text plus raw API payload. "
        "Requires a **google_docs** connection. "
        "Inputs: ``document_id`` (required), optional ``connection_id``.",
        {
            **_CONNECTION_ID,
            "document_id": {"type": "string", "description": "Document id from the Docs URL."},
        },
        required=["document_id"],
    ),
    _fn(
        "tasks_list_tasklists",
        "List Google Task lists for the user. Optional ``connection_id``, ``page_token``.",
        {**_CONNECTION_ID, "page_token": {"type": "string"}},
    ),
    _fn(
        "tasks_list_tasks",
        "List tasks in a Google Task list. ``tasklist_id`` required. "
        "Optional ``show_completed``, ``due_min`` / ``due_max`` (RFC3339), "
        "``page_token``, ``max_results``, ``connection_id``.",
        {
            **_CONNECTION_ID,
            "tasklist_id": {"type": "string"},
            "show_completed": {"type": "boolean"},
            "due_min": {"type": "string"},
            "due_max": {"type": "string"},
            "page_token": {"type": "string"},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 100},
        },
        required=["tasklist_id"],
    ),
    _fn(
        "people_search_contacts",
        "Search Google Contacts (People API, read-only). "
        "Use to resolve names to email or phone hints. ``query`` required. "
        "Optional ``page_token``, ``page_size`` (1-30), ``connection_id``.",
        {
            **_CONNECTION_ID,
            "query": {"type": "string"},
            "page_token": {"type": "string"},
            "page_size": {"type": "integer", "minimum": 1, "maximum": 30},
        },
        required=["query"],
    ),
    _fn(
        "github_list_my_repos",
        "List GitHub repositories for the linked PAT (sorted by last update). "
        "Optional ``page``, ``per_page`` (1-100), ``connection_id``.",
        {
            **_CONNECTION_ID,
            "page": {"type": "integer", "minimum": 1},
            "per_page": {"type": "integer", "minimum": 1, "maximum": 100},
        },
    ),
    _fn(
        "github_list_repo_issues",
        "List issues for ``owner`` / ``repo`` (pass owner and name only, e.g. ``octocat`` + ``Hello-World``). "
        "``state`` is ``open`` (default), ``closed``, or ``all``. "
        "Optional ``page``, ``per_page``, ``connection_id``.",
        {
            **_CONNECTION_ID,
            "owner": {"type": "string"},
            "repo": {"type": "string"},
            "state": {"type": "string", "enum": ["open", "closed", "all"]},
            "page": {"type": "integer", "minimum": 1},
            "per_page": {"type": "integer", "minimum": 1, "maximum": 100},
        },
        required=["owner", "repo"],
    ),
    _fn(
        "slack_list_conversations",
        "List Slack channels the bot can see (public + private by default). "
        "Requires a **slack_bot** connection. "
        "Optional ``connection_id``, ``types`` (Slack `types` string, default "
        "``public_channel,private_channel``), ``cursor``, ``limit`` (1-1000).",
        {
            **_CONNECTION_ID,
            "types": {"type": "string"},
            "cursor": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
        },
    ),
    _fn(
        "slack_get_conversation_history",
        "Fetch recent messages from a Slack channel. ``channel_id`` is the `C...` id from "
        "``slack_list_conversations``. Optional ``connection_id``, ``limit`` (1-200), ``cursor``.",
        {
            **_CONNECTION_ID,
            "channel_id": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 200},
            "cursor": {"type": "string"},
        },
        required=["channel_id"],
    ),
    _fn(
        "linear_list_issues",
        "List recent **Linear** issues (GraphQL). Requires **linear** API key connection. "
        "Optional ``first`` (1-100, default 25), ``connection_id``.",
        {
            **_CONNECTION_ID,
            "first": {"type": "integer", "minimum": 1, "maximum": 100},
        },
    ),
    _fn(
        "linear_get_issue",
        "Fetch one **Linear** issue by id (UUID). ``issue_id`` required. Optional ``connection_id``.",
        {**_CONNECTION_ID, "issue_id": {"type": "string"}},
        required=["issue_id"],
    ),
    _fn(
        "notion_search",
        "Search **Notion** pages/databases (POST /search). Requires **notion** integration token. "
        "``query`` optional (empty returns recent). ``page_size`` 1-100. Optional ``connection_id``.",
        {
            **_CONNECTION_ID,
            "query": {"type": "string"},
            "page_size": {"type": "integer", "minimum": 1, "maximum": 100},
        },
    ),
    _fn(
        "notion_get_page",
        "Get a **Notion** page by id (from ``notion_search`` or a shared link id). "
        "``page_id`` required. Optional ``connection_id``.",
        {**_CONNECTION_ID, "page_id": {"type": "string"}},
        required=["page_id"],
    ),
    _fn(
        "telegram_get_me",
        "Call Telegram **getMe** for the linked bot. Requires **telegram_bot**. Optional ``connection_id``.",
        {**_CONNECTION_ID},
    ),
    _fn(
        "telegram_get_updates",
        "Telegram **getUpdates** (polling-style snapshot of recent activity). "
        "Optional ``offset``, ``limit`` (1-100), ``connection_id``.",
        {
            **_CONNECTION_ID,
            "offset": {"type": "integer"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100},
        },
    ),
    _fn(
        "device_list_ingested_files",
        "List files previously uploaded via the **device bridge** (e.g. iOS Shortcuts → "
        "``POST /api/v1/device-files/ingest``). Newest first. No cloud connector. "
        "Optional ``limit`` (1-200, default 50).",
        {"limit": {"type": "integer", "minimum": 1, "maximum": 200}},
    ),
    _fn(
        "device_get_ingested_file",
        "Fetch one ingested file by **ingest_id** (from ``device_list_ingested_files``). "
        "Returns ``content_base64`` for small files; large files return metadata and a short note. "
        "``ingest_id`` required.",
        {"ingest_id": {"type": "integer", "minimum": 1}},
        required=["ingest_id"],
    ),
    _fn(
        "outlook_list_messages",
        "Use to read the user's Outlook (Microsoft 365) mail. Calls Graph "
        "live. Same role as ``gmail_list_messages`` for Outlook accounts. "
        "Inputs: optional ``connection_id``, ``top`` (1-100).",
        {**_CONNECTION_ID, "top": {"type": "integer", "minimum": 1, "maximum": 100}},
    ),
    _fn(
        "outlook_get_message",
        "Use to read the full body of a specific Outlook message located via "
        "``outlook_list_messages``. "
        "Inputs: ``message_id`` (required), optional ``connection_id``.",
        {**_CONNECTION_ID, "message_id": {"type": "string"}},
        required=["message_id"],
    ),
    _fn(
        "list_connectors",
        "Use when the user asks what is connected, or when you need to know "
        "which connector ids are available before calling another tool. "
        "Returns one row per ConnectorConnection with id, provider, label, "
        "and ``needs_reauth`` (true when the granted scopes no longer cover "
        "what the agent needs).",
    ),
    _fn(
        "get_session_time",
        "Return the server's current date and time in the user's configured "
        "time zone (same values as the system prompt's clock block). Use when "
        "you need a fresh timestamp during a long turn or after ambiguity.",
    ),
    _fn(
        "web_search",
        "Search the public internet for current information (news, docs, release notes, pricing, "
        "status pages, etc.). Use this when the answer is likely outside the user's connected "
        "accounts and may be newer than the model's training data. "
        "Inputs: ``query`` (required), optional ``max_results`` (1-20).",
        {
            "query": {"type": "string", "description": "Search query in natural language."},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 20},
        },
        required=["query"],
    ),
    _fn(
        "web_fetch",
        "Fetch and extract readable text from a public URL (http/https only). "
        "Use after ``web_search`` when you need to read the source page content "
        "before answering. Inputs: ``url`` (required), optional ``max_chars``.",
        {
            "url": {"type": "string", "description": "Public http/https URL."},
            "max_chars": {"type": "integer", "minimum": 500, "maximum": 100000},
        },
        required=["url"],
    ),
]


# ---------------------------------------------------------------------------
# Live WRITE tools — auto-apply (NO proposal). The user opted into
# ``send_only_gated``: only outbound email goes through approval.
# ---------------------------------------------------------------------------

_AUTO_APPLY_TOOLS: list[dict[str, Any]] = [
    # ---- Gmail mutations ------------------------------------------------
    _fn(
        "gmail_modify_message",
        "Use to add or remove labels on a single Gmail message — e.g. star "
        "(``STARRED``), mark important (``IMPORTANT``), archive "
        "(remove ``INBOX``). Auto-applies. "
        "Inputs: ``message_id`` (required), optional ``connection_id``, "
        "``add_label_ids`` (array), ``remove_label_ids`` (array).",
        {
            **_CONNECTION_ID,
            "message_id": {"type": "string"},
            "add_label_ids": {"type": "array", "items": {"type": "string"}},
            "remove_label_ids": {"type": "array", "items": {"type": "string"}},
        },
        required=["message_id"],
    ),
    _fn(
        "gmail_modify_thread",
        "Same as ``gmail_modify_message`` but applies to every message in a "
        "thread — typical for archiving a conversation or sending a whole "
        "thread to spam. Auto-applies. "
        "Inputs: ``thread_id`` (required), optional ``connection_id``, "
        "``add_label_ids`` (array), ``remove_label_ids`` (array).",
        {
            **_CONNECTION_ID,
            "thread_id": {"type": "string"},
            "add_label_ids": {"type": "array", "items": {"type": "string"}},
            "remove_label_ids": {"type": "array", "items": {"type": "string"}},
        },
        required=["thread_id"],
    ),
    _fn(
        "gmail_trash_message",
        "Move a single Gmail message to Trash. Reversible via "
        "``gmail_untrash_message``. Auto-applies. "
        "Inputs: ``message_id`` (required), optional ``connection_id``.",
        {**_CONNECTION_ID, "message_id": {"type": "string"}},
        required=["message_id"],
    ),
    _fn(
        "gmail_untrash_message",
        "Restore a trashed Gmail message. Auto-applies. "
        "Inputs: ``message_id`` (required), optional ``connection_id``.",
        {**_CONNECTION_ID, "message_id": {"type": "string"}},
        required=["message_id"],
    ),
    _fn(
        "gmail_trash_thread",
        "Move an entire Gmail thread to Trash. Auto-applies. "
        "Inputs: ``thread_id`` (required), optional ``connection_id``.",
        {**_CONNECTION_ID, "thread_id": {"type": "string"}},
        required=["thread_id"],
    ),
    _fn(
        "gmail_untrash_thread",
        "Restore a trashed Gmail thread. Auto-applies. "
        "Inputs: ``thread_id`` (required), optional ``connection_id``.",
        {**_CONNECTION_ID, "thread_id": {"type": "string"}},
        required=["thread_id"],
    ),
    _fn(
        "gmail_trash_bulk_query",
        "Trash **many** Gmail messages matching a search query using efficient "
        "batch API calls (up to 1000 messages per request). Use when the user "
        "wants to clear their inbox or delete everything matching a Gmail "
        "search — **much** faster than ``gmail_trash_message`` in a loop. "
        "Defaults to ``q='in:inbox'``. Hard cap ``max_messages`` (default 50000, "
        "max 250000). Auto-applies. "
        "Inputs: optional ``q``, ``connection_id``, ``max_messages``.",
        {
            **_CONNECTION_ID,
            "q": {"type": "string"},
            "max_messages": {"type": "integer", "minimum": 1, "maximum": 250000},
        },
    ),
    _fn(
        "gmail_mark_read",
        "Convenience: remove the ``UNREAD`` label from a message OR thread. "
        "Auto-applies. Pass either ``message_id`` or ``thread_id``.",
        {
            **_CONNECTION_ID,
            "message_id": {"type": "string"},
            "thread_id": {"type": "string"},
        },
    ),
    _fn(
        "gmail_mark_unread",
        "Convenience: add the ``UNREAD`` label to a message OR thread. "
        "Auto-applies.",
        {
            **_CONNECTION_ID,
            "message_id": {"type": "string"},
            "thread_id": {"type": "string"},
        },
    ),
    _fn(
        "gmail_silence_sender",
        "Silence a sender: creates a Gmail filter so future mail skips the inbox "
        "and is marked read. "
        "``mode='spam'``: Gmail **cannot** put SPAM on filter actions — pass "
        "``thread_id`` or ``message_id`` to move **that** mail to Spam via "
        "modify; future mail still only gets the inbox-skipping filter. "
        "Auto-applies. "
        "Inputs: ``email`` (required), ``mode`` (``mute`` default, ``spam``), "
        "optional ``thread_id`` / ``message_id`` (for spam on existing mail), "
        "``connection_id``.",
        {
            **_CONNECTION_ID,
            "email": {"type": "string"},
            "mode": {"type": "string", "enum": ["mute", "spam"]},
            "thread_id": {"type": "string"},
            "message_id": {"type": "string"},
        },
        required=["email"],
    ),
    _fn(
        "gmail_create_filter",
        "Low-level: create an arbitrary server-side Gmail filter. Auto-applies. "
        "Use ``gmail_silence_sender`` for the common 'mute / spam this "
        "sender' workflow; reach for this tool for richer rules (subject "
        "match, has-attachment, etc.). Requires the ``gmail.settings.basic`` "
        "scope. "
        "Do **not** put ``SPAM`` in ``action.addLabelIds`` — Gmail returns "
        "400; use ``gmail_modify_*`` to move mail to Spam. "
        "Inputs: ``criteria`` (Gmail filter criteria object — keys like "
        "``from``, ``to``, ``subject``, ``query``, ``hasAttachment``), "
        "``action`` (object with ``addLabelIds`` / ``removeLabelIds`` / "
        "``forward``), optional ``connection_id``.",
        {
            **_CONNECTION_ID,
            "criteria": {"type": "object"},
            "action": {"type": "object"},
        },
        required=["criteria", "action"],
    ),
    _fn(
        "gmail_delete_filter",
        "Remove an existing Gmail filter by id (look it up via "
        "``gmail_list_filters``). Auto-applies.",
        {**_CONNECTION_ID, "filter_id": {"type": "string"}},
        required=["filter_id"],
    ),
    # ---- Calendar mutations --------------------------------------------
    _fn(
        "calendar_create_event",
        "Create a new calendar event. Auto-applies for **Google Calendar**, **Microsoft Graph**, "
        "or **iCloud CalDAV** (same ``calendar_*`` tools — the host picks the API from the linked "
        "connection). "
        "Google / Microsoft: ``summary``, ``start_iso``, ``end_iso`` (RFC3339 wall time in "
        "``timezone``), optional ``description``, ``timezone`` (IANA; defaults from user "
        "settings). "
        "iCloud: same time fields; add ``calendar_url`` from ``calendar_list_calendars`` when not "
        "using the default calendar. "
        "Optional ``connection_id``.",
        {
            **_CONNECTION_ID,
            "calendar_url": {"type": "string"},
            "summary": {"type": "string", "maxLength": 500},
            "start_iso": {"type": "string"},
            "end_iso": {"type": "string"},
            "description": {"type": "string"},
            "timezone": {"type": "string"},
            **_IDEMPOTENCY,
        },
        required=["summary", "start_iso", "end_iso"],
    ),
    _fn(
        "calendar_update_event",
        "Update an existing calendar event (Google or Microsoft Graph). Auto-applies. "
        "Not supported for iCloud CalDAV in this deployment — returns a clear error. "
        "Inputs: ``event_id`` (required) plus any of ``summary`` / "
        "``description`` / ``start_iso`` / ``end_iso`` / ``timezone`` (same "
        "rules as ``calendar_create_event``).",
        {
            **_CONNECTION_ID,
            "event_id": {"type": "string"},
            "summary": {"type": "string"},
            "description": {"type": "string"},
            "start_iso": {"type": "string"},
            "end_iso": {"type": "string"},
            "timezone": {"type": "string"},
        },
        required=["event_id"],
    ),
    _fn(
        "calendar_delete_event",
        "Delete (cancel) a calendar event by provider id (Google or Microsoft Graph). "
        "Not supported for iCloud CalDAV in this deployment. "
        "Auto-applies. Inputs: ``event_id`` (required), optional "
        "``connection_id``.",
        {**_CONNECTION_ID, "event_id": {"type": "string"}},
        required=["event_id"],
    ),
    # ---- Drive mutations -----------------------------------------------
    _fn(
        "drive_upload_file",
        "Upload a small text/binary file to the user's Google Drive. "
        "Auto-applies. For binary content base64-encode it. "
        "Inputs: ``path`` (required, target filename), ``mime_type`` "
        "(required), and EITHER ``content_text`` (UTF-8) OR "
        "``content_base64`` (binary), optional ``connection_id``.",
        {
            **_CONNECTION_ID,
            "path": {"type": "string", "maxLength": 1024},
            "mime_type": {"type": "string"},
            "content_text": {"type": "string"},
            "content_base64": {"type": "string"},
        },
        required=["path", "mime_type"],
    ),
    _fn(
        "tasks_create_task",
        "Create a task in a Google Task list. ``tasklist_id`` and ``title`` required. "
        "Optional ``notes``, ``due`` (RFC3339), ``connection_id``.",
        {
            **_CONNECTION_ID,
            "tasklist_id": {"type": "string"},
            "title": {"type": "string"},
            "notes": {"type": "string"},
            "due": {"type": "string"},
        },
        required=["tasklist_id", "title"],
    ),
    _fn(
        "tasks_update_task",
        "Patch a Google Task. ``tasklist_id``, ``task_id`` required. "
        "Optional ``title``, ``notes``, ``status`` (needsAction/completed), ``due``, "
        "``connection_id``.",
        {
            **_CONNECTION_ID,
            "tasklist_id": {"type": "string"},
            "task_id": {"type": "string"},
            "title": {"type": "string"},
            "notes": {"type": "string"},
            "status": {"type": "string", "enum": ["needsAction", "completed"]},
            "due": {"type": "string"},
        },
        required=["tasklist_id", "task_id"],
    ),
    _fn(
        "tasks_delete_task",
        "Delete a task from a Google Task list. ``tasklist_id`` and ``task_id`` required.",
        {
            **_CONNECTION_ID,
            "tasklist_id": {"type": "string"},
            "task_id": {"type": "string"},
        },
        required=["tasklist_id", "task_id"],
    ),
    _fn(
        "telegram_send_message",
        "Send a Telegram message to a **chat_id** immediately (no approval needed). "
        "Use for scheduled summaries, alerts, or any proactive notification the user expects. "
        "``chat_id`` may be numeric id (e.g. 8671136588) or @channelusername for public channels. "
        "``text`` is the message body (max 4096 chars). Optional ``connection_id`` for "
        "users with multiple Telegram bots.",
        {
            **_CONNECTION_ID,
            "chat_id": {
                "anyOf": [{"type": "string"}, {"type": "integer"}],
                "description": "Telegram chat_id (numeric) or @channelusername.",
            },
            "text": {"type": "string", "maxLength": 4096},
        },
        required=["chat_id", "text"],
    ),
    _fn(
        "upsert_memory",
        "Save (or update) a small note in the agent's persistent memory — "
        "the primary way to persist facts across sessions (OpenClaw-style). "
        "Use for stable preferences, recurring tasks, or anything the user "
        "asked you to remember. Avoid ``memory.durable.*`` for ephemeral "
        "tool diagnostics (e.g. one empty mail search) unless the user asked "
        "to remember; avoid ``prefs.*`` for generic procedures they never "
        "stated. If unsure about a user-specific fact, save it anyway. "
        "**When the user assigns or changes your "
        "display name** (including bilingual names), call this in the same "
        "turn before ``final_answer`` with keys such as "
        "``agent.identity.display_name_es`` / ``agent.identity.display_name_en``. "
        "Auto-applies. "
        "Inputs: ``key`` (required, short snake_case slug), ``content`` "
        "(required, free-form text — keep it under a few sentences), "
            "optional ``importance`` (0 default; higher values pin closer to the top of "
        "the system prompt warmup; use 8–10 for identity the user asked to remember), "
        "optional ``tags`` (array of short labels for grouping).",
        {
            "key": {"type": "string", "maxLength": 200},
            "content": {"type": "string"},
            "importance": {"type": "integer", "minimum": 0, "maximum": 10},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        required=["key", "content"],
    ),
    _fn(
        "delete_memory",
        "Delete a persistent memory entry by key. Use when the user "
        "explicitly retracts something ('forget what I said about X'). "
        "Auto-applies.",
        {"key": {"type": "string"}},
        required=["key"],
    ),
    _fn(
        "list_memory",
        "Return every persistent memory entry for the current user, "
        "sorted by importance then recency. Useful for an end-of-turn "
        "audit ('what does the agent remember about me?').",
        {"limit": {"type": "integer", "minimum": 1, "maximum": 200}},
    ),
    _fn(
        "recall_memory",
        "Search persistent memory by semantic similarity (or recency when "
        "no query is given). Use early in a turn to surface relevant "
        "prior notes — preferences, deadlines, ongoing threads. "
        "Inputs: optional ``query`` (free text), optional ``tags`` (array "
        "for filtering), optional ``limit`` (default 6).",
        {
            "query": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
        },
    ),
    _fn(
        "memory_get",
        "Fetch one memory row by exact ``key`` (full ``content``, no truncation). "
        "Use before editing or to inspect ``memory.durable.*``, "
        "``memory.daily.*``, or ``user.profile.*`` keys. Input: ``key`` (required).",
        {"key": {"type": "string", "maxLength": 200}},
        required=["key"],
    ),
    # ---- Skills ---------------------------------------------------------
    _fn(
        "list_skills",
        "List every skill (markdown recipe) shipped under ``backend/skills/``. "
        "Each skill is a focused workflow the agent can adopt — call "
        "``load_skill`` to read the full body before following it.",
    ),
    _fn(
        "load_skill",
        "Read the full markdown body of a single skill by slug. Use "
        "before executing the workflow it describes. "
        "Inputs: ``slug`` (required, e.g. 'gmail-triage').",
        {"slug": {"type": "string"}},
        required=["slug"],
    ),
    # ---- Connector setup helpers ---------------------------------------
    _fn(
        "start_connector_setup",
        "Use when the user asks to connect a new account — e.g. 'connect "
        "my Gmail', 'vincúlame Outlook', WhatsApp Business, iCloud calendar, or GitHub. "
        "Renders the in-chat setup card so "
        "the user can paste OAuth client credentials, Meta/Apple secrets, or a GitHub PAT. "
        "Inputs: ``provider`` (``google``, ``microsoft``, ``whatsapp``, ``icloud_caldav``, ``github``).",
        {
            "provider": {
                "type": "string",
                "enum": ["google", "microsoft", "whatsapp", "icloud_caldav", "github"],
            }
        },
        required=["provider"],
    ),
    _fn(
        "submit_connector_credentials",
        "Use after the user types their OAuth client_id / client_secret "
        "into the setup card. Persists the credentials and prepares OAuth.",
        {
            "setup_token": {"type": "string"},
            "client_id": {"type": "string"},
            "client_secret": {"type": "string"},
            "redirect_uri": {"type": "string"},
            "tenant": {"type": "string"},
        },
        required=["setup_token", "client_id", "client_secret"],
    ),
    _fn(
        "start_oauth_flow",
        "Return the OAuth consent URL for a configured provider/service. "
        "Inputs: ``provider`` (google / microsoft), ``service`` (gmail / "
        "calendar / drive / youtube / tasks / people / outlook / teams / all).",
        {
            "provider": {"type": "string", "enum": ["google", "microsoft"]},
            "service": {
                "type": "string",
                "enum": [
                    "gmail",
                    "calendar",
                    "drive",
                    "youtube",
                    "tasks",
                    "people",
                    "outlook",
                    "teams",
                    "all",
                ],
            },
        },
        required=["provider", "service"],
    ),
]


# ---------------------------------------------------------------------------
# Approval-required (proposal) tools — outbound email / WhatsApp / YouTube upload.
# ---------------------------------------------------------------------------

_PROPOSAL_TOOLS: list[dict[str, Any]] = [
    _fn(
        "propose_email_send",
        "Use when the user asks you to send a brand-new email (not a reply "
        "to an existing thread). Drafts the message and queues an approval "
        "card; nothing is sent until the user taps Approve in chat. "
        "Works for Gmail and Outlook — pick the right ``connection_id``. "
        "Inputs: ``connection_id`` (required), ``to`` (required, string or "
        "array), ``subject`` (required), ``body`` (required), optional "
        "``content_type`` (``text`` or ``html``).",
        {
            "connection_id": {"type": "integer"},
            "to": {
                "anyOf": [
                    {"type": "string"},
                    {"type": "array", "items": {"type": "string"}},
                ]
            },
            "subject": {"type": "string", "maxLength": 998},
            "body": {"type": "string"},
            "content_type": {"type": "string", "enum": ["text", "html"]},
            **_IDEMPOTENCY,
        },
        required=["connection_id", "to", "subject", "body"],
    ),
    _fn(
        "propose_email_reply",
        "Use when the user asks you to reply to a SPECIFIC email/thread you "
        "already located (via ``gmail_get_thread`` / ``outlook_get_message``). "
        "Drafts the reply and queues an approval card; preserves headers so "
        "the reply lands in the right conversation. "
        "Inputs: ``connection_id`` (required), ``thread_id`` (required), "
        "``body`` (required), optional ``in_reply_to``, ``to``, ``subject``, "
        "``content_type``.",
        {
            "connection_id": {"type": "integer"},
            "thread_id": {"type": "string"},
            "in_reply_to": {"type": "string"},
            "to": {
                "anyOf": [
                    {"type": "string"},
                    {"type": "array", "items": {"type": "string"}},
                ]
            },
            "subject": {"type": "string"},
            "body": {"type": "string"},
            "content_type": {"type": "string", "enum": ["text", "html"]},
            **_IDEMPOTENCY,
        },
        required=["connection_id", "thread_id", "body"],
    ),
    _fn(
        "propose_whatsapp_send",
        "Queue an outbound WhatsApp **Business** message (Meta Cloud API). Creates an "
        "approval card; nothing is sent until the user approves. "
        "Aligns with [Meta's policies](https://developers.facebook.com/docs/whatsapp/overview): "
        "recipients should have opted in to your business; free-form ``body`` is for the "
        "customer care **24h window** after they messaged you; **cold outreach** outside that "
        "window typically needs pre-approved **template** messages (``template_name`` + "
        "``template_language``). For contacts like 'my mother' resolve a phone with "
        "``people_search_contacts`` or explicit digits — never guess numbers. "
        "``to_e164`` is E.164 (e.g. +34600111222). "
        "Inputs: ``connection_id``, ``to_e164``, "
        "``body`` (session text) **or** ``template_name`` + optional ``template_language``.",
        {
            "connection_id": {"type": "integer"},
            "to_e164": {"type": "string"},
            "body": {"type": "string"},
            "template_name": {"type": "string"},
            "template_language": {"type": "string"},
            **_IDEMPOTENCY,
        },
        required=["connection_id", "to_e164"],
    ),
    _fn(
        "propose_slack_post_message",
        "Queue a Slack **chat.postMessage** in a channel. Creates an approval card; "
        "nothing is posted until the user approves. "
        "``channel_id`` is the `C...` id from ``slack_list_conversations``. "
        "Inputs: ``connection_id``, ``channel_id``, ``text`` (mrkdwn/plain), optional ``thread_ts``.",
        {
            "connection_id": {"type": "integer"},
            "channel_id": {"type": "string"},
            "text": {"type": "string", "maxLength": 4000},
            "thread_ts": {"type": "string"},
            **_IDEMPOTENCY,
        },
        required=["connection_id", "channel_id", "text"],
    ),
    _fn(
        "propose_linear_create_comment",
        "Queue a **Linear** comment on an issue. Approval required before post. "
        "``issue_id`` is the Linear issue UUID; ``body`` is comment markdown/text.",
        {
            "connection_id": {"type": "integer"},
            "issue_id": {"type": "string"},
            "body": {"type": "string", "maxLength": 20000},
            **_IDEMPOTENCY,
        },
        required=["connection_id", "issue_id", "body"],
    ),
    _fn(
        "propose_telegram_send_message",
        "Queue **sendMessage** to a Telegram ``chat_id``. Requires approval. "
        "``chat_id`` may be numeric id or @channelusername for public channels. "
        "``text`` is the outgoing body (max 4096).",
        {
            "connection_id": {"type": "integer"},
            "chat_id": {
                "anyOf": [{"type": "string"}, {"type": "integer"}],
            },
            "text": {"type": "string", "maxLength": 4096},
            **_IDEMPOTENCY,
        },
        required=["connection_id", "chat_id", "text"],
    ),
    _fn(
        "list_workspace_files",
        "List markdown files available in the agent workspace (persona/rules) and "
        "the skills folder. Use when the user asks what files they can edit or "
        "how behaviour is configured.",
        {},
    ),
    _fn(
        "read_workspace_file",
        "Read one markdown file from the workspace or skills root. "
        "Pass only the basename (e.g. `SOUL.md`, `AGENTS.md`).",
        {
            "path": {
                "type": "string",
                "description": "Filename ending in .md (no directories or ..).",
            }
        },
        required=["path"],
    ),
    _fn(
        "scheduled_task_create",
        "Create a user-defined scheduled task. Use for both recurring automation "
        "(like every every night check iCloud photos) AND one-time reminders "
        "(like remind me at 7pm to pick up groceries). For one-time tasks, use "
        "schedule_type=once with scheduled_at (ISO 8601 datetime). CRITICAL: when the user says "
        "at 22:50 or at 7pm and they have a timezone set in Settings, interpret that time in THEIR local timezone "
        "(check the clock block in the system prompt for the user's configured timezone). The user means their local time, NOT UTC. "
        "Inputs: name (required), instruction (required), schedule_type (once/interval/daily/cron/rrule), "
        "for once use scheduled_at (ISO 8601 datetime string); for interval use interval_minutes; "
        "for daily use hour_local, minute_local, optional timezone and weekdays (0=Mon..6=Sun); "
        "for cron use cron_expr; for rrule use rrule_expr. One-time tasks auto-disable after execution.",
        {
            "name": {"type": "string"},
            "instruction": {"type": "string"},
            "schedule_type": {"type": "string", "enum": ["once", "interval", "daily", "cron", "rrule"]},
            "scheduled_at": {"type": "string", "description": "ISO 8601 datetime for once type (interpret in user's local timezone)"},
            "interval_minutes": {"type": "integer", "minimum": 1, "maximum": 10080},
            "hour_local": {"type": "integer", "minimum": 0, "maximum": 23},
            "minute_local": {"type": "integer", "minimum": 0, "maximum": 59},
            "cron_expr": {"type": "string"},
            "rrule_expr": {"type": "string"},
            "timezone": {"type": "string"},
            "weekdays": {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 6}},
            "enabled": {"type": "boolean"},
        },
        required=["name", "instruction", "schedule_type"],
    ),
    _fn(
        "scheduled_task_list",
        "List the user's scheduled tasks. Use before updates/deletes, and to confirm "
        "what automations are active. Optional input: ``enabled_only``.",
        {
            "enabled_only": {"type": "boolean"},
        },
    ),
    _fn(
        "scheduled_task_update",
        "Update an existing scheduled task (name, instruction, enabled, or schedule). "
        "Pass ``task_id`` and only the fields that need changing.",
        {
            "task_id": {"type": "integer"},
            "name": {"type": "string"},
            "instruction": {"type": "string"},
            "schedule_type": {"type": "string", "enum": ["once", "interval", "daily", "cron", "rrule"]},
            "scheduled_at": {"type": "string", "description": "ISO 8601 datetime for once type"},
            "interval_minutes": {"type": "integer", "minimum": 1, "maximum": 10080},
            "hour_local": {"type": "integer", "minimum": 0, "maximum": 23},
            "minute_local": {"type": "integer", "minimum": 0, "maximum": 59},
            "cron_expr": {"type": "string"},
            "rrule_expr": {"type": "string"},
            "timezone": {"type": "string"},
            "weekdays": {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 6}},
            "enabled": {"type": "boolean"},
        },
        required=["task_id"],
    ),
    _fn(
        "scheduled_task_delete",
        "Delete a scheduled task permanently. Use when the user asks to remove/stop a recurring task.",
        {
            "task_id": {"type": "integer"},
        },
        required=["task_id"],
    ),
]


# ---------------------------------------------------------------------------
# Terminator tool — every turn MUST end in a tool call. When the model is
# done gathering data (or never needed to in the first place), it calls
# ``final_answer`` with the user-facing reply. We pair this with
# ``tool_choice="required"`` to structurally prevent the "model emits a
# free-form text answer instead of calling the tool I asked it to call"
# class of failures we kept seeing with small local models on Ollama.
# ---------------------------------------------------------------------------

FINAL_ANSWER_TOOL_NAME = "final_answer"

_TERMINATOR_TOOLS: list[dict[str, Any]] = [
    _fn(
        FINAL_ANSWER_TOOL_NAME,
        "Use to deliver the FINAL natural-language reply to the user. This "
        "is the terminator — calling it ends the turn. Call it EXACTLY "
        "ONCE per assistant message that contains tool calls, AFTER any "
        "non-terminator tools you need (e.g. ``upsert_memory`` to save a "
        "name or preference — emit those tool calls **first**, then "
        "``final_answer`` **last** in the same assistant message when possible). "
        "If the API only allows one tool per step, call ``upsert_memory`` in "
        "one step and ``final_answer`` in the next. "
        "Do NOT call this on turn 1 for a factual question about the "
        "user's data — first call the appropriate data tool to ground the "
        "answer, then call this with a summary that cites the result. "
        "Inputs: ``text`` (required, the reply shown verbatim to the user, "
        "in the same language they used — default Spanish, conversational, "
        "concise), optional ``citations`` (array of bare ids referenced "
        "in the reply, e.g. ``[\"gmail:msg_xyz\"]``).",
        {
            "text": {
                "type": "string",
                "description": (
                    "The reply shown verbatim to the user, in the same language "
                    "they used (default Spanish). Be concise and conversational."
                ),
            },
            "citations": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional list of bare ids referenced in the reply, e.g. "
                    "[\"gmail:msg_xyz\", \"drive:file_abc\"]."
                ),
            },
        },
        required=["text"],
    ),
]


AGENT_TOOLS: list[dict[str, Any]] = [
    *_READ_ONLY_TOOLS,
    *_AUTO_APPLY_TOOLS,
    *_PROPOSAL_TOOLS,
    *_INTROSPECTION_TOOLS,
    *_TERMINATOR_TOOLS,
]


AGENT_TOOL_NAMES: frozenset[str] = frozenset(t["function"]["name"] for t in AGENT_TOOLS)

# Tools that should be in compact palette - source of truth is here
_COMPACT_PALETTE_TOOLS = frozenset({
    "final_answer",
    "get_session_time",
    "list_skills",
    "load_skill",
    "list_memory",
    "recall_memory",
    "memory_get",
    "upsert_memory",
    "delete_memory",
    "gmail_list_messages",
    "gmail_get_message",
    "gmail_get_thread",
    "calendar_list_events",
    "calendar_list_calendars",
    "start_connector_setup",
    "start_oauth_flow",
    "submit_connector_credentials",
    "list_connectors",
    "list_workspace_files",
    "read_workspace_file",
    "web_search",
    "web_fetch",
    "telegram_send_message",
    "scheduled_task_create",
    "scheduled_task_list",
    "scheduled_task_update",
    "scheduled_task_delete",
})

# Add palette_modes metadata to tools
for _tool in AGENT_TOOLS:
    _name = _tool.get("function", {}).get("name")
    if _name in _COMPACT_PALETTE_TOOLS:
        _tool["_palette_modes"] = frozenset({"full", "compact"})


def tools_for_palette_mode(mode: str) -> list[dict[str, Any]]:
    """Return the tool list for ``full`` (default) or ``compact`` (fewer tools, lower token use).
    
    The source of truth for palette membership is each tool's ``_palette_modes`` metadata.
    Tools without ``_palette_modes`` default to ``{"full"}`` (excluded from compact).
    """
    m = (mode or "full").strip().lower()
    if m == "compact":
        # Return tools that self-declare "compact" in their _palette_modes
        return [
            t for t in AGENT_TOOLS
            if "compact" in (t.get("_palette_modes") or frozenset())
        ]
    return list(AGENT_TOOLS)


