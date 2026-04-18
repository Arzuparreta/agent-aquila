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

AGENT_SYSTEM = """You are an operations copilot for a live music and artist booking business (festivals, concerts, venues, promoters).
You help principals research the CRM and propose next actions. Never claim anything was created, sent, or changed unless a human approved it in the system.
Return ONLY valid JSON (no markdown, no code fences) with exactly this shape:
{"phase":"tool"|"answer","tool":null|string,"args":{},"reply":null|string,"citations":[]}

Rules:
- phase "tool" requires a non-null "tool" name and "args" object.
- phase "answer" requires a non-null "reply" string and "citations" as an array of strings like "deal:12" or "email:3".
- Read-only tools:
  - hybrid_rag_search — args: {"query": string, "limit_per_type": optional number 1-8, default 5}
  - get_entity — args: {"entity_type":"contact|email|deal|event","entity_id": number}
- Proposal tools (each creates a PENDING human approval only; nothing applies until approved):
  - propose_create_deal — {"contact_id": number, "title": string, "status": optional (new|contacted|negotiating|won|lost), "notes": optional, "amount": optional, "currency": optional}
  - propose_update_deal — {"deal_id": number, optional: title, status, amount, currency, notes}
  - propose_create_contact — {"name": string, optional: email, phone, role default "other", notes}
  - propose_update_contact — {"contact_id": number, optional: name, email, phone, role, notes}
  - propose_create_event — {"venue_name": string, "event_date": string ISO date YYYY-MM-DD, optional: deal_id, city, status default "confirmed", notes}
  - propose_update_event — {"event_id": number, optional: venue_name, event_date, deal_id, city, status, notes}
  - propose_connector_email_send — {"connection_id": number, "to": string or string[], "subject": string, "body": string, optional "content_type": "text"|"html"}
  - propose_connector_calendar_create — {"connection_id": number, "summary": string, "start_iso": string, "end_iso": string, optional "description", "timezone" default "UTC"}
  - propose_connector_file_upload — {"connection_id": number, "path": string, "mime_type": string, optional "content_text" or "content_base64"}
  - propose_connector_teams_message — {"connection_id": number, "team_id": string, "channel_id": string, "body": string}
- Optional on any proposal tool: "idempotency_key" (string, max 128 chars). Reuses an existing PENDING row with the same key instead of creating a duplicate.
- Prefer hybrid_rag_search before answering factual questions about the business.
- Be concise; operators are busy. Use the same language as the user when possible.
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

    _PROPOSAL_TOOL_METHODS: dict[str, str] = {
        "propose_create_deal": "_tool_propose_create_deal",
        "propose_update_deal": "_tool_propose_update_deal",
        "propose_create_contact": "_tool_propose_create_contact",
        "propose_update_contact": "_tool_propose_update_contact",
        "propose_create_event": "_tool_propose_create_event",
        "propose_update_event": "_tool_propose_update_event",
        "propose_connector_email_send": "_tool_propose_connector_email_send",
        "propose_connector_calendar_create": "_tool_propose_connector_calendar_create",
        "propose_connector_file_upload": "_tool_propose_connector_file_upload",
        "propose_connector_teams_message": "_tool_propose_connector_teams_message",
    }

    @staticmethod
    async def run_agent(db: AsyncSession, user: User, message: str) -> AgentRunRead:
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

        conversation: list[dict[str, str]] = [
            {"role": "system", "content": AGENT_SYSTEM},
            {"role": "user", "content": message},
        ]

        step_idx = 0
        proposals_created: list[PendingProposal] = []

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

        prop_reads = [proposal_to_read(p) for p in proposals_created]
        steps = await AgentService._load_steps(db, run.id)
        return AgentService._to_read(run, steps, prop_reads)

    @staticmethod
    async def _load_steps(db: AsyncSession, run_id: int) -> list[AgentStepRead]:
        result = await db.execute(
            select(AgentRunStep).where(AgentRunStep.run_id == run_id).order_by(AgentRunStep.step_index)
        )
        rows = result.scalars().all()
        return [AgentStepRead(step_index=s.step_index, kind=s.kind, name=s.name, payload=s.payload) for s in rows]

    @staticmethod
    def _to_read(run: AgentRun, steps: list[AgentStepRead], proposals: list[PendingProposalRead]) -> AgentRunRead:
        return AgentRunRead(
            id=run.id,
            status=run.status,
            user_message=run.user_message,
            assistant_reply=run.assistant_reply,
            error=run.error,
            steps=steps,
            pending_proposals=proposals,
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
        return AgentService._to_read(run, steps, props)
