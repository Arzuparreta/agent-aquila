"""OpenAI-format tool definitions for the agent.

Native tool/function calling is dramatically more reliable than asking the model
to author a custom JSON envelope freehand — especially for small local models
(Ollama / Gemma / Qwen / Llama). The structured choice is biased into the
decoder, so the model can't "go off-script" by inventing a phase name, omitting
required fields, or returning a vague natural-language reply when it should be
calling a tool.

This module is the single source of truth for the schemas presented to the
model. The actual handlers still live in ``AgentService`` — see
``AGENT_TOOL_NAMES`` for the contract.
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


# ---------------------------------------------------------------------------
# Read-only tools
# ---------------------------------------------------------------------------

_READ_ONLY_TOOLS: list[dict[str, Any]] = [
    _fn(
        "hybrid_rag_search",
        "Hybrid semantic + keyword search across the artist's CRM (contacts, deals, events, "
        "emails, drive files). Use this to ground factual answers about the artist's data.",
        {
            "query": {"type": "string", "description": "Natural-language query."},
            "limit_per_type": {
                "type": "integer",
                "minimum": 1,
                "maximum": 8,
                "description": "Max hits to return per entity type. Default 5.",
            },
        },
        required=["query"],
    ),
    _fn(
        "get_entity",
        "Fetch a single CRM/Drive entity by id.",
        {
            "entity_type": {
                "type": "string",
                "enum": ["contact", "email", "deal", "event", "drive_file", "attachment"],
            },
            "entity_id": {"type": "integer"},
        },
        required=["entity_type", "entity_id"],
    ),
    _fn(
        "search_emails",
        "Filter the mirrored email index. Returns matching messages newest-first.",
        {
            "query": {"type": "string", "description": "Free-text match against subject/body/sender."},
            "direction": {"type": "string", "enum": ["inbound", "outbound"]},
            "thread_id": {"type": "string", "description": "Provider thread id."},
            "connection_id": {"type": "integer"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 25},
        },
    ),
    _fn(
        "get_thread",
        "Return the full message thread for a provider thread id, oldest-first.",
        {
            "thread_id": {"type": "string"},
            "connection_id": {"type": "integer"},
        },
        required=["thread_id"],
    ),
    _fn(
        "list_calendar_events",
        "List the artist's mirrored calendar events.",
        {
            "start": {"type": "string", "description": "ISO 8601 lower bound."},
            "end": {"type": "string", "description": "ISO 8601 upper bound."},
            "connection_id": {"type": "integer"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
        },
    ),
    _fn(
        "search_drive",
        "Search the artist's mirrored Drive/OneDrive files by name or content text.",
        {
            "query": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 25},
        },
        required=["query"],
    ),
    _fn(
        "list_drive_files",
        "Enumerate the artist's Drive/OneDrive files (most recently modified first). "
        "Use this when the artist asks an open-ended 'what files do I have?' question "
        "with no specific search term.",
        {
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            "connection_id": {"type": "integer"},
            "mime_type": {"type": "string"},
        },
    ),
    _fn(
        "get_drive_file_text",
        "Return extracted plain text for a mirrored Drive file. Triggers on-demand "
        "extraction if not yet cached.",
        {"file_id": {"type": "integer"}},
        required=["file_id"],
    ),
    _fn(
        "list_automations",
        "List the artist's silently-learned automation rules.",
    ),
    _fn(
        "list_connectors",
        "List the artist's Gmail/Outlook/Drive/Teams connector connections and their status.",
    ),
]


# ---------------------------------------------------------------------------
# Auto-apply CRM tools (run instantly with UNDO; no approval card)
# ---------------------------------------------------------------------------

_CONTACT_ROLE_ENUM = ["promoter", "venue", "agent", "manager", "other"]
_DEAL_STATUS_ENUM = ["new", "contacted", "negotiating", "won", "lost"]
_EVENT_STATUS_ENUM = ["confirmed", "tentative", "cancelled"]


def _contact_props(*, include_id: bool) -> dict[str, dict[str, Any]]:
    base: dict[str, dict[str, Any]] = {}
    if include_id:
        base["contact_id"] = {"type": "integer"}
    base.update(
        {
            "name": {"type": "string", "maxLength": 255},
            "email": {"type": "string"},
            "phone": {"type": "string"},
            "role": {"type": "string", "enum": _CONTACT_ROLE_ENUM},
            "notes": {"type": "string"},
            **_IDEMPOTENCY,
        }
    )
    return base


def _deal_props(*, include_id: bool) -> dict[str, dict[str, Any]]:
    base: dict[str, dict[str, Any]] = {}
    if include_id:
        base["deal_id"] = {"type": "integer"}
    else:
        base["contact_id"] = {"type": "integer"}
    base.update(
        {
            "title": {"type": "string", "maxLength": 255},
            "status": {"type": "string", "enum": _DEAL_STATUS_ENUM},
            "amount": {"type": "number"},
            "currency": {"type": "string", "maxLength": 8},
            "notes": {"type": "string"},
            **_IDEMPOTENCY,
        }
    )
    return base


def _event_props(*, include_id: bool) -> dict[str, dict[str, Any]]:
    base: dict[str, dict[str, Any]] = {}
    if include_id:
        base["event_id"] = {"type": "integer"}
    base.update(
        {
            "venue_name": {"type": "string", "maxLength": 255},
            "event_date": {
                "type": "string",
                "description": "ISO date YYYY-MM-DD.",
            },
            "deal_id": {"type": "integer"},
            "city": {"type": "string", "maxLength": 255},
            "status": {"type": "string", "enum": _EVENT_STATUS_ENUM},
            "notes": {"type": "string"},
            **_IDEMPOTENCY,
        }
    )
    return base


_AUTO_APPLY_TOOLS: list[dict[str, Any]] = [
    _fn(
        "apply_create_contact",
        "Create a CRM contact immediately. The artist sees an UNDO option in chat.",
        _contact_props(include_id=False),
        required=["name"],
    ),
    _fn(
        "apply_update_contact",
        "Update an existing CRM contact immediately (UNDO available).",
        _contact_props(include_id=True),
        required=["contact_id"],
    ),
    _fn(
        "apply_create_deal",
        "Create a CRM deal immediately (UNDO available).",
        _deal_props(include_id=False),
        required=["contact_id", "title"],
    ),
    _fn(
        "apply_update_deal",
        "Update an existing CRM deal immediately (UNDO available).",
        _deal_props(include_id=True),
        required=["deal_id"],
    ),
    _fn(
        "apply_create_event",
        "Create a CRM event/show immediately (UNDO available).",
        _event_props(include_id=False),
        required=["venue_name", "event_date"],
    ),
    _fn(
        "apply_update_event",
        "Update an existing CRM event immediately (UNDO available).",
        _event_props(include_id=True),
        required=["event_id"],
    ),
    _fn(
        "create_automation",
        "Silently learn a rule the artist just expressed in plain language "
        "(\"nunca enviar correos a X\", \"siempre CC bookings@...\"). Do NOT ask "
        "permission first; record it and confirm verbally.",
        {
            "name": {"type": "string", "maxLength": 255},
            "trigger": {"type": "string", "enum": ["email_received"]},
            "conditions": {"type": "object"},
            "instruction_natural_language": {"type": "string"},
        },
        required=["instruction_natural_language"],
    ),
    _fn(
        "update_automation",
        "Modify an existing automation rule.",
        {
            "automation_id": {"type": "integer"},
            "name": {"type": "string"},
            "conditions": {"type": "object"},
            "instruction_natural_language": {"type": "string"},
            "enabled": {"type": "boolean"},
        },
        required=["automation_id"],
    ),
    _fn(
        "delete_automation",
        "Delete an automation rule.",
        {"automation_id": {"type": "integer"}},
        required=["automation_id"],
    ),
    _fn(
        "start_connector_setup",
        "Begin the in-chat connector-setup card so the artist can connect Gmail/Outlook/Drive.",
        {"provider": {"type": "string", "enum": ["google", "microsoft"]}},
        required=["provider"],
    ),
    _fn(
        "submit_connector_credentials",
        "Submit the OAuth client credentials the artist just typed in chat.",
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
        "Return a URL the artist taps to grant access for a specific service.",
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
# Approval-required (proposal) tools
# ---------------------------------------------------------------------------

_PROPOSAL_TOOLS: list[dict[str, Any]] = [
    _fn(
        "propose_connector_email_send",
        "Draft an outbound email and queue it for human approval (the artist taps Approve in chat).",
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
        "propose_connector_email_reply",
        "Draft a reply to an existing email thread; queued for human approval. "
        "If `to` is omitted, defaults to the last inbound sender in the thread.",
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
        "propose_connector_calendar_create",
        "Draft a new calendar event; queued for human approval.",
        {
            "connection_id": {"type": "integer"},
            "summary": {"type": "string", "maxLength": 500},
            "start_iso": {"type": "string"},
            "end_iso": {"type": "string"},
            "description": {"type": "string"},
            "timezone": {"type": "string"},
            **_IDEMPOTENCY,
        },
        required=["connection_id", "summary", "start_iso", "end_iso"],
    ),
    _fn(
        "propose_connector_calendar_update",
        "Propose an update to an existing calendar event; queued for human approval.",
        {
            "connection_id": {"type": "integer"},
            "event_id": {"type": "string"},
            "summary": {"type": "string"},
            "description": {"type": "string"},
            "start_iso": {"type": "string"},
            "end_iso": {"type": "string"},
            "timezone": {"type": "string"},
            **_IDEMPOTENCY,
        },
        required=["connection_id", "event_id"],
    ),
    _fn(
        "propose_connector_calendar_delete",
        "Propose deleting an existing calendar event; queued for human approval.",
        {
            "connection_id": {"type": "integer"},
            "event_id": {"type": "string"},
            **_IDEMPOTENCY,
        },
        required=["connection_id", "event_id"],
    ),
    _fn(
        "propose_connector_file_upload",
        "Propose uploading a file to Drive/OneDrive; queued for human approval. "
        "Provide either content_text or content_base64.",
        {
            "connection_id": {"type": "integer"},
            "path": {"type": "string", "maxLength": 1024},
            "mime_type": {"type": "string"},
            "content_text": {"type": "string"},
            "content_base64": {"type": "string"},
            **_IDEMPOTENCY,
        },
        required=["connection_id", "path", "mime_type"],
    ),
    _fn(
        "propose_connector_file_share",
        "Propose sharing an existing file with someone; queued for human approval.",
        {
            "connection_id": {"type": "integer"},
            "file_id": {"type": "string"},
            "email": {"type": "string"},
            "role": {"type": "string", "enum": ["reader", "writer"]},
            **_IDEMPOTENCY,
        },
        required=["connection_id", "file_id", "email"],
    ),
    _fn(
        "propose_connector_teams_message",
        "Propose posting a message in a Teams channel; queued for human approval.",
        {
            "connection_id": {"type": "integer"},
            "team_id": {"type": "string"},
            "channel_id": {"type": "string"},
            "body": {"type": "string"},
            **_IDEMPOTENCY,
        },
        required=["connection_id", "team_id", "channel_id", "body"],
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
        "Deliver the FINAL natural-language reply to the artist. Call this exactly "
        "once, only after you have gathered enough information from the other tools "
        "(or are certain no tool is needed). After this call the conversation turn "
        "ends — do NOT call any other tool in the same response.",
        {
            "text": {
                "type": "string",
                "description": (
                    "The reply shown verbatim to the artist, in the same language "
                    "they used (default Spanish). Be concise and conversational."
                ),
            },
            "citations": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional list of bare ids referenced in the reply, e.g. "
                    "[\"deal:12\", \"email:3\", \"drive_file:7\"]."
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


AGENT_TOOL_NAMES: frozenset[str] = frozenset(
    t["function"]["name"] for t in AGENT_TOOLS
)


# Tool names the agent loop should treat as "fetches more context" rather
# than terminators. Used by the loop to know when to stop iterating.
EXECUTABLE_TOOL_NAMES: frozenset[str] = AGENT_TOOL_NAMES - {FINAL_ANSWER_TOOL_NAME}
