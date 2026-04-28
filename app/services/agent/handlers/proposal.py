from __future__ import annotations
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.connector_connection import ConnectorConnection
from app.models.user import User

# From agent_service.py (Phase 5 refactor)

@staticmethod
@staticmethod
@staticmethod
async def _tool_device_list_ingested_files(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    return {
        "items": await DeviceIngestService.list_recent(
            db, user, limit=int(args.get("limit") or 50)
        )
    }

@staticmethod
async def _tool_device_get_ingested_file(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    return await DeviceIngestService.get_for_agent(
        db, user, int(args.get("ingest_id") or 0)
    )

@staticmethod
@staticmethod
@staticmethod

@staticmethod
@staticmethod
@staticmethod
@staticmethod
@staticmethod
@staticmethod
@staticmethod
@staticmethod
@staticmethod
@staticmethod
@staticmethod
@staticmethod
@staticmethod
async def _tool_outlook_list_messages(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    row = await _resolve_connection(db, user, args, OUTLOOK_MAIL_TOOL_PROVIDERS, label="Outlook")
    client = await _graph_client(db, row)
    return await client.messages_delta(top=int(args.get("top") or 25))

@staticmethod
async def _tool_outlook_get_message(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    row = await _resolve_connection(db, user, args, OUTLOOK_MAIL_TOOL_PROVIDERS, label="Outlook")
    client = await _graph_client(db, row)
    return await client.get_message(str(args["message_id"]))

@staticmethod
@staticmethod
@staticmethod
@staticmethod
async def _tool_upsert_memory(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    """Persist scratchpad memory; return structured errors instead of raising when args are bad.

    The model sees ``{"error": ...}`` in the tool channel — phrases like "problema técnico con

    la memoria" usually mean this path returned an error dict (DB issue, missing fields, etc.).
    """
    if not isinstance(args, dict):
        return {"error": "invalid_arguments", "detail": "expected a JSON object of arguments"}
    rk = args.get("key")
    rc = args.get("content")
    if rk is None or rc is None:
        return {
            "error": "missing_fields",
            "detail": "Provide non-empty 'key' and 'content' (strings).",
        }
    key = str(rk).strip()
    content = str(rc).strip()
    if not key or not content:
        return {
            "error": "empty_key_or_content",
            "detail": "key and content must be non-empty after trimming.",
        }
    imp = 0
    if args.get("importance") is not None:
        try:
            imp = max(0, min(10, int(args["importance"])))
        except (TypeError, ValueError):
            imp = 0
    tags_arg = args.get("tags")
    tags: list[str] | None = None
    if isinstance(tags_arg, list):
        tags = [str(x).strip() for x in tags_arg if str(x).strip()][:50] or None

    try:
        row = await AgentMemoryService.upsert(
            db,

            user,
            key=key,
            content=content,
            importance=imp,
            tags=tags,
        )
    except Exception as exc:  # noqa: BLE001 — surface a clear payload to the model + ops logs
        _logger_memory_tools.exception(
            "upsert_memory persist_failed user_id=%s key_prefix=%s",
            user.id,
            key[:80],
        )
        return {
            "error": "persist_failed",
            "detail": str(exc)[:400],
        }
    return {"ok": True, "key": row.key, "id": row.id}

@staticmethod
async def _tool_delete_memory(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    ok = await AgentMemoryService.delete(db, user, key=str(args["key"]))
    return {"ok": ok}

@staticmethod
async def _tool_list_memory(

    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    rows = await AgentMemoryService.list_for_user(
        db, user, limit=int(args.get("limit") or 50)
    )
    return {
        "memories": [
            {
                "key": r.key,
                "content": r.content,
                "importance": r.importance or 0,
                "tags": r.tags,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ]
    }

@staticmethod
async def _tool_recall_memory(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    hits = await AgentMemoryService.recall(
        db,
        user,

        query=(args.get("query") or None),
        tags=args.get("tags"),
        limit=int(args.get("limit") or 6),
    )
    return {"hits": hits}

@staticmethod
async def _tool_memory_get(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    key = str(args.get("key") or "").strip()
    if not key:
        return {"ok": False, "error": "key is required"}
    row = await AgentMemoryService.get(db, user, key=key)
    if not row:
        return {"ok": False, "error": "not_found", "key": key}
    return {
        "ok": True,
        "key": row.key,
        "content": row.content,
        "importance": row.importance or 0,
        "tags": row.tags,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }

@staticmethod

