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
from app.services.ai_providers import provider_kind_requires_api_key
from app.services.llm_client import LLMClient, parse_json_object
from app.services.proposal_service import proposal_to_read
from app.services.semantic_search_service import SemanticSearchService
from app.services.user_ai_settings_service import UserAISettingsService

AGENT_SYSTEM = """You are the artist's personal operations manager (live music: festivals, concerts, venues, promoters). The artist is NON-TECHNICAL — never mention APIs, OAuth, RAG, embeddings, JSON, model names, or any internal implementation. Speak like a friendly colleague.

You operate inside a chat app. The artist may be talking to you about a specific contact, deal, event or email (the thread title indicates this). When proactive notifications arrive ("Nuevo correo entrante de X"), you continue the conversation in that same thread.

Return ONLY valid JSON (no markdown, no code fences) with exactly this shape:
{"phase":"tool"|"answer","tool":null|string,"args":{},"reply":null|string,"citations":[]}

Rules:
- phase "tool" requires a non-null "tool" name and "args" object.
- phase "answer" requires a non-null "reply" string and "citations" as an array of strings like "deal:12" or "email:3".

Read-only tools:
  - hybrid_rag_search — args: {"query": string, "limit_per_type": optional number 1-8, default 5}
  - get_entity — args: {"entity_type":"contact|email|deal|event|drive_file|attachment","entity_id": number}
  - search_emails — args: {"query": optional, "direction": optional "inbound|outbound", "thread_id": optional, "connection_id": optional, "limit": optional 1-25}
  - get_thread — args: {"thread_id": string, "connection_id": optional}
  - list_calendar_events — args: {"start": optional ISO, "end": optional ISO, "connection_id": optional, "limit": optional 1-50}
  - search_drive — args: {"query": string, "limit": optional 1-25}
  - get_drive_file_text — args: {"file_id": number}  // triggers on-demand extraction if not yet cached
  - list_automations — args: {} — returns the artist's silently-learned rules
  - list_connectors — args: {} — returns Gmail/Outlook/Drive/Teams connection status

Auto-apply tools (no approval needed; the action runs immediately and the artist sees an UNDO option in chat):
  - apply_create_contact — {"name": string, optional email, phone, role default "other", notes}
  - apply_update_contact — {"contact_id": number, optional name, email, phone, role, notes}
  - apply_create_deal — {"contact_id": number, "title": string, optional status, amount, currency, notes}
  - apply_update_deal — {"deal_id": number, optional title, status, amount, currency, notes}
  - apply_create_event — {"venue_name": string, "event_date": YYYY-MM-DD, optional deal_id, city, status, notes}
  - apply_update_event — {"event_id": number, optional venue_name, event_date, deal_id, city, status, notes}
  - create_automation — {"name": string, "trigger": "email_received", "conditions": object, "instruction_natural_language": string} — silently learn a rule the artist just expressed in plain language ("nunca enviar correos a X", "siempre responder a venues con plantilla Y"). Do NOT ask permission; just record it and confirm verbally.
  - update_automation — {"automation_id": number, optional name, conditions, instruction_natural_language, enabled}
  - delete_automation — {"automation_id": number}
  - start_connector_setup — {"provider": "google"|"microsoft"} — emits a step-by-step setup card the artist follows in chat to connect Gmail/Outlook/Drive
  - submit_connector_credentials — {"setup_token": string, "client_id": string, "client_secret": string, optional "redirect_uri", optional "tenant"}
  - start_oauth_flow — {"provider": "google"|"microsoft", "service": "gmail"|"calendar"|"drive"|"outlook"|"teams"} — returns a URL the artist taps to grant access

Approval-required tools (these create a PENDING approval card; the artist taps Approve in chat):
  - propose_connector_email_send — {"connection_id": number, "to": string or string[], "subject": string, "body": string, optional "content_type": "text"|"html"}
  - propose_connector_email_reply — {"connection_id": number, "thread_id": string, optional in_reply_to, to, subject, "body": string, optional content_type}
  - propose_connector_calendar_create — {"connection_id": number, "summary": string, "start_iso": string, "end_iso": string, optional description, "timezone" default "UTC"}
  - propose_connector_calendar_update — {"connection_id": number, "event_id": string, optional summary, description, start_iso, end_iso, timezone}
  - propose_connector_calendar_delete — {"connection_id": number, "event_id": string}
  - propose_connector_file_upload — {"connection_id": number, "path": string, "mime_type": string, optional "content_text" or "content_base64"}
  - propose_connector_file_share — {"connection_id": number, "file_id": string, "email": string, optional "role": "reader"|"writer"}
  - propose_connector_teams_message — {"connection_id": number, "team_id": string, "channel_id": string, "body": string}

Behavior rules:
- Always reply in the same language the artist uses (default: Spanish).
- When the artist expresses a preference ("don't email X", "always CC bookings@..."), call create_automation IMMEDIATELY without asking. Then confirm verbally ("Hecho — no volveré a escribir a X.").
- Prefer hybrid_rag_search before answering factual questions. Cite ids in "citations".
- Be concise. The artist is busy.
- Optional on any tool: "idempotency_key" (string, max 128 chars).
"""

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
        return {"hits": hits}

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
        return {"events": out}

    @staticmethod
    async def _tool_search_drive(db: AsyncSession, user: User, args: dict[str, Any]) -> dict[str, Any]:
        from sqlalchemy import or_

        q = str(args.get("query") or "").strip()
        if not q:
            return {"error": "query required"}
        limit = max(1, min(25, int(args.get("limit") or 10)))
        like = f"%{q}%"
        stmt = (
            select(DriveFile)
            .where(or_(DriveFile.name.ilike(like), DriveFile.content_text.ilike(like)))
            .order_by(DriveFile.modified_time.desc().nulls_last())
            .limit(limit)
        )
        r = await db.execute(stmt)
        out = []
        for f in r.scalars().all():
            out.append(
                {
                    "id": f.id,
                    "name": f.name,
                    "mime_type": f.mime_type,
                    "size_bytes": f.size_bytes,
                    "web_view_link": f.web_view_link,
                    "modified_time": f.modified_time.isoformat() if f.modified_time else None,
                    "has_text": bool(f.content_text),
                    "citation": f"drive_file:{f.id}",
                }
            )
        return {"hits": out}

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
            for _ in range(settings.agent_max_tool_steps):
                raw = await LLMClient.chat_completion(
                    api_key or "",
                    settings_row,
                    messages=conversation,
                    temperature=0.15,
                    response_format_json=True,
                )
                step_idx += 1
                db.add(
                    AgentRunStep(
                        run_id=run.id,
                        step_index=step_idx,
                        kind="llm",
                        name="turn",
                        payload={"raw": raw[:8000]},
                    )
                )

                decision = parse_json_object(raw) or {}
                phase = str(decision.get("phase") or "").lower()

                if phase == "answer":
                    reply = str(decision.get("reply") or "").strip()
                    citations = decision.get("citations") or []
                    if citations:
                        cite_txt = ", ".join(str(c) for c in citations)
                        run.assistant_reply = f"{reply}\n\n— Sources: {cite_txt}"
                    else:
                        run.assistant_reply = reply
                    run.status = "completed"
                    break

                if phase != "tool":
                    run.status = "failed"
                    run.error = "Model returned an invalid phase"
                    break

                tool = decision.get("tool")
                args = decision.get("args") if isinstance(decision.get("args"), dict) else {}
                tool_name = str(tool or "")

                if tool_name == "hybrid_rag_search":
                    result = await AgentService._tool_rag(db, user, args)
                elif tool_name == "get_entity":
                    result = await AgentService._tool_get_entity(db, args)
                elif tool_name == "search_emails":
                    result = await AgentService._tool_search_emails(db, user, args)
                elif tool_name == "get_thread":
                    result = await AgentService._tool_get_thread(db, user, args)
                elif tool_name == "list_calendar_events":
                    result = await AgentService._tool_list_calendar_events(db, user, args)
                elif tool_name == "search_drive":
                    result = await AgentService._tool_search_drive(db, user, args)
                elif tool_name == "get_drive_file_text":
                    result = await AgentService._tool_get_drive_file_text(db, user, args)
                elif tool_name == "list_connectors":
                    result = await AgentService._tool_list_connectors(db, user, args)
                elif tool_name == "list_automations":
                    result = await AgentService._tool_list_automations(db, user, args)
                elif tool_name == "create_automation":
                    result = await AgentService._tool_create_automation(db, user, args)
                elif tool_name == "update_automation":
                    result = await AgentService._tool_update_automation(db, user, args)
                elif tool_name == "delete_automation":
                    result = await AgentService._tool_delete_automation(db, user, args)
                elif tool_name == "start_connector_setup":
                    result = await AgentService._tool_start_connector_setup(db, user, args)
                elif tool_name == "submit_connector_credentials":
                    result = await AgentService._tool_submit_connector_credentials(db, user, args)
                elif tool_name == "start_oauth_flow":
                    result = await AgentService._tool_start_oauth_flow(db, user, args)
                elif tool_name in AgentService._AUTO_APPLY_TOOL_KIND:
                    result = await AgentService._tool_auto_apply(
                        db, user, run.id, thread_id, tool_name, args
                    )
                elif tool_name in AgentService._PROPOSAL_TOOL_METHODS:
                    method_name = AgentService._PROPOSAL_TOOL_METHODS[tool_name]
                    handler = getattr(AgentService, method_name)
                    result = await handler(db, user, run.id, args)
                    prop_id = result.get("proposal_id") if isinstance(result, dict) else None
                    if prop_id:
                        prop = await db.get(PendingProposal, int(prop_id))
                        if prop:
                            proposals_created.append(prop)
                else:
                    result = {"error": f"unknown tool: {tool_name}"}

                step_idx += 1
                db.add(
                    AgentRunStep(
                        run_id=run.id,
                        step_index=step_idx,
                        kind="tool",
                        name=tool_name or "unknown",
                        payload={"args": args, "result": result},
                    )
                )

                conversation.append({"role": "assistant", "content": json.dumps(decision, ensure_ascii=False)})
                conversation.append(
                    {
                        "role": "user",
                        "content": f"Tool {tool_name} result:\n{json.dumps(result, ensure_ascii=False)[:12000]}",
                    }
                )

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
