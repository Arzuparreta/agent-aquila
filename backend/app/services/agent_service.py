from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.agent_run import AgentRun, AgentRunStep
from app.models.contact import Contact
from app.models.deal import Deal
from app.models.drive_file import DriveFile
from app.models.email import Email
from app.models.event import Event
from app.models.pending_proposal import PendingProposal
from app.models.user import User
from app.schemas.agent import AgentRunRead, AgentStepRead, PendingProposalRead
from app.services.agent_tools import (
    AGENT_TOOL_NAMES,
    AGENT_TOOLS,
    EXECUTABLE_TOOL_NAMES,
    FINAL_ANSWER_TOOL_NAME,
)
from app.services.ai_providers import provider_kind_requires_api_key
from app.services.llm_client import ChatResponse, ChatToolCall, LLMClient
from app.services.proposal_service import proposal_to_read
from app.services.semantic_search_service import SemanticSearchService
from app.services.user_ai_settings_service import UserAISettingsService

# ---------------------------------------------------------------------------
# Tool-name aliasing
# ---------------------------------------------------------------------------
# Small instruction-tuned models (notably Gemma 3/4 on Ollama) have heavy
# RLHF priors that make them emit tool names from THEIR training (e.g.
# ``google:search``) instead of the names we advertise. Rather than telling
# the model "no, try again" and hoping it self-corrects (which Gemma in
# particular doesn't reliably do — it just retries the same wrong name in
# a tight loop), we accept a small set of well-known aliases and rewrite
# them to the matching real tool name. This recovers gracefully for the
# common confusions and is a no-op for everything else.
TOOL_NAME_ALIASES: dict[str, str] = {
    # Gemma's pretraining bias.
    "google:search": "hybrid_rag_search",
    "google_search": "hybrid_rag_search",
    "websearch": "hybrid_rag_search",
    "search": "hybrid_rag_search",
    # Common abbreviations small models reach for.
    "list_files": "list_drive_files",
    "drive_list_files": "list_drive_files",
    "list_drive": "list_drive_files",
    "search_files": "search_drive",
    "drive_search": "search_drive",
    "get_file": "get_drive_file_text",
    "read_file": "get_drive_file_text",
    "list_emails": "search_emails",
    "email_search": "search_emails",
    "list_events": "list_calendar_events",
    "calendar_list": "list_calendar_events",
    # Final-answer aliases.
    "answer": FINAL_ANSWER_TOOL_NAME,
    "respond": FINAL_ANSWER_TOOL_NAME,
    "reply": FINAL_ANSWER_TOOL_NAME,
}


def _resolve_tool_name(name: str | None) -> str | None:
    """Map a possibly-aliased / case-mangled tool name to a real one, or
    return ``None`` if no resolution is possible."""
    if not name:
        return None
    if name in AGENT_TOOL_NAMES:
        return name
    lowered = name.lower().strip()
    if lowered in AGENT_TOOL_NAMES:
        return lowered
    aliased = TOOL_NAME_ALIASES.get(lowered)
    if aliased and aliased in AGENT_TOOL_NAMES:
        return aliased
    return None


# ---------------------------------------------------------------------------
# Intent-based tool palette filtering
# ---------------------------------------------------------------------------
# Small local models (Gemma, Qwen 2.5 small, Llama 3.2 3B) struggle when given
# 30 unrelated tool schemas — they routinely fall back to RLHF priors like
# ``google:search`` instead of picking the right one. The fix is to look at
# the artist's last user message and, when the intent is obvious, advertise
# only the tools that are actually relevant. This dramatically lifts tool-
# selection accuracy without needing a separate classifier model.
#
# Rules are intentionally conservative: when in doubt we fall back to the
# full palette so the model never has access ripped away from it.

_INTENT_TOOL_GROUPS: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
    # Drive / files / documents.
    (
        ("archivo", "archivos", "drive", "carpeta", "documento", "documentos",
         "file", "files", "rider", "contrato", "pdf"),
        ("list_drive_files", "search_drive", "get_drive_file_text",
         "hybrid_rag_search"),
    ),
    # Email.
    (
        ("correo", "correos", "email", "emails", "mail", "mails",
         "mensaje", "mensajes", "bandeja", "inbox"),
        ("search_emails", "get_thread", "hybrid_rag_search"),
    ),
    # Calendar / agenda.
    (
        ("agenda", "calendario", "calendar", "evento", "eventos",
         "cita", "citas", "agendado", "fecha", "fechas"),
        ("list_calendar_events", "hybrid_rag_search"),
    ),
    # Connector / integration setup.
    (
        ("conectar", "conecta", "conexión", "conexion", "conectores",
         "integración", "integracion", "google", "outlook", "spotify",
         "instagram", "oauth"),
        ("list_connectors", "start_connector_setup",
         "submit_connector_credentials", "start_oauth_flow"),
    ),
    # Automations / preferences.
    (
        ("automatización", "automatizacion", "automatizaciones",
         "regla", "reglas", "preferencia", "preferencias",
         "siempre", "nunca", "no vuelvas", "recordar"),
        ("create_automation", "list_automations", "update_automation",
         "delete_automation"),
    ),
]


def _select_tool_palette(
    last_user_message: str,
) -> list[dict[str, Any]]:
    """Return the subset of AGENT_TOOLS that's relevant to the user's last
    message. Always includes ``final_answer`` so the model can terminate.
    Falls back to the full palette when no intent matches."""
    if not last_user_message:
        return AGENT_TOOLS
    text = last_user_message.lower()

    matched: set[str] = set()
    for keywords, tools in _INTENT_TOOL_GROUPS:
        if any(kw in text for kw in keywords):
            matched.update(tools)

    if not matched:
        return AGENT_TOOLS

    # Always include the terminator so we never strand the model.
    matched.add(FINAL_ANSWER_TOOL_NAME)
    return [t for t in AGENT_TOOLS if t["function"]["name"] in matched]


