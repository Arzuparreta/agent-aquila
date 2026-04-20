"""OpenAI-format tool definitions for the OpenClaw-style agent.

After the refactor the agent has a small, opinionated palette:

- **Live read tools** for every connector (Gmail / Calendar / Drive /
  Outlook / Teams). Nothing reads from a local mirror because none
  exists — every call goes straight to the upstream API.
- **Live write tools** for everything *except* outbound email/Teams
  sends. Label / trash / mute / filter / calendar / drive uploads run
  immediately because the user explicitly opted into ``send_only_gated``
  approval policy.
- **Proposal tools** for the two operations that *do* still require
  a human nod: ``propose_email_send`` and ``propose_email_reply``.
  These create a ``PendingProposal`` row that the user approves from
  the chat UI before it actually goes out.
- **Memory tools** (``upsert_memory`` / ``recall_memory`` /
  ``delete_memory`` / ``list_memory``) — backed by ``agent_memory``.
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

This module is the single source of truth for the schemas presented to
the model. The actual handlers live in ``AgentService._dispatch_tool``.
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fn(
    name: str,
    description: str,
    properties: dict[str, dict[str, Any]] | None = None,
    required: list[str] | None = None,
) -> dict[str, Any]:
    """Build one OpenAI-format function tool definition."""
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties or {},
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description.strip(),
            "parameters": schema,
        },
    }


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
        "this week, conflicts, free slots. Calls Google Calendar live. "
        "Inputs: optional ``connection_id``, ``calendar_id`` (defaults to "
        "``primary``), ``page_token``, ``max_results`` (1-250).",
        {
            **_CONNECTION_ID,
            "calendar_id": {"type": "string"},
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
        "teams_list_teams",
        "Use to list the Microsoft Teams the user is a member of. Required "
        "before posting a channel message (you need the ``team_id``). "
        "Inputs: optional ``connection_id``.",
        {**_CONNECTION_ID},
    ),
    _fn(
        "teams_list_channels",
        "Use to list channels in a Microsoft Team. Required before posting "
        "(you need the ``channel_id``). "
        "Inputs: ``team_id`` (required), optional ``connection_id``.",
        {**_CONNECTION_ID, "team_id": {"type": "string"}},
        required=["team_id"],
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
        "High-level helper to silence a sender end-to-end: creates a Gmail "
        "filter that removes ``INBOX`` for future mail from that sender, "
        "and (optionally, when ``mode='spam'``) also marks them as spam. "
        "Auto-applies. "
        "Inputs: ``email`` (required, sender address), ``mode`` "
        "(``mute`` (default) — skip inbox; ``spam`` — also mark as spam), "
        "optional ``connection_id``. "
        "Returns: the filter id + a human summary.",
        {
            **_CONNECTION_ID,
            "email": {"type": "string"},
            "mode": {"type": "string", "enum": ["mute", "spam"]},
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
        "Create a new event on the user's Google Calendar. Auto-applies. "
        "Inputs: ``summary`` (required), ``start_iso`` (required, RFC3339 "
        "datetime), ``end_iso`` (required), optional ``description``, "
        "``timezone`` (defaults to UTC), ``connection_id``.",
        {
            **_CONNECTION_ID,
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
        "Update an existing Google Calendar event. Auto-applies. "
        "Inputs: ``event_id`` (required) plus any of ``summary`` / "
        "``description`` / ``start_iso`` / ``end_iso`` / ``timezone``.",
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
        "Delete (cancel) a Google Calendar event by provider id. "
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
        "drive_share_file",
        "Grant access to an existing Drive file. Auto-applies. "
        "Inputs: ``file_id`` (required, provider id from ``drive_list_files``), "
        "``email`` (required), ``role`` (``reader`` (default) or ``writer``), "
        "optional ``connection_id``.",
        {
            **_CONNECTION_ID,
            "file_id": {"type": "string"},
            "email": {"type": "string"},
            "role": {"type": "string", "enum": ["reader", "writer"]},
        },
        required=["file_id", "email"],
    ),
    # ---- Teams mutations ------------------------------------------------
    _fn(
        "teams_post_message",
        "Post a message to a Microsoft Teams channel. Auto-applies. "
        "Look up ``team_id`` via ``teams_list_teams`` and ``channel_id`` "
        "via ``teams_list_channels`` first. "
        "Inputs: ``team_id`` (required), ``channel_id`` (required), "
        "``body`` (required, plain text or HTML), optional ``connection_id``.",
        {
            **_CONNECTION_ID,
            "team_id": {"type": "string"},
            "channel_id": {"type": "string"},
            "body": {"type": "string"},
        },
        required=["team_id", "channel_id", "body"],
    ),
    # ---- Persistent memory ---------------------------------------------
    _fn(
        "upsert_memory",
        "Save (or update) a small note in the agent's persistent memory. "
        "Use to record stable preferences ('prefers concise replies'), "
        "recurring tasks, or facts the user explicitly asked you to "
        "remember. Auto-applies. "
        "Inputs: ``key`` (required, short snake_case slug), ``content`` "
        "(required, free-form text — keep it under a few sentences), "
        "optional ``importance`` (0 default; 1+ pins it to the top of "
        "the system prompt warmup), optional ``tags`` (array of short "
        "labels for grouping).",
        {
            "key": {"type": "string", "maxLength": 200},
            "content": {"type": "string"},
            "importance": {"type": "integer", "minimum": 0, "maximum": 5},
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
        "my Gmail', 'vincúlame Outlook'. Renders the in-chat setup card so "
        "the user can paste their OAuth client credentials. "
        "Inputs: ``provider`` (``google`` or ``microsoft``).",
        {"provider": {"type": "string", "enum": ["google", "microsoft"]}},
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
        "calendar / drive / outlook / teams).",
        {
            "provider": {"type": "string", "enum": ["google", "microsoft"]},
            "service": {
                "type": "string",
                "enum": ["gmail", "calendar", "drive", "outlook", "teams"],
            },
        },
        required=["provider", "service"],
    ),
]


# ---------------------------------------------------------------------------
# Approval-required (proposal) tools — only outbound EMAIL is gated.
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
        "ONCE, AFTER you have gathered enough information from the other "
        "tools (or you are certain no data tool is needed for a "
        "chitchat-style message). "
        "Do NOT call this on turn 1 for a factual question about the "
        "user's data — first call the appropriate data tool to ground the "
        "answer, then call this with a summary that cites the result. "
        "Do NOT call any other tool in the same response as this one. "
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
    *_TERMINATOR_TOOLS,
]


AGENT_TOOL_NAMES: frozenset[str] = frozenset(t["function"]["name"] for t in AGENT_TOOLS)

# Smaller palette for ``AGENT_TOOL_PALETTE=compact`` — memory, skills, time, Gmail read,
# calendar list, OAuth setup, plus terminator (see ``tools_for_palette_mode``).
_COMPACT_NAMES: frozenset[str] = frozenset(
    {
        "final_answer",
        "get_session_time",
        "list_skills",
        "load_skill",
        "list_memory",
        "recall_memory",
        "upsert_memory",
        "delete_memory",
        "gmail_list_messages",
        "gmail_get_message",
        "gmail_get_thread",
        "calendar_list_events",
        "start_connector_setup",
        "start_oauth_flow",
        "submit_connector_credentials",
        "list_connectors",
    }
)


def tools_for_palette_mode(mode: str) -> list[dict[str, Any]]:
    """Return the tool list for ``full`` (default) or ``compact`` (fewer tools, lower token use)."""
    m = (mode or "full").strip().lower()
    if m == "compact":
        return [t for t in AGENT_TOOLS if t["function"]["name"] in _COMPACT_NAMES]
    return list(AGENT_TOOLS)


# Tool names the agent loop should treat as "fetches more context" rather
# than terminators. Used by the loop to know when to stop iterating.
EXECUTABLE_TOOL_NAMES: frozenset[str] = AGENT_TOOL_NAMES - {FINAL_ANSWER_TOOL_NAME}
