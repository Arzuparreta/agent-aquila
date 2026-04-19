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
        "Use when the artist asks an open-ended 'what do you know about X?' / 'find "
        "anything related to Y' question that could match across multiple data types "
        "at once (contacts, deals, events, emails, AND files). Combines semantic + "
        "keyword search across the entire CRM mirror. "
        "Do NOT use for type-specific queries — for emails use search_emails, for "
        "files use search_drive or list_drive_files, for calendar use "
        "list_calendar_events. Those are stricter and faster. "
        "Inputs: ``query`` (natural-language), optional ``limit_per_type`` (1-8, "
        "default 5). "
        "Returns: hits grouped by entity type (contact / deal / event / email / "
        "drive_file) with id, summary, and a relevance score.",
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
        "Use when you ALREADY know the exact id of a CRM or Drive object (typically "
        "from a prior search/list result) and you need its full details to answer "
        "the artist accurately. "
        "Do NOT use for searching — call hybrid_rag_search, search_emails, or "
        "search_drive instead and then call this on the returned id. "
        "Inputs: ``entity_type`` (one of contact / email / deal / event / "
        "drive_file / attachment) and ``entity_id`` (integer). "
        "Returns: the full record for that entity, or an error if it does not "
        "exist or does not belong to the artist.",
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
        "Use when the artist asks about emails / correo / mensajes / inbox — for "
        "example 'qué correos tengo de X', 'busca el último mail del promotor', "
        "'mensajes sobre la fecha de Bilbao'. Filters the mirrored Gmail/Outlook "
        "index newest-first. "
        "Do NOT use for non-email content — use search_drive for files, "
        "list_calendar_events for agenda. "
        "Inputs: optional ``query`` (matches subject / body / sender), optional "
        "``direction`` (inbound or outbound), optional ``thread_id`` to scope to a "
        "single conversation, optional ``connection_id``, optional ``limit`` "
        "(1-25). All inputs are optional — calling with no arguments returns the "
        "most recent emails. "
        "Returns: matching messages with id, subject, sender, snippet, "
        "thread_id, sent_at, and a sync_health field that flags when the "
        "underlying email sync is broken.",
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
        "Use when the artist asks for the full back-and-forth of a specific email "
        "conversation, or when you need full context (not just the snippet) of a "
        "thread you already located via search_emails. "
        "Do NOT use to search across threads — use search_emails first, then call "
        "this on the returned thread_id. "
        "Inputs: ``thread_id`` (provider thread id, required), optional "
        "``connection_id``. "
        "Returns: every message in the thread, oldest-first, with full bodies.",
        {
            "thread_id": {"type": "string"},
            "connection_id": {"type": "integer"},
        },
        required=["thread_id"],
    ),
    _fn(
        "list_calendar_events",
        "Use when the artist asks about their agenda / calendario / próximas fechas / "
        "shows / what they have scheduled. Lists the mirrored Google or Outlook "
        "calendar events. "
        "Do NOT use for proposing new events — use propose_connector_calendar_create "
        "for that. "
        "Inputs: optional ``start`` and ``end`` (ISO 8601 datetimes — narrow the "
        "window for date-specific questions like 'qué tengo este mes'), optional "
        "``connection_id``, optional ``limit`` (1-50). All inputs are optional. "
        "Returns: events sorted by start time with id, summary, start, end, "
        "location, and a sync_health field that flags when the calendar sync is "
        "broken.",
        {
            "start": {"type": "string", "description": "ISO 8601 lower bound."},
            "end": {"type": "string", "description": "ISO 8601 upper bound."},
            "connection_id": {"type": "integer"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
        },
    ),
    _fn(
        "search_drive",
        "Use when the artist asks for a SPECIFIC file by name or content keyword — "
        "e.g. 'búscame el rider de X', 'encuéntrame el contrato de Bilbao', 'el "
        "PDF que dice technical specs'. Searches the mirrored Drive/OneDrive index "
        "by filename and extracted text. "
        "Do NOT use for the open-ended 'qué archivos tengo' question — use "
        "list_drive_files for that, since the artist is browsing rather than "
        "searching. Do NOT use for emails (use search_emails). "
        "Inputs: ``query`` (required, free text), optional ``limit`` (1-25). "
        "Returns: matching files with id, name, mime_type, web_view_link, "
        "modified_at, and a sync_health field that flags when the Drive sync is "
        "broken.",
        {
            "query": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 25},
        },
        required=["query"],
    ),
    _fn(
        "list_drive_files",
        "Use when the artist asks an open-ended 'what files do I have?' question "
        "WITHOUT a specific search term — e.g. 'qué archivos tengo', 'muéstrame "
        "mis archivos', 'qué tengo en mi drive', 'what's in my drive'. Lists the "
        "mirrored Drive/OneDrive index, most-recently-modified first. "
        "Do NOT use when the artist gave you something specific to look for — use "
        "search_drive instead. Do NOT use to extract a single file's text — use "
        "get_drive_file_text. "
        "Inputs: all optional — ``limit`` (1-50), ``connection_id``, ``mime_type`` "
        "to filter by type. "
        "Returns: files with id, name, mime_type, web_view_link, modified_at, "
        "and a sync_health field that flags when the Drive sync is broken (e.g. "
        "the artist will see no files when in fact the connector token expired).",
        {
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            "connection_id": {"type": "integer"},
            "mime_type": {"type": "string"},
        },
    ),
    _fn(
        "get_drive_file_text",
        "Use when the artist asks about the CONTENTS of a specific file you "
        "already located via search_drive or list_drive_files — e.g. 'qué dice "
        "ese contrato', 'resúmeme el rider', 'cuál es el caché en ese PDF'. "
        "Triggers on-demand text extraction (PDF / DOCX / etc.) and caches the "
        "result. "
        "Do NOT use to discover files — call list_drive_files / search_drive "
        "first to obtain a file_id. "
        "Inputs: ``file_id`` (integer, required — the local mirror id from a "
        "previous list/search call). "
        "Returns: the extracted plain text plus the file's metadata, or an error "
        "if extraction failed (e.g. unsupported format, file too large).",
        {"file_id": {"type": "integer"}},
        required=["file_id"],
    ),
    _fn(
        "list_automations",
        "Use when the artist asks what rules / preferences / automations they "
        "currently have set — e.g. 'qué reglas tengo', 'qué automatizaciones', "
        "'qué te pedí que recordaras'. "
        "Do NOT use to create or modify rules — use create_automation, "
        "update_automation, or delete_automation. "
        "Inputs: none. "
        "Returns: every active automation rule with id, name, "
        "instruction_natural_language, trigger, conditions, and enabled flag.",
    ),
    _fn(
        "list_connectors",
        "Use when the artist asks about their connected services — e.g. 'qué "
        "tengo conectado', 'qué cuentas hay vinculadas', 'está conectado mi "
        "Gmail'. Returns a status snapshot for every connector connection. "
        "Do NOT use to set up a new connector — use start_connector_setup. Do NOT "
        "use to start an OAuth flow — use start_oauth_flow. "
        "Inputs: none. "
        "Returns: each connection with id, provider, label, status (active / "
        "error / disabled), last_sync_at, and any current error message.",
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
        "Use when the artist clearly wants to add a new person to their CRM — "
        "e.g. 'agrega a Juan como promotor', 'guárdame este contacto'. Creates "
        "the contact immediately; the artist sees an UNDO chip in chat. "
        "Do NOT use when the contact already exists (call hybrid_rag_search "
        "first if unsure). Do NOT use for CRM updates — use apply_update_contact. "
        "Inputs: ``name`` (required), optional ``email``, ``phone``, ``role`` "
        "(promoter / venue / agent / manager / other), ``notes``. "
        "Returns: the created contact with its new id, plus an executed_action "
        "card the artist can undo.",
        _contact_props(include_id=False),
        required=["name"],
    ),
    _fn(
        "apply_update_contact",
        "Use when the artist asks to modify an existing CRM contact — e.g. "
        "'cambia el rol de Juan a manager', 'actualiza el teléfono de María'. "
        "Applies immediately with an UNDO chip. "
        "Do NOT use to create — use apply_create_contact. You MUST already know "
        "``contact_id`` (from a prior search/get). "
        "Inputs: ``contact_id`` (required), plus any of ``name`` / ``email`` / "
        "``phone`` / ``role`` / ``notes`` you want to change. "
        "Returns: the updated contact and an undoable executed_action.",
        _contact_props(include_id=True),
        required=["contact_id"],
    ),
    _fn(
        "apply_create_deal",
        "Use when the artist confirms a new business opportunity / negotiation — "
        "e.g. 'abre un deal con el promotor de Bilbao por 5000€'. Creates the "
        "deal immediately with an UNDO chip. "
        "Do NOT use without first having (or creating) the related contact. Do "
        "NOT use for updates — use apply_update_deal. "
        "Inputs: ``contact_id`` (required), ``title`` (required), optional "
        "``status`` (new/contacted/negotiating/won/lost), ``amount``, "
        "``currency``, ``notes``. "
        "Returns: the created deal and an undoable executed_action.",
        _deal_props(include_id=False),
        required=["contact_id", "title"],
    ),
    _fn(
        "apply_update_deal",
        "Use when the artist updates a deal status / amount / notes — e.g. 'el "
        "deal con Bilbao está cerrado', 'sube el caché a 6000'. Applies "
        "immediately with an UNDO chip. "
        "Do NOT use to create — use apply_create_deal. You MUST already know "
        "``deal_id``. "
        "Inputs: ``deal_id`` (required) plus any of ``title`` / ``status`` / "
        "``amount`` / ``currency`` / ``notes``. "
        "Returns: the updated deal and an undoable executed_action.",
        _deal_props(include_id=True),
        required=["deal_id"],
    ),
    _fn(
        "apply_create_event",
        "Use when the artist confirms a new show / gig / event in their CRM — "
        "e.g. 'apunta el bolo del 15 de marzo en Madrid'. Creates the CRM event "
        "row immediately with an UNDO chip. "
        "Do NOT use to publish to Google/Outlook calendar — that requires "
        "approval; use propose_connector_calendar_create. "
        "Inputs: ``venue_name`` (required), ``event_date`` (YYYY-MM-DD, "
        "required), optional ``deal_id``, ``city``, ``status`` "
        "(confirmed/tentative/cancelled), ``notes``. "
        "Returns: the created event and an undoable executed_action.",
        _event_props(include_id=False),
        required=["venue_name", "event_date"],
    ),
    _fn(
        "apply_update_event",
        "Use when the artist updates an existing CRM event — e.g. 'cambia la "
        "fecha del bolo de Madrid', 'márcalo como confirmado'. Applies "
        "immediately with an UNDO chip. "
        "Do NOT use without ``event_id`` (look it up first). Do NOT use to "
        "publish a calendar event change to Google/Outlook — use "
        "propose_connector_calendar_update for that. "
        "Inputs: ``event_id`` (required) plus any of the event fields. "
        "Returns: the updated event and an undoable executed_action.",
        _event_props(include_id=True),
        required=["event_id"],
    ),
    _fn(
        "create_automation",
        "Use IMMEDIATELY whenever the artist expresses a standing preference / "
        "rule in plain language — e.g. 'nunca le envíes correos a X', 'siempre "
        "CC bookings@...', 'no me molestes con notificaciones de Y', "
        "'recuérdame que...'. Do NOT ask permission first; record the rule and "
        "then confirm verbally in your final_answer ('Hecho — no le volveré a "
        "escribir a X.'). "
        "Do NOT use for one-off requests — only for things the artist wants to "
        "apply going forward. "
        "Inputs: ``instruction_natural_language`` (required, the rule in the "
        "artist's own words), optional ``name``, ``trigger`` (currently only "
        "email_received), ``conditions`` object. "
        "Returns: the created automation rule.",
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
        "Use when the artist amends an existing rule — e.g. 'también que CC a "
        "manager@', 'desactívala por ahora'. "
        "Do NOT use to create — use create_automation. You MUST already know "
        "``automation_id`` (call list_automations first if unsure). "
        "Inputs: ``automation_id`` (required), plus any of ``name`` / "
        "``conditions`` / ``instruction_natural_language`` / ``enabled``. "
        "Returns: the updated rule.",
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
        "Use when the artist explicitly retracts a previously-saved rule — e.g. "
        "'olvida lo que te dije sobre X', 'borra esa regla'. "
        "Do NOT use to temporarily disable — use update_automation with "
        "``enabled=false`` instead. You MUST already know ``automation_id``. "
        "Inputs: ``automation_id`` (required). "
        "Returns: confirmation that the rule was removed.",
        {"automation_id": {"type": "integer"}},
        required=["automation_id"],
    ),
    _fn(
        "start_connector_setup",
        "Use when the artist asks to connect a new account — e.g. 'conéctame mi "
        "Gmail', 'quiero vincular Outlook'. Renders the in-chat setup card so "
        "the artist can paste their OAuth client credentials. "
        "Do NOT use to start the OAuth consent flow — that's start_oauth_flow, "
        "which runs after credentials are submitted. Do NOT use to list "
        "existing connectors — that's list_connectors. "
        "Inputs: ``provider`` (google or microsoft, required). "
        "Returns: a setup_token plus the in-chat card payload.",
        {"provider": {"type": "string", "enum": ["google", "microsoft"]}},
        required=["provider"],
    ),
    _fn(
        "submit_connector_credentials",
        "Use when the artist has just typed their OAuth client_id / "
        "client_secret into the setup card and confirmed. Stores the credentials "
        "and prepares the OAuth flow. "
        "Do NOT use without a fresh ``setup_token`` from start_connector_setup. "
        "Inputs: ``setup_token`` (required), ``client_id`` (required), "
        "``client_secret`` (required), optional ``redirect_uri``, ``tenant`` "
        "(for multi-tenant Microsoft). "
        "Returns: confirmation plus the connection_id once stored.",
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
        "Use after credentials are stored when the artist needs to grant access "
        "to a specific service — e.g. 'dame el link para autorizar el Drive'. "
        "Returns the OAuth consent URL the artist taps. "
        "Do NOT use before submit_connector_credentials has succeeded for that "
        "provider. "
        "Inputs: ``provider`` (google or microsoft) and ``service`` (gmail / "
        "calendar / drive / outlook / teams), both required. "
        "Returns: the consent URL and an opaque state token for the callback.",
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
        "Use when the artist asks you to send a brand-new email — e.g. "
        "'mándale un correo a X', 'escribe a bookings@ pidiendo Y'. Drafts the "
        "message and queues an approval card; nothing is sent until the artist "
        "taps Approve in chat. "
        "Do NOT use to reply to an existing thread — use "
        "propose_connector_email_reply (which preserves headers / "
        "in-reply-to). Do NOT use without first knowing which "
        "``connection_id`` to send from (call list_connectors if unsure). "
        "Inputs: ``connection_id`` (required), ``to`` (required, string or "
        "array), ``subject`` (required), ``body`` (required), optional "
        "``content_type`` (text or html). "
        "Returns: a pending_proposal id; the email is queued, not sent.",
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
        "Use when the artist asks you to reply to a SPECIFIC email or thread you "
        "already located via search_emails / get_thread — e.g. 'contesta al "
        "promotor', 'respóndele al último correo'. Drafts the reply and queues "
        "an approval card; preserves thread headers so the reply lands in the "
        "right conversation. "
        "Do NOT use to start a brand-new email — use propose_connector_email_send "
        "instead. You MUST know ``thread_id`` (from search_emails / get_thread). "
        "Inputs: ``connection_id`` (required), ``thread_id`` (required), "
        "``body`` (required), optional ``in_reply_to`` (provider message id), "
        "``to`` (defaults to the last inbound sender if omitted), ``subject``, "
        "``content_type``. "
        "Returns: a pending_proposal id; the reply is queued, not sent.",
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
        "Use when the artist asks you to create a new event in their actual "
        "Google/Outlook CALENDAR (not just the internal CRM) — e.g. 'agéndame "
        "una reunión con X el viernes a las 5'. Drafts the event and queues an "
        "approval card; nothing is published until the artist taps Approve. "
        "Do NOT use for the internal-only CRM event row — use apply_create_event "
        "for that. Do NOT use to update an existing event — use "
        "propose_connector_calendar_update. "
        "Inputs: ``connection_id`` (required), ``summary`` (required), "
        "``start_iso`` (required), ``end_iso`` (required), optional "
        "``description``, ``timezone``. "
        "Returns: a pending_proposal id; the event is queued, not created.",
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
        "Use when the artist asks to change an existing Google/Outlook calendar "
        "event — e.g. 'mueve la reunión a las 6', 'cámbiale el título'. Queues "
        "an approval card. "
        "Do NOT use without an ``event_id`` from list_calendar_events. Do NOT "
        "use to delete — use propose_connector_calendar_delete. "
        "Inputs: ``connection_id`` (required), ``event_id`` (required, the "
        "provider event id), plus any of ``summary`` / ``description`` / "
        "``start_iso`` / ``end_iso`` / ``timezone`` to change. "
        "Returns: a pending_proposal id; the change is queued, not applied.",
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
        "Use when the artist asks to cancel / remove an existing Google/Outlook "
        "calendar event — e.g. 'cancela la reunión del jueves'. Queues an "
        "approval card. "
        "Do NOT use without an ``event_id`` from list_calendar_events. Do NOT "
        "use to merely mark a CRM event cancelled — use apply_update_event with "
        "``status=cancelled``. "
        "Inputs: ``connection_id`` (required), ``event_id`` (required). "
        "Returns: a pending_proposal id; the deletion is queued, not applied.",
        {
            "connection_id": {"type": "integer"},
            "event_id": {"type": "string"},
            **_IDEMPOTENCY,
        },
        required=["connection_id", "event_id"],
    ),
    _fn(
        "propose_connector_file_upload",
        "Use when the artist asks you to upload a new file to their Drive or "
        "OneDrive — e.g. 'súbeme este texto como PDF', 'guarda esto en mi "
        "drive'. Queues an approval card; nothing is uploaded until approved. "
        "Do NOT use to share an existing file — use propose_connector_file_share. "
        "Inputs: ``connection_id`` (required), ``path`` (required, target path "
        "in the user's drive), ``mime_type`` (required), and EITHER "
        "``content_text`` (for plain text) OR ``content_base64`` (for binary). "
        "Returns: a pending_proposal id; the upload is queued.",
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
        "Use when the artist asks to share an EXISTING Drive/OneDrive file with "
        "someone — e.g. 'comparte el rider con bookings@', 'dale acceso de "
        "lectura a Juan'. Queues an approval card. "
        "Do NOT use to upload a new file — use propose_connector_file_upload. "
        "You MUST already know the provider ``file_id`` (look it up via "
        "search_drive / list_drive_files first). "
        "Inputs: ``connection_id`` (required), ``file_id`` (required, provider "
        "id of the existing file), ``email`` (required, recipient), optional "
        "``role`` (reader or writer; defaults to reader). "
        "Returns: a pending_proposal id; the share is queued, not applied.",
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
        "Use when the artist asks to post a message into a Microsoft Teams "
        "channel — e.g. 'mándale al canal de tour avisando que...'. Queues an "
        "approval card. "
        "Do NOT use for email — use propose_connector_email_send. You MUST "
        "already know ``team_id`` and ``channel_id``. "
        "Inputs: ``connection_id`` (required), ``team_id`` (required), "
        "``channel_id`` (required), ``body`` (required). "
        "Returns: a pending_proposal id; the message is queued, not posted.",
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
        "Use to deliver the FINAL natural-language reply to the artist. This is "
        "the terminator — calling it ends the turn. Call it EXACTLY ONCE, AFTER "
        "you have gathered enough information from the other tools (or you are "
        "certain no data tool is needed for a chitchat-style message). "
        "Do NOT call this on turn 1 for a factual question about the artist's "
        "data — first call the appropriate data tool to ground the answer, then "
        "call this with a summary that cites the result. Do NOT call any other "
        "tool in the same response as this one. "
        "Inputs: ``text`` (required, the reply shown verbatim to the artist, in "
        "the same language they used — default Spanish, conversational, "
        "concise), optional ``citations`` (array of bare ids referenced in the "
        "reply, e.g. ``[\"deal:12\", \"drive_file:7\"]``). "
        "Returns: ``{ok: true}``; the reply is recorded as the run output.",
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