def _normalize_tool_args(resolved_name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Coerce common argument-shape variants to the canonical names each tool
    expects. Pairs with ``_resolve_tool_name``: when we accept ``google:search``
    as an alias for ``hybrid_rag_search``, we also need to accept its
    ``{"queries": [...]}`` arg shape. Conservative: only rewrites keys that
    are clearly synonymous, leaves everything else untouched."""
    if not isinstance(args, dict):
        return {}
    out = dict(args)

    if resolved_name == "hybrid_rag_search":
        if "query" not in out:
            if isinstance(out.get("queries"), list) and out["queries"]:
                out["query"] = " ".join(str(q) for q in out["queries"])
            elif isinstance(out.get("q"), str):
                out["query"] = out.pop("q")
            elif isinstance(out.get("text"), str):
                out["query"] = out.pop("text")
    elif resolved_name == "search_emails" or resolved_name == "search_drive":
        if "q" not in out:
            for k in ("query", "text", "search"):
                if isinstance(out.get(k), str):
                    out["q"] = out[k]
                    break
    elif resolved_name == FINAL_ANSWER_TOOL_NAME:
        if "text" not in out:
            for k in ("answer", "reply", "message", "content"):
                if isinstance(out.get(k), str):
                    out["text"] = out[k]
                    break
    return out

# The agent uses the provider's NATIVE function/tool-calling API (see
# ``LLMClient.chat_with_tools``), so the system prompt deliberately does NOT
# enumerate tool schemas — those are passed as a typed ``tools=[]`` array,
# which is dramatically more reliable than asking the model to author a
# bespoke JSON envelope (especially for small local models like Gemma /
# Qwen / Llama via Ollama). The prompt only carries persona + behavior
# rules; the schemas live in ``agent_tools.AGENT_TOOLS``.
AGENT_SYSTEM = """You are the artist's personal operations manager (live music: festivals, concerts, venues, promoters). The artist is NON-TECHNICAL — never mention APIs, OAuth, RAG, embeddings, JSON, model names, or any internal implementation. Speak like a friendly colleague.

You operate inside a chat app. The artist may be talking to you about a specific contact, deal, event or email (the thread title indicates this). When proactive notifications arrive ("Nuevo correo entrante de X"), you continue the conversation in that same thread.

# How to respond — IMPORTANT

Every assistant turn MUST end in a tool call. You have two kinds of tools:

1. Data/action tools — fetch information or perform actions on behalf of the artist (e.g. list_drive_files, search_emails, hybrid_rag_search, apply_create_contact, propose_connector_email_send, ...). Use these to GATHER data or DO things.
2. final_answer — deliver the user-facing reply. Call this EXACTLY ONCE, when you are ready to talk to the artist. After final_answer the turn ends.

You may call as many data/action tools as you need before calling final_answer. Never write a free-form text reply outside of final_answer — the artist will not see it.

# Behavior rules

- Always pick a tool from the provided tools list. Do NOT invent tool names — use the exact names spelled in the schema.
- Always reply in the same language the artist uses (default: Spanish), inside `final_answer.text`.
- For ANY factual question about the artist's own data (their files, contacts, deals, events, emails, calendar), you MUST first call a data tool to ground the answer. Never guess, never paraphrase from memory, and never repeat what a previous assistant turn said about that data — re-check with a tool every time.
  - "¿Qué archivos tengo?" / "qué tengo en mi drive" → call list_drive_files (NOT list_files; the tool is named list_drive_files).
  - "Busca el rider de X" / "encuéntrame el contrato" → call search_drive or hybrid_rag_search.
  - "¿Qué correos tengo de X?" → call search_emails.
  - "¿Qué tengo agendado?" → call list_calendar_events.
  - General "¿qué sabes de X?" → call hybrid_rag_search.
- After tools return, summarize the actual result in `final_answer.text`. If a tool result is empty, say so honestly ("No encontré archivos en tu Drive todavía, ¿quieres que conectemos Drive?"). Never invent files, names, or numbers that did not come from a tool result.
- When the artist expresses a preference ("don't email X", "always CC bookings@..."), call create_automation IMMEDIATELY without asking, then call final_answer to confirm verbally ("Hecho — no volveré a escribir a X.").
- Be concise. The artist is busy.
- Cite bare ids inline in `final_answer.text` (e.g. "(drive_file:7)") and/or in `final_answer.citations`.
- If a data tool result includes a `sync_health` field with `ok: false`, the underlying connector is failing to sync. Tell the artist what's broken in plain language (using the `summary` field) and that the data they're seeing may be stale or incomplete. Example: "Tu Drive está conectado pero la sincronización está fallando — necesito que reactives el acceso. Mientras tanto te muestro lo último que tengo guardado."
"""


# ---------------------------------------------------------------------------
# Connector sync-health surfacing
# ---------------------------------------------------------------------------
# The agent's read tools (list_drive_files, search_emails, list_calendar_events)
# all read from the local mirror tables. When the upstream sync is broken
# (API disabled, token revoked, scope missing, rate limit), those tables are
# stale or empty — and previously the agent had no way to know that. The
# helper below reads `connection_sync_state` for the relevant
# (provider, resource) and returns a small structured payload that we attach
# to every read-tool result so the model can warn the artist instead of
# silently reporting "you have no files".

# Map a logical "domain" → (connector_connections.provider values, sync resource label)
_SYNC_HEALTH_DOMAINS: dict[str, tuple[tuple[str, ...], str]] = {
    "drive": (
        ("google_drive", "google", "microsoft", "graph_onedrive", "onedrive"),
        "drive",
    ),
    "email": (
        ("google_gmail", "google", "microsoft", "graph_mail"),
        "gmail",  # gmail_sync_service writes resource="gmail"
    ),
    "calendar": (
        ("google_calendar", "google", "microsoft", "graph_calendar"),
        "calendar",
    ),
}


async def _get_sync_health(
    db: AsyncSession, user: User, domain: str
) -> dict[str, Any]:
    """Return a small dict describing the sync-health for the connectors of a
    given ``domain`` ("drive" / "email" / "calendar") for ``user``. Always
    safe to call (returns ``{"ok": True, ...}`` when nothing is wrong or when
    the user has no relevant connectors). The shape is stable so the system
    prompt can teach the model how to interpret it.
    """
    from app.models.connection_sync_state import ConnectionSyncState
    from app.models.connector_connection import ConnectorConnection

    providers, resource = _SYNC_HEALTH_DOMAINS.get(domain, ((), ""))
    if not providers:
        return {"ok": True, "checked": False}

    stmt = (
        select(ConnectionSyncState, ConnectorConnection)
        .join(
            ConnectorConnection,
            ConnectorConnection.id == ConnectionSyncState.connection_id,
        )
        .where(
            ConnectorConnection.user_id == user.id,
            ConnectorConnection.provider.in_(providers),
            ConnectionSyncState.resource == resource,
        )
    )
    rows = (await db.execute(stmt)).all()
    if not rows:
        # No sync-state row at all: connector may be brand-new or never
        # synced. Not necessarily broken — just unknown.
        return {"ok": True, "checked": True, "states": []}

    errors: list[dict[str, Any]] = []
    healthy: list[dict[str, Any]] = []
    for state, conn in rows:
        entry = {
            "connection_id": conn.id,
            "provider": conn.provider,
            "label": conn.label,
            "status": state.status,
            "last_full_sync_at": (
                state.last_full_sync_at.isoformat() if state.last_full_sync_at else None
            ),
            "last_delta_at": (
                state.last_delta_at.isoformat() if state.last_delta_at else None
            ),
            "error_count": state.error_count,
        }
        if state.status == "error" and state.last_error:
            entry["last_error"] = (state.last_error or "")[:600]
            errors.append(entry)
        else:
            healthy.append(entry)

    if errors:
        # Synthesize a short, artist-friendly summary the model can echo.
        first = errors[0]
        provider_friendly = (
            "Drive" if domain == "drive"
            else "Calendario" if domain == "calendar"
            else "Correo"
        )
        # Try to extract the human-readable bit from the upstream error.
        raw = first.get("last_error", "") or ""
        if "API has not been used" in raw or "is disabled" in raw:
            cause = "el API correspondiente está desactivado en el proyecto de Google Cloud"
        elif "invalid_grant" in raw or "unauthorized" in raw.lower() or "401" in raw:
            cause = "el acceso caducó y necesita re-autorizarse"
        elif "403" in raw or "permission" in raw.lower():
            cause = "faltan permisos en la cuenta conectada"
        elif "rate" in raw.lower() and "limit" in raw.lower():
            cause = "el proveedor está limitando el ritmo de sincronización"
        else:
            cause = "hay un error de sincronización con el proveedor"
        summary = (
            f"La conexión de {provider_friendly} ({first['provider']}) está fallando: "
            f"{cause}. Lo que ves puede estar incompleto o desactualizado."
        )
        return {"ok": False, "checked": True, "summary": summary, "errors": errors, "healthy": healthy}

    return {"ok": True, "checked": True, "healthy": healthy}


def _assistant_message_from(response: ChatResponse) -> dict[str, Any]:
    """Re-encode an assistant ``ChatResponse`` into a chat-completions message.

    We deliberately rebuild the dict (rather than reusing ``raw_message``) so
    the conversation history we feed back to the next call is exactly the
    OpenAI tool-calling shape, regardless of provider-specific extras.
    """
    msg: dict[str, Any] = {"role": "assistant", "content": response.content or None}
    if response.tool_calls:
        msg["tool_calls"] = [tc.to_message_dict() for tc in response.tool_calls]
    return msg

class AgentService:
    @staticmethod
    def _serialize_contact(c: Contact) -> dict[str, Any]:
        return {
            "id": c.id,
            "name": c.name,
            "email": c.email,
            "phone": c.phone,
            "role": c.role,
            "notes": c.notes,
        }

    @staticmethod
    def _serialize_email(e: Email) -> dict[str, Any]:
        return {
            "id": e.id,
            "contact_id": e.contact_id,
            "sender_email": e.sender_email,
            "sender_name": e.sender_name,
            "subject": e.subject,
            "body": e.body,
            "received_at": e.received_at.isoformat(),
        }

    @staticmethod
    def _serialize_deal(d: Deal) -> dict[str, Any]:
        return {
            "id": d.id,
            "contact_id": d.contact_id,
            "title": d.title,
            "status": d.status,
            "amount": float(d.amount) if d.amount is not None else None,
            "currency": d.currency,
            "notes": d.notes,
        }

    @staticmethod
    def _serialize_event(ev: Event) -> dict[str, Any]:
        return {
            "id": ev.id,
            "deal_id": ev.deal_id,
            "venue_name": ev.venue_name,
            "event_date": ev.event_date.isoformat(),
            "city": ev.city,
            "status": ev.status,
            "notes": ev.notes,
        }

    @staticmethod
    async def _tool_get_entity(db: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
        et = str(args.get("entity_type") or "").lower()
        eid = int(args.get("entity_id"))
        if et == "contact":
            row = await db.get(Contact, eid)
            return {"found": row is not None, "entity": AgentService._serialize_contact(row) if row else None}
        if et == "email":
            row = await db.get(Email, eid)
            return {"found": row is not None, "entity": AgentService._serialize_email(row) if row else None}
        if et == "deal":
            row = await db.get(Deal, eid)
            return {"found": row is not None, "entity": AgentService._serialize_deal(row) if row else None}
        if et == "event":
            row = await db.get(Event, eid)
            return {"found": row is not None, "entity": AgentService._serialize_event(row) if row else None}
        if et == "drive_file":
            row = await db.get(DriveFile, eid)
            if not row:
                return {"found": False, "entity": None}
            return {
                "found": True,
                "entity": {
                    "id": row.id,
                    "connection_id": row.connection_id,
                    "name": row.name,
                    "mime_type": row.mime_type,
                    "size_bytes": row.size_bytes,
                    "web_view_link": row.web_view_link,
                    "modified_time": row.modified_time.isoformat() if row.modified_time else None,
                    "has_text": bool(row.content_text),
                },
            }
        return {"error": "invalid entity_type"}

    @staticmethod
    async def _tool_rag(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        q = str(args.get("query") or "").strip()
        if not q:
            return {"hits": [], "error": "missing query"}
        lim = int(args.get("limit_per_type") or 5)
        lim = max(1, min(8, lim))
        hits = await SemanticSearchService.search(db, user, q, lim)
        return {
            "hits": [
                {
                    "entity_type": h.entity_type,
                    "entity_id": h.entity_id,
                    "score": h.score,
                    "title": h.title,
                    "snippet": h.snippet,
                    "citation": h.citation,
                    "match_sources": h.match_sources,
                    "rrf_score": h.rrf_score,
                }
                for h in hits
            ]
        }

    @staticmethod
    async def _tool_search_emails(db: AsyncSession, user: User, args: dict[str, Any]) -> dict[str, Any]:
        from sqlalchemy import and_, or_

        limit = max(1, min(25, int(args.get("limit") or 10)))
        q = str(args.get("query") or "").strip()
        direction = str(args.get("direction") or "").strip().lower() or None
        thread_id = args.get("thread_id")
        connection_id = args.get("connection_id")

        filters = []
        if direction in ("inbound", "outbound"):
            filters.append(Email.direction == direction)
        if thread_id:
            filters.append(Email.provider_thread_id == str(thread_id))
        if connection_id is not None:
            filters.append(Email.connection_id == int(connection_id))
        if q:
            like = f"%{q}%"
            filters.append(or_(Email.subject.ilike(like), Email.body.ilike(like), Email.sender_email.ilike(like)))
        stmt = select(Email).order_by(Email.received_at.desc()).limit(limit)
        if filters:
            stmt = stmt.where(and_(*filters))
        r = await db.execute(stmt)
        hits = []
        for e in r.scalars().all():
            hits.append(
                {
                    "id": e.id,
                    "subject": e.subject,
                    "from": f"{e.sender_name or ''} <{e.sender_email}>",
                    "direction": e.direction,
                    "received_at": e.received_at.isoformat(),
                    "thread_id": e.provider_thread_id,
                    "snippet": (e.snippet or e.body or "")[:300],
                    "citation": f"email:{e.id}",
                }
            )
        sync_health = await _get_sync_health(db, user, "email")
        return {"hits": hits, "sync_health": sync_health}

    @staticmethod
    async def _tool_get_thread(db: AsyncSession, user: User, args: dict[str, Any]) -> dict[str, Any]:
        tid = str(args.get("thread_id") or "")
        if not tid:
            return {"error": "thread_id required"}
        stmt = select(Email).where(Email.provider_thread_id == tid)
        if args.get("connection_id") is not None:
            stmt = stmt.where(Email.connection_id == int(args["connection_id"]))
        r = await db.execute(stmt.order_by(Email.received_at.asc()))
        msgs = []
        for e in r.scalars().all():
            msgs.append(
                {
                    "id": e.id,
                    "direction": e.direction,
                    "from": f"{e.sender_name or ''} <{e.sender_email}>",
                    "subject": e.subject,
                    "received_at": e.received_at.isoformat(),
                    "body": (e.body or "")[:8000],
                    "citation": f"email:{e.id}",
                }
            )
        return {"thread_id": tid, "messages": msgs}

    @staticmethod
    async def _tool_list_calendar_events(db: AsyncSession, user: User, args: dict[str, Any]) -> dict[str, Any]:
        from datetime import datetime as dt

        limit = max(1, min(50, int(args.get("limit") or 20)))
        stmt = select(Event).order_by(Event.start_utc.asc().nulls_last(), Event.event_date.asc())
        if args.get("connection_id") is not None:
            stmt = stmt.where(Event.connection_id == int(args["connection_id"]))
        if args.get("start"):
            try:
                s_dt = dt.fromisoformat(str(args["start"]).replace("Z", "+00:00"))
                stmt = stmt.where((Event.start_utc >= s_dt) | (Event.event_date >= s_dt.date()))
            except ValueError:
                pass
        if args.get("end"):
            try:
                e_dt = dt.fromisoformat(str(args["end"]).replace("Z", "+00:00"))
                stmt = stmt.where((Event.start_utc <= e_dt) | (Event.event_date <= e_dt.date()))
            except ValueError:
                pass
        r = await db.execute(stmt.limit(limit))
        out = []
        for ev in r.scalars().all():
            out.append(
                {
                    "id": ev.id,
                    "summary": ev.summary or ev.venue_name,
                    "start": ev.start_utc.isoformat() if ev.start_utc else ev.event_date.isoformat(),
                    "end": ev.end_utc.isoformat() if ev.end_utc else None,
                    "provider": ev.provider,
                    "provider_event_id": ev.provider_event_id,
                    "connection_id": ev.connection_id,
                    "location": ev.location,
                    "html_link": ev.html_link,
                    "citation": f"event:{ev.id}",
                }
            )
        sync_health = await _get_sync_health(db, user, "calendar")
        return {"events": out, "sync_health": sync_health}

    @staticmethod
    def _serialize_drive_file(f: DriveFile) -> dict[str, Any]:
        return {
            "id": f.id,
            "connection_id": f.connection_id,
            "name": f.name,
            "mime_type": f.mime_type,
            "size_bytes": f.size_bytes,
            "web_view_link": f.web_view_link,
            "modified_time": f.modified_time.isoformat() if f.modified_time else None,
            "has_text": bool(f.content_text),
            "citation": f"drive_file:{f.id}",
        }

    @staticmethod
    async def _tool_search_drive(db: AsyncSession, user: User, args: dict[str, Any]) -> dict[str, Any]:
        from sqlalchemy import or_

        from app.models.connector_connection import ConnectorConnection

        q = str(args.get("query") or "").strip()
        if not q:
            return {"error": "query required"}
        limit = max(1, min(25, int(args.get("limit") or 10)))
        like = f"%{q}%"
        stmt = (
            select(DriveFile)
            .join(ConnectorConnection, ConnectorConnection.id == DriveFile.connection_id)
            .where(
                ConnectorConnection.user_id == user.id,
                DriveFile.is_trashed.is_(False),
                or_(DriveFile.name.ilike(like), DriveFile.content_text.ilike(like)),
            )
            .order_by(DriveFile.modified_time.desc().nulls_last())
            .limit(limit)
        )
        r = await db.execute(stmt)
        sync_health = await _get_sync_health(db, user, "drive")
        return {
            "hits": [AgentService._serialize_drive_file(f) for f in r.scalars().all()],
            "sync_health": sync_health,
        }

    @staticmethod
    async def _tool_list_drive_files(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        """Enumerate the user's Drive/OneDrive files. Use when the artist asks
        an open-ended "what files do I have?" question with no search term."""
        from app.models.connector_connection import ConnectorConnection

        limit = max(1, min(50, int(args.get("limit") or 20)))
        stmt = (
            select(DriveFile)
            .join(ConnectorConnection, ConnectorConnection.id == DriveFile.connection_id)
            .where(
                ConnectorConnection.user_id == user.id,
                DriveFile.is_trashed.is_(False),
            )
            .order_by(DriveFile.modified_time.desc().nulls_last(), DriveFile.id.desc())
            .limit(limit)
        )
        if args.get("connection_id") is not None:
            stmt = stmt.where(DriveFile.connection_id == int(args["connection_id"]))
        if args.get("mime_type"):
            stmt = stmt.where(DriveFile.mime_type == str(args["mime_type"]))
        r = await db.execute(stmt)
        files = [AgentService._serialize_drive_file(f) for f in r.scalars().all()]
        sync_health = await _get_sync_health(db, user, "drive")
        if not files:
            # Distinguish "no Drive connected" from "connected but empty mirror"
            # so the model can guide the artist toward connecting Drive instead
            # of claiming the drive is empty.
            conn_r = await db.execute(
                select(ConnectorConnection.id).where(
                    ConnectorConnection.user_id == user.id,
                    ConnectorConnection.provider.in_(("google", "google_drive", "microsoft", "onedrive")),
                )
            )
            has_drive_connection = conn_r.first() is not None
            return {
                "files": [],
                "has_drive_connection": has_drive_connection,
                "sync_health": sync_health,
                "hint": (
                    "No drive files have been mirrored yet. The artist may need to connect Drive "
                    "via start_connector_setup / start_oauth_flow."
                    if not has_drive_connection
                    else "Drive is connected but no files have been synced yet."
                ),
            }
        return {"files": files, "count": len(files), "sync_health": sync_health}

    @staticmethod
    async def _tool_get_drive_file_text(db: AsyncSession, user: User, args: dict[str, Any]) -> dict[str, Any]:
        fid = int(args.get("file_id") or 0)
        if not fid:
            return {"error": "file_id required"}
        row = await db.get(DriveFile, fid)
        if not row:
            return {"found": False}
        if not row.content_text:
            try:
                from app.services.drive_sync_service import run_extract_text

                await run_extract_text(db, fid)
                await db.refresh(row)
            except Exception as exc:
                return {"found": True, "extracted": False, "error": str(exc)[:300]}
        return {
            "found": True,
            "extracted": bool(row.content_text),
            "name": row.name,
            "mime_type": row.mime_type,
            "text": (row.content_text or "")[:40_000],
            "web_view_link": row.web_view_link,
        }

    @staticmethod
    async def _insert_proposal(
        db: AsyncSession,
        user: User,
        run_id: int,
        kind: str,
        payload: dict[str, Any],
        summary: str,
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        ikey = (idempotency_key or "").strip()[:128] or None
        if ikey:
            r = await db.execute(
                select(PendingProposal).where(
                    PendingProposal.user_id == user.id,
                    PendingProposal.idempotency_key == ikey,
                    PendingProposal.status == "pending",
                )
            )
            existing = r.scalar_one_or_none()
            if existing:
                return {
                    "proposal_id": existing.id,
                    "kind": existing.kind,
                    "status": "pending",
                    "deduplicated": True,
                    "message": "Existing pending operation with the same idempotency key.",
                }
        prop = PendingProposal(
            user_id=user.id,
            run_id=run_id,
            idempotency_key=ikey,
            kind=kind,
            summary=summary[:500] if summary else None,
            status="pending",
            payload=payload,
        )
        db.add(prop)
        await db.flush()
        return {
            "proposal_id": prop.id,
            "kind": kind,
            "status": "pending",
            "message": "Proposal recorded. A human must approve it before it is executed.",
        }

    @staticmethod
    def _idem(args: dict[str, Any]) -> str | None:
        raw = args.get("idempotency_key")
        return str(raw).strip()[:128] if raw is not None and str(raw).strip() else None

    @staticmethod
    async def _tool_propose_create_deal(
        db: AsyncSession, user: User, run_id: int, args: dict[str, Any]
    ) -> dict[str, Any]:
        payload = {
            "contact_id": int(args["contact_id"]),
            "title": str(args["title"])[:255],
            "status": str(args.get("status") or "new"),
            "notes": args.get("notes"),
            "amount": args.get("amount"),
            "currency": args.get("currency"),
        }
        if payload["status"] not in ("new", "contacted", "negotiating", "won", "lost"):
            payload["status"] = "new"
        summary = f"Create deal: {payload['title']}"
        return await AgentService._insert_proposal(
            db, user, run_id, "create_deal", payload, summary, idempotency_key=AgentService._idem(args)
        )

    @staticmethod
    async def _tool_propose_update_deal(
        db: AsyncSession, user: User, run_id: int, args: dict[str, Any]
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"deal_id": int(args["deal_id"])}
        for key in ("title", "status", "amount", "currency", "notes"):
            if key in args and args[key] is not None:
                payload[key] = args[key]
        if len(payload) <= 1:
            return {"error": "no fields to update"}
        summary = f"Update deal #{payload['deal_id']}"
        return await AgentService._insert_proposal(
            db, user, run_id, "update_deal", payload, summary, idempotency_key=AgentService._idem(args)
        )

    @staticmethod
    async def _tool_propose_create_contact(
        db: AsyncSession, user: User, run_id: int, args: dict[str, Any]
    ) -> dict[str, Any]:
        payload = {
            "name": str(args["name"])[:255],
            "email": args.get("email"),
            "phone": args.get("phone"),
            "role": str(args.get("role") or "other"),
            "notes": args.get("notes"),
        }
        summary = f"Create contact: {payload['name']}"
        return await AgentService._insert_proposal(
            db, user, run_id, "create_contact", payload, summary, idempotency_key=AgentService._idem(args)
        )

    @staticmethod
    async def _tool_propose_update_contact(
        db: AsyncSession, user: User, run_id: int, args: dict[str, Any]
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"contact_id": int(args["contact_id"])}
        for key in ("name", "email", "phone", "role", "notes"):
            if key in args and args[key] is not None:
                payload[key] = args[key]
        if len(payload) <= 1:
            return {"error": "no fields to update"}
        summary = f"Update contact #{payload['contact_id']}"
        return await AgentService._insert_proposal(
            db, user, run_id, "update_contact", payload, summary, idempotency_key=AgentService._idem(args)
        )

    @staticmethod
    async def _tool_propose_create_event(
        db: AsyncSession, user: User, run_id: int, args: dict[str, Any]
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "venue_name": str(args["venue_name"])[:255],
            "event_date": str(args["event_date"]),
            "status": str(args.get("status") or "confirmed"),
        }
        if args.get("deal_id") is not None:
            payload["deal_id"] = int(args["deal_id"])
        if args.get("city") is not None:
            payload["city"] = str(args["city"])[:255]
        if args.get("notes") is not None:
            payload["notes"] = args.get("notes")
        summary = f"Create event: {payload['venue_name']} on {payload['event_date']}"
        return await AgentService._insert_proposal(
            db, user, run_id, "create_event", payload, summary, idempotency_key=AgentService._idem(args)
        )

    @staticmethod
    async def _tool_propose_update_event(
        db: AsyncSession, user: User, run_id: int, args: dict[str, Any]
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"event_id": int(args["event_id"])}
        for key in ("venue_name", "event_date", "deal_id", "city", "status", "notes"):
            if key in args and args[key] is not None:
                payload[key] = args[key]
        if len(payload) <= 1:
            return {"error": "no fields to update"}
        summary = f"Update event #{payload['event_id']}"
        return await AgentService._insert_proposal(
            db, user, run_id, "update_event", payload, summary, idempotency_key=AgentService._idem(args)
        )

    @staticmethod
    async def _tool_propose_connector_email_send(
        db: AsyncSession, user: User, run_id: int, args: dict[str, Any]
    ) -> dict[str, Any]:
        to_raw = args["to"]
        to_list = to_raw if isinstance(to_raw, list) else [str(to_raw)]
        payload = {
            "connection_id": int(args["connection_id"]),
            "to": [str(x) for x in to_list],
            "subject": str(args["subject"])[:998],
            "body": str(args["body"]),
            "content_type": str(args.get("content_type") or "text"),
        }
        summary = f"Send email: {payload['subject'][:80]}"
        return await AgentService._insert_proposal(
            db, user, run_id, "connector_email_send", payload, summary, idempotency_key=AgentService._idem(args)
        )

    @staticmethod
    async def _tool_propose_connector_calendar_create(
        db: AsyncSession, user: User, run_id: int, args: dict[str, Any]
    ) -> dict[str, Any]:
        payload = {
            "connection_id": int(args["connection_id"]),
            "summary": str(args.get("summary") or args.get("title") or "Event")[:500],
            "start_iso": str(args["start_iso"]),
            "end_iso": str(args["end_iso"]),
            "description": args.get("description"),
            "timezone": str(args.get("timezone") or "UTC"),
        }
        summary = f"Calendar: {payload['summary'][:80]}"
        return await AgentService._insert_proposal(
            db, user, run_id, "connector_calendar_create", payload, summary, idempotency_key=AgentService._idem(args)
        )

    @staticmethod
    async def _tool_propose_connector_file_upload(
        db: AsyncSession, user: User, run_id: int, args: dict[str, Any]
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "connection_id": int(args["connection_id"]),
            "path": str(args["path"])[:1024],
            "mime_type": str(args.get("mime_type") or "application/octet-stream"),
        }
        if args.get("content_base64"):
            payload["content_base64"] = str(args["content_base64"])
        elif args.get("content_text") is not None:
            payload["content_text"] = str(args["content_text"])
        else:
            return {"error": "content_text or content_base64 required"}
        summary = f"Upload file: {payload['path'][:80]}"
        return await AgentService._insert_proposal(
            db, user, run_id, "connector_file_upload", payload, summary, idempotency_key=AgentService._idem(args)
        )

    @staticmethod
    async def _tool_propose_connector_teams_message(
        db: AsyncSession, user: User, run_id: int, args: dict[str, Any]
    ) -> dict[str, Any]:
        payload = {
            "connection_id": int(args["connection_id"]),
            "team_id": str(args["team_id"]),
            "channel_id": str(args["channel_id"]),
            "body": str(args["body"]),
        }
        summary = "Teams channel message"
        return await AgentService._insert_proposal(
            db, user, run_id, "connector_teams_message", payload, summary, idempotency_key=AgentService._idem(args)
        )

    @staticmethod
    async def _tool_propose_connector_email_reply(
        db: AsyncSession, user: User, run_id: int, args: dict[str, Any]
    ) -> dict[str, Any]:
        thread_id = str(args.get("thread_id") or "").strip()
        if not thread_id:
            return {"error": "thread_id required"}
        to_raw = args.get("to")
        to_list: list[str]
        if to_raw:
            to_list = to_raw if isinstance(to_raw, list) else [str(to_raw)]
        else:
            # Default: reply to the sender of the last inbound message in this thread.
            r = await db.execute(
                select(Email)
                .where(Email.provider_thread_id == thread_id, Email.direction == "inbound")
                .order_by(Email.received_at.desc())
                .limit(1)
            )
            last = r.scalar_one_or_none()
            if not last or not last.sender_email:
                return {"error": "no inbound sender found in thread; provide `to` explicitly"}
            to_list = [last.sender_email]
        # Default subject = "Re: <last subject>".
        subject = args.get("subject")
        if not subject:
            r2 = await db.execute(
                select(Email)
                .where(Email.provider_thread_id == thread_id)
                .order_by(Email.received_at.desc())
                .limit(1)
            )
            last = r2.scalar_one_or_none()
            if last:
                subj = (last.subject or "").strip()
                subject = subj if subj.lower().startswith("re:") else f"Re: {subj}"[:998]
            else:
                subject = "Re:"
        payload = {
            "connection_id": int(args["connection_id"]),
            "to": [str(x) for x in to_list],
            "subject": str(subject)[:998],
            "body": str(args["body"]),
            "content_type": str(args.get("content_type") or "text"),
            "thread_id": thread_id,
            "in_reply_to": args.get("in_reply_to"),
        }
        summary = f"Reply in thread: {payload['subject'][:80]}"
        return await AgentService._insert_proposal(
            db, user, run_id, "connector_email_send", payload, summary, idempotency_key=AgentService._idem(args)
        )

    @staticmethod
    async def _tool_propose_connector_calendar_update(
        db: AsyncSession, user: User, run_id: int, args: dict[str, Any]
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "connection_id": int(args["connection_id"]),
            "event_id": str(args["event_id"]),
        }
        for k in ("summary", "description", "start_iso", "end_iso", "timezone"):
            if args.get(k) is not None:
                payload[k] = str(args[k])
        if len(payload) <= 2:
            return {"error": "no fields to update"}
        summary = f"Update calendar event {payload['event_id']}"
        return await AgentService._insert_proposal(
            db, user, run_id, "connector_calendar_update", payload, summary,
            idempotency_key=AgentService._idem(args),
        )

    @staticmethod
    async def _tool_propose_connector_calendar_delete(
        db: AsyncSession, user: User, run_id: int, args: dict[str, Any]
    ) -> dict[str, Any]:
        payload = {
            "connection_id": int(args["connection_id"]),
            "event_id": str(args["event_id"]),
        }
        return await AgentService._insert_proposal(
            db, user, run_id, "connector_calendar_delete", payload,
            f"Delete calendar event {payload['event_id']}",
            idempotency_key=AgentService._idem(args),
        )

    @staticmethod
    async def _tool_propose_connector_file_share(
        db: AsyncSession, user: User, run_id: int, args: dict[str, Any]
    ) -> dict[str, Any]:
        payload = {
            "connection_id": int(args["connection_id"]),
            "file_id": str(args["file_id"]),
            "email": str(args["email"]),
            "role": str(args.get("role") or "reader"),
        }
        if payload["role"] not in ("reader", "writer"):
            payload["role"] = "reader"
        return await AgentService._insert_proposal(
            db, user, run_id, "connector_file_share", payload,
            f"Share file {payload['file_id']} with {payload['email']} ({payload['role']})",
            idempotency_key=AgentService._idem(args),
        )

    _PROPOSAL_TOOL_METHODS: dict[str, str] = {
        # Internal-CRM proposals (legacy: create a pending row even though we now also
        # support an auto-apply variant). Kept for back-compat with prior agent prompts.
        "propose_create_deal": "_tool_propose_create_deal",
        "propose_update_deal": "_tool_propose_update_deal",
        "propose_create_contact": "_tool_propose_create_contact",
        "propose_update_contact": "_tool_propose_update_contact",
        "propose_create_event": "_tool_propose_create_event",
        "propose_update_event": "_tool_propose_update_event",
        # External-write proposals (always require approval).
        "propose_connector_email_send": "_tool_propose_connector_email_send",
        "propose_connector_calendar_create": "_tool_propose_connector_calendar_create",
        "propose_connector_file_upload": "_tool_propose_connector_file_upload",
        "propose_connector_teams_message": "_tool_propose_connector_teams_message",
        "propose_connector_email_reply": "_tool_propose_connector_email_reply",
        "propose_connector_calendar_update": "_tool_propose_connector_calendar_update",
        "propose_connector_calendar_delete": "_tool_propose_connector_calendar_delete",
        "propose_connector_file_share": "_tool_propose_connector_file_share",
    }

    # Auto-apply CRM tools — execute immediately (with UNDO) instead of creating a pending row.
    _AUTO_APPLY_TOOL_KIND: dict[str, str] = {
        "apply_create_contact": "create_contact",
        "apply_update_contact": "update_contact",
        "apply_create_deal": "create_deal",
        "apply_update_deal": "update_deal",
        "apply_create_event": "create_event",
        "apply_update_event": "update_event",
    }

    @staticmethod
    def _build_auto_apply_payload(kind: str, args: dict[str, Any]) -> tuple[dict[str, Any], str]:
        """Mirrors the payload normalization the proposal tools do, then returns (payload, summary)."""
        if kind == "create_contact":
            payload = {
                "name": str(args["name"])[:255],
                "email": args.get("email"),
                "phone": args.get("phone"),
                "role": str(args.get("role") or "other"),
                "notes": args.get("notes"),
            }
            return payload, f"Crear contacto: {payload['name']}"
        if kind == "update_contact":
            payload = {"contact_id": int(args["contact_id"])}
            for k in ("name", "email", "phone", "role", "notes"):
                if args.get(k) is not None:
                    payload[k] = args[k]
            return payload, f"Actualizar contacto #{payload['contact_id']}"
        if kind == "create_deal":
            payload = {
                "contact_id": int(args["contact_id"]),
                "title": str(args["title"])[:255],
                "status": str(args.get("status") or "new"),
                "notes": args.get("notes"),
                "amount": args.get("amount"),
                "currency": args.get("currency"),
            }
            if payload["status"] not in ("new", "contacted", "negotiating", "won", "lost"):
                payload["status"] = "new"
            return payload, f"Crear trato: {payload['title']}"
        if kind == "update_deal":
            payload = {"deal_id": int(args["deal_id"])}
            for k in ("title", "status", "amount", "currency", "notes"):
                if args.get(k) is not None:
                    payload[k] = args[k]
            return payload, f"Actualizar trato #{payload['deal_id']}"
        if kind == "create_event":
            payload = {
                "venue_name": str(args["venue_name"])[:255],
                "event_date": str(args["event_date"]),
                "status": str(args.get("status") or "confirmed"),
            }
            if args.get("deal_id") is not None:
                payload["deal_id"] = int(args["deal_id"])
            if args.get("city") is not None:
                payload["city"] = str(args["city"])[:255]
            if args.get("notes") is not None:
                payload["notes"] = args.get("notes")
            return payload, f"Crear evento: {payload['venue_name']} ({payload['event_date']})"
        if kind == "update_event":
            payload = {"event_id": int(args["event_id"])}
            for k in ("venue_name", "event_date", "deal_id", "city", "status", "notes"):
                if args.get(k) is not None:
                    payload[k] = args[k]
            return payload, f"Actualizar evento #{payload['event_id']}"
        return {}, kind

    @staticmethod
    async def _tool_auto_apply(
        db: AsyncSession,
        user: User,
        run_id: int,
        thread_id: int | None,
        agent_tool_name: str,
        args: dict[str, Any],
    ) -> dict[str, Any]:
        from app.services.auto_apply_service import auto_apply

        kind = AgentService._AUTO_APPLY_TOOL_KIND[agent_tool_name]
        payload, summary = AgentService._build_auto_apply_payload(kind, args)
        try:
            action = await auto_apply(
                db, user,
                kind=kind,
                payload=payload,
                summary=summary,
                run_id=run_id,
                thread_id=thread_id,
            )
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)[:300]}
        return {
            "executed_action_id": action.id,
            "kind": action.kind,
            "summary": action.summary,
            "entity_id": (action.result or {}).get("entity_id"),
            "reversible_until": action.reversible_until.isoformat() if action.reversible_until else None,
            "auto_applied": True,
        }

    @staticmethod
    async def _tool_list_automations(db: AsyncSession, user: User, args: dict[str, Any]) -> dict[str, Any]:
        from app.services.automation_lifecycle_service import automation_to_summary, list_automations

        rows = await list_automations(db, user)
        return {"automations": [automation_to_summary(r) for r in rows]}

    @staticmethod
    async def _tool_create_automation(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        from app.services.automation_lifecycle_service import (
            automation_to_summary,
            create_automation,
        )

        nl = str(args.get("instruction_natural_language") or "").strip()
        if not nl:
            return {"error": "instruction_natural_language is required"}
        rule = await create_automation(
            db, user,
            name=str(args.get("name") or nl)[:255],
            instruction_natural_language=nl,
            trigger=args.get("trigger"),
            conditions=args.get("conditions") if isinstance(args.get("conditions"), dict) else None,
            enabled=bool(args.get("enabled", True)),
            source="agent",
        )
        return {"ok": True, "automation": automation_to_summary(rule)}

    @staticmethod
    async def _tool_update_automation(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        from app.services.automation_lifecycle_service import (
            automation_to_summary,
            update_automation,
        )

        aid = args.get("automation_id")
        if aid is None:
            return {"error": "automation_id required"}
        rule = await update_automation(
            db, user,
            automation_id=int(aid),
            name=args.get("name"),
            instruction_natural_language=args.get("instruction_natural_language"),
            conditions=args.get("conditions") if isinstance(args.get("conditions"), dict) else None,
            enabled=args.get("enabled"),
        )
        if not rule:
            return {"error": "automation not found"}
        return {"ok": True, "automation": automation_to_summary(rule)}

    @staticmethod
    async def _tool_delete_automation(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        from app.services.automation_lifecycle_service import delete_automation

        aid = args.get("automation_id")
        if aid is None:
            return {"error": "automation_id required"}
        ok = await delete_automation(db, user, int(aid))
        return {"ok": ok}

    @staticmethod
    async def _tool_start_connector_setup(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        from app.services.connector_setup_service import start_setup

        return await start_setup(db, user, str(args.get("provider") or ""))

    @staticmethod
    async def _tool_submit_connector_credentials(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        from app.services.connector_setup_service import submit_credentials

        token = str(args.get("setup_token") or "").strip()
        cid = str(args.get("client_id") or "").strip()
        secret = str(args.get("client_secret") or "").strip()
        if not (token and cid and secret):
            return {"error": "setup_token, client_id and client_secret are required"}
        return await submit_credentials(
            db, user,
            setup_token=token,
            client_id=cid,
            client_secret=secret,
            redirect_uri=args.get("redirect_uri"),
            tenant=args.get("tenant"),
        )

    @staticmethod
    async def _tool_start_oauth_flow(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        from app.services.connector_setup_service import start_oauth

        return await start_oauth(
            db, user,
            provider=str(args.get("provider") or ""),
            service=str(args.get("service") or "all"),
        )

    @staticmethod
    async def _tool_list_connectors(db: AsyncSession, user: User, args: dict[str, Any]) -> dict[str, Any]:
        from app.models.connector_connection import ConnectorConnection

        r = await db.execute(
            select(ConnectorConnection).where(ConnectorConnection.user_id == user.id)
        )
        out = []
        for c in r.scalars().all():
            out.append(
                {
                    "id": c.id,
                    "provider": c.provider,
                    "label": c.label,
                    "status": (c.meta or {}).get("status"),
                }
            )
        return {"connectors": out}

    # ------------------------------------------------------------------
    # Tool dispatch (single source of truth for routing a model-issued
    # tool call to the matching internal handler). Used by ``run_agent``.
    # ------------------------------------------------------------------

    @staticmethod
    async def _dispatch_tool(
        db: AsyncSession,
        user: User,
        run_id: int,
        thread_id: int | None,
        call: ChatToolCall,
    ) -> tuple[dict[str, Any], PendingProposal | None]:
        """Execute one model-issued tool call.

        Returns ``(result_dict, pending_proposal_or_None)``. The result dict
        is what we feed back to the model (and persist as the tool step).
        ``pending_proposal_or_None`` is set when the call created a row in
        ``pending_proposals`` so the caller can include it in the response.
        """
        original_name = call.name
        raw_args = call.arguments if isinstance(call.arguments, dict) else {}

        tool_name = _resolve_tool_name(original_name)
        if tool_name is None:
            # We couldn't even fuzzy-match the name. Feed back a hard error
            # with the full list of valid names + the final_answer escape
            # hatch so the model has the information needed to recover.
            return (
                {
                    "error": f"unknown tool {original_name!r} — call rejected.",
                    "valid_tool_names": sorted(
                        EXECUTABLE_TOOL_NAMES | {FINAL_ANSWER_TOOL_NAME}
                    ),
                    "hint": (
                        "Your next tool call MUST use one of valid_tool_names "
                        "spelled EXACTLY. If no listed tool fits the artist's "
                        f"request, call {FINAL_ANSWER_TOOL_NAME!r} with a "
                        "natural-language reply explaining what you can do."
                    ),
                },
                None,
            )

        # The caller (run_agent) already records the canonical name and
        # normalized args in the agent step / role:"tool" message; here we
        # just need the normalized args to actually invoke the handler.
        args = _normalize_tool_args(tool_name, raw_args)

        try:
            if tool_name == "hybrid_rag_search":
                return (await AgentService._tool_rag(db, user, args), None)
            if tool_name == "get_entity":
                return (await AgentService._tool_get_entity(db, args), None)
            if tool_name == "search_emails":
                return (await AgentService._tool_search_emails(db, user, args), None)
            if tool_name == "get_thread":
                return (await AgentService._tool_get_thread(db, user, args), None)
            if tool_name == "list_calendar_events":
                return (await AgentService._tool_list_calendar_events(db, user, args), None)
            if tool_name == "search_drive":
                return (await AgentService._tool_search_drive(db, user, args), None)
            if tool_name == "list_drive_files":
                return (await AgentService._tool_list_drive_files(db, user, args), None)
            if tool_name == "get_drive_file_text":
                return (await AgentService._tool_get_drive_file_text(db, user, args), None)
            if tool_name == "list_connectors":
                return (await AgentService._tool_list_connectors(db, user, args), None)
            if tool_name == "list_automations":
                return (await AgentService._tool_list_automations(db, user, args), None)
            if tool_name == "create_automation":
                return (await AgentService._tool_create_automation(db, user, args), None)
            if tool_name == "update_automation":
                return (await AgentService._tool_update_automation(db, user, args), None)
            if tool_name == "delete_automation":
                return (await AgentService._tool_delete_automation(db, user, args), None)
            if tool_name == "start_connector_setup":
                return (await AgentService._tool_start_connector_setup(db, user, args), None)
            if tool_name == "submit_connector_credentials":
                return (await AgentService._tool_submit_connector_credentials(db, user, args), None)
            if tool_name == "start_oauth_flow":
                return (await AgentService._tool_start_oauth_flow(db, user, args), None)
            if tool_name in AgentService._AUTO_APPLY_TOOL_KIND:
                result = await AgentService._tool_auto_apply(
                    db, user, run_id, thread_id, tool_name, args
                )
                return (result, None)
            if tool_name in AgentService._PROPOSAL_TOOL_METHODS:
                method_name = AgentService._PROPOSAL_TOOL_METHODS[tool_name]
                handler = getattr(AgentService, method_name)
                result = await handler(db, user, run_id, args)
                prop_id = result.get("proposal_id") if isinstance(result, dict) else None
                if prop_id:
                    prop = await db.get(PendingProposal, int(prop_id))
                    return (result, prop)
                return (result, None)
        except Exception as exc:  # noqa: BLE001 — surface tool errors to the model
            return ({"error": str(exc)[:500]}, None)

        # Defensive: AGENT_TOOL_NAMES says it's known but no branch handled it.
        return ({"error": f"unhandled tool: {tool_name}"}, None)

    @staticmethod
    async def run_agent(
        db: AsyncSession,
        user: User,
        message: str,
        *,
        prior_messages: list[dict[str, str]] | None = None,
        thread_id: int | None = None,
        thread_context_hint: str | None = None,
    ) -> AgentRunRead:
        """Run one agent turn.

        ``prior_messages``: optional ``[{role, content}, ...]`` of previous user/assistant
          turns from the same chat thread (so multi-turn conversations are coherent).
        ``thread_id``: persisted on AgentRun so executed actions / proposals can route
          their inline cards back into the right chat thread.
        ``thread_context_hint``: a short system-injected context blurb such as
          ``"Conversación sobre Contacto #42 (Maria Lopez)"``.
        """
        settings_row = await UserAISettingsService.get_or_create(db, user)
        if settings_row.ai_disabled:
            run = AgentRun(
                user_id=user.id,
                status="failed",
                user_message=message,
                error="AI is disabled for this user",
            )
            db.add(run)
            await db.commit()
            await db.refresh(run)
            return AgentService._to_read(run, [], [])

        api_key = await UserAISettingsService.get_api_key(db, user)
        if provider_kind_requires_api_key(settings_row.provider_kind) and not api_key:
            run = AgentRun(
                user_id=user.id,
                status="failed",
                user_message=message,
                error="API key not configured",
            )
            db.add(run)
            await db.commit()
            await db.refresh(run)
            return AgentService._to_read(run, [], [])

        run = AgentRun(user_id=user.id, status="running", user_message=message)
        db.add(run)
        await db.flush()

        system_prompt = AGENT_SYSTEM
        if thread_context_hint:
            system_prompt = f"{AGENT_SYSTEM}\n\nThread context: {thread_context_hint.strip()}"

        conversation: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
        if prior_messages:
            conversation.extend(
                [
                    {"role": str(m.get("role") or "user"), "content": str(m.get("content") or "")}
                    for m in prior_messages
                    if m.get("content")
                ]
            )
        conversation.append({"role": "user", "content": message})

        step_idx = 0
        proposals_created: list[PendingProposal] = []
        # Carry the bound thread id on AgentRun for downstream surfaces (executed actions,
        # proactive notifications) without growing the AgentRun schema. Stored as a step.
        if thread_id is not None:
            db.add(
                AgentRunStep(
                    run_id=run.id,
                    step_index=0,
                    kind="meta",
                    name="thread",
                    payload={"thread_id": int(thread_id)},
                )
            )

        try:
            final_answer_text: str | None = None
            consecutive_unknown_turns = 0
            MAX_UNKNOWN_TURNS = 2
            # Soft budget for data-gathering tool calls before we FORCE the
            # model to terminate via final_answer. Small local models (Gemma
            # in particular) tend to keep issuing search queries forever
            # rather than recognising they have enough information; once we
            # exceed this many real tool calls without a final_answer, we
            # switch ``tool_choice`` to specifically require ``final_answer``
            # so the model is structurally forced to wrap up.
            data_tool_calls_made = 0
            DATA_TOOL_CALL_BUDGET = 4
            for _ in range(settings.agent_max_tool_steps):
                # Tool-palette strategy:
                #  - default: an INTENT-FILTERED palette derived from the
                #    artist's last message + tool_choice="required" so every
                #    turn ends in a tool call (data tool or final_answer).
                #    Filtering down the schema is critical for small models
                #    (Gemma, Qwen 2.5 small) which otherwise default to
                #    RLHF-baked-in names like ``google:search`` even when we
                #    advertise the right tool.
                #  - over-budget: SHRINK to ONLY final_answer so the model is
                #    structurally forced to terminate. We can't rely on
                #    OpenAI's specific-function tool_choice because Ollama
                #    silently ignores it for Gemma; restricting the tools
                #    array works on every provider we support.
                turn_tools = _select_tool_palette(message)
                turn_tool_choice: Any = "required"
                if data_tool_calls_made >= DATA_TOOL_CALL_BUDGET:
                    turn_tools = [
                        t
                        for t in turn_tools
                        if t["function"]["name"] == FINAL_ANSWER_TOOL_NAME
                    ] or [
                        t
                        for t in AGENT_TOOLS
                        if t["function"]["name"] == FINAL_ANSWER_TOOL_NAME
                    ]
                    # Also append a brief instruction so the model knows
                    # WHY the palette shrank and what it should do.
                    last_msg = conversation[-1] if conversation else {}
                    if last_msg.get("role") != "user" or "wrap up now" not in str(
                        last_msg.get("content", "")
                    ):
                        conversation.append(
                            {
                                "role": "user",
                                "content": (
                                    "You have gathered enough information. "
                                    "Wrap up now: call final_answer with your "
                                    "natural-language reply to the artist, in "
                                    "Spanish. Do not call any other tool."
                                ),
                            }
                        )

                response = await LLMClient.chat_with_tools(
                    api_key or "",
                    settings_row,
                    messages=conversation,
                    tools=turn_tools,
                    tool_choice=turn_tool_choice,
                    temperature=0.15,
                )
                step_idx += 1
                db.add(
                    AgentRunStep(
                        run_id=run.id,
                        step_index=step_idx,
                        kind="llm",
                        name="turn",
                        payload={
                            "content": (response.content or "")[:4000],
                            "tool_calls": [
                                {"name": tc.name, "arguments": tc.arguments}
                                for tc in response.tool_calls
                            ],
                        },
                    )
                )

                # tool_choice="required" should make this branch impossible,
                # but some providers (or models without tool-call support)
                # may still return text-only. Treat that as a "lazy text"
                # answer and complete the run with the content so the artist
                # at least sees something useful.
                if not response.has_tool_calls:
                    fallback = (response.content or "").strip()
                    if fallback:
                        run.assistant_reply = fallback
                        run.status = "completed"
                    else:
                        # Empty content AND no tool call — nudge once.
                        conversation.append(_assistant_message_from(response))
                        conversation.append(
                            {
                                "role": "user",
                                "content": (
                                    "You returned an empty reply with no tool call. "
                                    "Call a tool from the provided list — at minimum, "
                                    "call final_answer with your reply text."
                                ),
                            }
                        )
                        continue
                    break

                conversation.append(_assistant_message_from(response))

                # Execute every tool call in order. If we hit final_answer
                # at any point in this batch, that becomes the run's reply
                # and we terminate (after still recording any sibling tool
                # results so the run history is complete).
                turn_had_real_call = False
                turn_had_unknown_call = False
                for call in response.tool_calls:
                    # Resolve aliases up front so both the final_answer branch
                    # and the dispatcher see the canonical name. ChatToolCall
                    # is frozen, so we track the canonical name/args alongside
                    # the original ``call`` instead of mutating it.
                    resolved = _resolve_tool_name(call.name)
                    canonical_name = resolved or (call.name or "unknown")
                    canonical_args = _normalize_tool_args(
                        resolved or "", call.arguments or {}
                    )
                    if resolved == FINAL_ANSWER_TOOL_NAME:
                        text = str(canonical_args.get("text") or "").strip()
                        citations = canonical_args.get("citations") or []
                        if not text:
                            tool_result: dict[str, Any] = {
                                "error": "final_answer requires a non-empty 'text' field"
                            }
                            turn_had_unknown_call = True
                        else:
                            if isinstance(citations, list) and citations:
                                cite_txt = ", ".join(str(c) for c in citations)
                                final_answer_text = f"{text}\n\n— {cite_txt}"
                            else:
                                final_answer_text = text
                            tool_result = {"ok": True}
                            turn_had_real_call = True
                        result, prop = tool_result, None
                    else:
                        result, prop = await AgentService._dispatch_tool(
                            db, user, run.id, thread_id, call
                        )
                        if (
                            isinstance(result, dict)
                            and "valid_tool_names" in result
                            and "error" in result
                        ):
                            turn_had_unknown_call = True
                        else:
                            turn_had_real_call = True
                            data_tool_calls_made += 1
                    if prop is not None:
                        proposals_created.append(prop)
                    step_idx += 1
                    db.add(
                        AgentRunStep(
                            run_id=run.id,
                            step_index=step_idx,
                            kind="tool",
                            name=canonical_name,
                            payload={"args": canonical_args, "result": result},
                        )
                    )
                    conversation.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "name": canonical_name,
                            "content": json.dumps(result, ensure_ascii=False)[:12000],
                        }
                    )

                if final_answer_text is not None:
                    run.assistant_reply = final_answer_text
                    run.status = "completed"
                    break

                # Loop-breaker: if the model burns multiple consecutive turns
                # only producing unknown/invalid tool calls, abort gracefully
                # with a helpful synthesized reply rather than letting the
                # step budget exhaust silently. This was observed in the wild
                # with Gemma 3/4 on Ollama, which has a strong RLHF prior to
                # emit ``google:search`` and won't self-correct from the error.
                if turn_had_unknown_call and not turn_had_real_call:
                    consecutive_unknown_turns += 1
                else:
                    consecutive_unknown_turns = 0
                if consecutive_unknown_turns >= MAX_UNKNOWN_TURNS:
                    run.assistant_reply = (
                        "Lo siento, no logré entender bien qué necesitas. "
                        "¿Puedes reformular la pregunta o ser un poco más específico? "
                        "Por ejemplo: \"qué archivos tengo en Drive\", \"búscame el "
                        "rider de X\", \"qué correos tengo de Y\"."
                    )
                    run.status = "completed"
                    run.error = "loop_breaker: model failed to call a valid tool"
                    break

            else:
                run.status = "failed"
                run.error = "Step budget exceeded"

        except Exception as exc:
            run.status = "failed"
            run.error = str(exc)[:2000]

        run.updated_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(run)

        # After commit, ORM instances are expired; lazy loads raise MissingGreenlet in async.
        for p in proposals_created:
            await db.refresh(p)
        prop_reads = [proposal_to_read(p) for p in proposals_created]
        steps = await AgentService._load_steps(db, run.id)
        actions = await AgentService._load_executed_actions(db, run.id)
        return AgentService._to_read(run, steps, prop_reads, actions)

    @staticmethod
    async def _load_steps(db: AsyncSession, run_id: int) -> list[AgentStepRead]:
        result = await db.execute(
            select(AgentRunStep).where(AgentRunStep.run_id == run_id).order_by(AgentRunStep.step_index)
        )
        rows = result.scalars().all()
        return [AgentStepRead(step_index=s.step_index, kind=s.kind, name=s.name, payload=s.payload) for s in rows]

    @staticmethod
    async def _load_executed_actions(db: AsyncSession, run_id: int):
        from app.models.executed_action import ExecutedAction
        from app.schemas.agent import ExecutedActionRead

        r = await db.execute(
            select(ExecutedAction).where(ExecutedAction.run_id == run_id).order_by(ExecutedAction.id)
        )
        out: list[ExecutedActionRead] = []
        for a in r.scalars().all():
            out.append(
                ExecutedActionRead(
                    id=a.id,
                    kind=a.kind,
                    summary=a.summary,
                    status=a.status,
                    payload=dict(a.payload),
                    result=dict(a.result) if a.result else None,
                    reversible_until=a.reversible_until,
                    reversed_at=a.reversed_at,
                    created_at=a.created_at,
                )
            )
        return out

    @staticmethod
    def _to_read(
        run: AgentRun,
        steps: list[AgentStepRead],
        proposals: list[PendingProposalRead],
        executed_actions: list | None = None,
    ) -> AgentRunRead:
        return AgentRunRead(
            id=run.id,
            status=run.status,
            user_message=run.user_message,
            assistant_reply=run.assistant_reply,
            error=run.error,
            steps=steps,
            pending_proposals=proposals,
            executed_actions=executed_actions or [],
        )

    @staticmethod
    async def get_run(db: AsyncSession, user: User, run_id: int) -> AgentRunRead | None:
        run = await db.get(AgentRun, run_id)
        if not run or run.user_id != user.id:
            return None
        steps = await AgentService._load_steps(db, run.id)
        pr = await db.execute(
            select(PendingProposal).where(PendingProposal.run_id == run_id, PendingProposal.user_id == user.id)
        )
        props = [proposal_to_read(p) for p in pr.scalars().all()]
        actions = await AgentService._load_executed_actions(db, run.id)
        return AgentService._to_read(run, steps, props, actions)
