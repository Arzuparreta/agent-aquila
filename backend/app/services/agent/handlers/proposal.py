"""Proposal tool handlers — outbound actions requiring human approval."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pending_proposal import PendingProposal
from app.models.user import User


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
        "message": "Proposal recorded. The user must approve it before it is executed.",
    }


def _idem(args: dict[str, Any]) -> str | None:
    raw = args.get("idempotency_key")
    return str(raw).strip()[:128] if raw is not None and str(raw).strip() else None


# ---------------------------------------------------------------------------
# Email proposals
# ---------------------------------------------------------------------------

async def _tool_propose_email_send(
    db: AsyncSession, user: User, run_id: int, args: dict[str, Any],
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
    return await _insert_proposal(
        db, user, run_id, "email_send", payload,
        f"Send email: {payload['subject'][:80]}",
        idempotency_key=_idem(args),
    )


async def _tool_propose_email_reply(
    db: AsyncSession, user: User, run_id: int, args: dict[str, Any],
) -> dict[str, Any]:
    thread_id = str(args.get("thread_id") or "").strip()
    if not thread_id:
        return {"error": "thread_id required"}
    to_raw = args.get("to")
    to_list: list[str] | None = None
    if to_raw:
        to_list = to_raw if isinstance(to_raw, list) else [str(to_raw)]
    if not to_list:
        return {
            "error": "no `to` provided. Call gmail_get_thread first and pass the sender as `to`."
        }
    payload = {
        "connection_id": int(args["connection_id"]),
        "to": [str(x) for x in to_list],
        "subject": str(args.get("subject") or "")[:998],
        "body": str(args["body"]),
        "content_type": str(args.get("content_type") or "text"),
        "thread_id": thread_id,
        "in_reply_to": args.get("in_reply_to"),
    }
    return await _insert_proposal(
        db, user, run_id, "email_reply", payload,
        f"Reply in thread: {payload['subject'][:80] or thread_id}",
        idempotency_key=_idem(args),
    )


# ---------------------------------------------------------------------------
# WhatsApp proposal
# ---------------------------------------------------------------------------

async def _tool_propose_whatsapp_send(
    db: AsyncSession, user: User, run_id: int, args: dict[str, Any],
) -> dict[str, Any]:
    to_e164 = str(args.get("to_e164") or "").strip()
    if not to_e164:
        return {"error": "to_e164 is required (E.164, e.g. +34600111222)."}
    tname = (args.get("template_name") or "").strip() or None
    tlang = str(args.get("template_language") or "en")
    body = str(args.get("body") or "")
    if not tname and not body.strip():
        return {
            "error": "Provide `body` for session text, or `template_name` for outside the 24h window.",
        }
    payload = {
        "connection_id": int(args["connection_id"]),
        "to_e164": to_e164,
        "body": body if not tname else "",
        "template_name": tname,
        "template_language": tlang,
    }
    return await _insert_proposal(
        db, user, run_id, "whatsapp_send", payload,
        f"WhatsApp → {to_e164[:40]}",
        idempotency_key=_idem(args),
    )


# ---------------------------------------------------------------------------
# Slack proposal
# ---------------------------------------------------------------------------

async def _tool_propose_slack_post_message(
    db: AsyncSession, user: User, run_id: int, args: dict[str, Any],
) -> dict[str, Any]:
    channel = str(args.get("channel_id") or "").strip()
    if not channel:
        return {"error": "channel_id is required (from slack_list_conversations)"}
    text = str(args.get("text") or "").strip()
    if not text:
        return {"error": "text is required"}
    payload: dict[str, Any] = {
        "connection_id": int(args["connection_id"]),
        "channel_id": channel,
        "text": text[:4000],
    }
    if args.get("thread_ts"):
        payload["thread_ts"] = str(args["thread_ts"]).strip()
    return await _insert_proposal(
        db, user, run_id, "slack_post", payload,
        f"Slack post → {channel[:40]}",
        idempotency_key=_idem(args),
    )


# ---------------------------------------------------------------------------
# Linear proposal
# ---------------------------------------------------------------------------

async def _tool_propose_linear_create_comment(
    db: AsyncSession, user: User, run_id: int, args: dict[str, Any],
) -> dict[str, Any]:
    iid = str(args.get("issue_id") or "").strip()
    if not iid:
        return {"error": "issue_id is required"}
    body = str(args.get("body") or "").strip()
    if not body:
        return {"error": "body is required"}
    payload = {
        "connection_id": int(args["connection_id"]),
        "issue_id": iid,
        "body": body[:20000],
    }
    return await _insert_proposal(
        db, user, run_id, "linear_comment", payload,
        f"Linear comment → {iid[:40]}",
        idempotency_key=_idem(args),
    )


# ---------------------------------------------------------------------------
# Telegram proposal
# ---------------------------------------------------------------------------

async def _tool_propose_telegram_send_message(
    db: AsyncSession, user: User, run_id: int, args: dict[str, Any],
) -> dict[str, Any]:
    text = str(args.get("text") or "").strip()
    if not text:
        return {"error": "text is required"}
    cid = args.get("chat_id")
    if cid is None:
        return {"error": "chat_id is required"}
    payload = {
        "connection_id": int(args["connection_id"]),
        "chat_id": cid,
        "text": text[:4096],
    }
    return await _insert_proposal(
        db, user, run_id, "telegram_message", payload,
        f"Telegram → {str(cid)[:40]}",
        idempotency_key=_idem(args),
    )
