"""Calendar tool handlers."""
from __future__ import annotations
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.connector_connection import ConnectorConnection
from app.models.user import User
from app.services.agent.runtime_clients import GoogleCalendarClient

    return conversation, False
reduced = list(conversation)
changed = False
# Keep system prompt + latest user turn, compact middle history first.
if len(reduced) > 2:
    head = reduced[:1]
    middle = reduced[1:-1]
    tail = reduced[-1:]
    dropped_count = max(0, len(middle) - 8)
    compact_middle = select_history_by_budget(
        history=[
            {"role": str(m.get("role") or "user"), "content": str(m.get("content") or "")}
            for m in middle
            if isinstance(m.get("content"), str)
        ],
        budget_tokens=max(256, input_budget_tokens - estimate_message_tokens(head + tail)),
        keep_tail_messages=4,
    )
    if dropped_count > 0:
        summary = {
            "role": "system",
            "content": (
                "Context compression summary:\n"
                f"- Active Task: Continue the current user request.\n"
                f"- Completed Actions: Earlier tool/assistant exchanges were compacted ({dropped_count} msgs).\n"
                "- Pending Requests: Prior unresolved asks remain in compacted history.\n"
                "- Constraints/Preferences: Preserve user constraints and provider/tool limitations.\n"
                "- Open Questions: None explicitly tracked."
            ),
        }
        reduced = head + [summary] + compact_middle + tail
    else:
        reduced = head + compact_middle + tail
    changed = True
# If still over budget, trim very large message contents.
while estimate_message_tokens(reduced) > input_budget_tokens and len(reduced) > 1:
    idx = 1
    candidate = reduced[idx]
    content = candidate.get("content")

    if not isinstance(content, str) or len(content) < 600:
        if len(reduced) > 3:
            reduced.pop(idx)
            changed = True
            continue
        break
    candidate = dict(candidate)
    candidate["content"] = clamp_tool_content_by_tokens(content, max(100, len(content) // 10))
    reduced[idx] = candidate
    changed = True
return reduced, changed


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


# ---------------------------------------------------------------------------
# Connection resolution
# ---------------------------------------------------------------------------


async def _resolve_connection(
db: AsyncSession,
user: User,
args: dict[str, Any],
providers: tuple[str, ...],
*,
label: str,
) -> ConnectorConnection:
"""Pick the connector connection a tool call should use.

Honour ``args["connection_id"]`` when present; otherwise auto-detect
the user's single matching connection. Returns a friendly-error
``RuntimeError`` (caught by the dispatcher) when the user has zero
or many connections of the requested type.
"""
cid = args.get("connection_id")
if cid is not None:
    row = await db.get(ConnectorConnection, int(cid))
    if not row or row.user_id != user.id:
        raise RuntimeError(f"connection {cid} not found")
    if row.provider not in providers:
        raise RuntimeError(f"connection {cid} is not a {label} connection")
    return row
stmt = (
    select(ConnectorConnection)
    .where(
        ConnectorConnection.user_id == user.id,
        ConnectorConnection.provider.in_(providers),
    )
    .order_by(ConnectorConnection.created_at.desc())
)
rows = list((await db.execute(stmt)).scalars().all())
if not rows:
    raise RuntimeError(f"no {label} connection — connect one in Settings → Connectors")

if len(rows) > 1:
    ids = ", ".join(str(r.id) for r in rows)
    raise RuntimeError(
        f"multiple {label} connections — pass `connection_id` (available: {ids})"
    )
return rows[0]


async def _gmail_client(db: AsyncSession, row: ConnectorConnection) -> GmailClient:
token = await TokenManager.get_valid_access_token(db, row)
return GmailClient(token)


async def _calendar_client(db: AsyncSession, row: ConnectorConnection) -> GoogleCalendarClient:
token = await TokenManager.get_valid_access_token(db, row)
return GoogleCalendarClient(token)


async def _drive_client(db: AsyncSession, row: ConnectorConnection) -> GoogleDriveClient:
token = await TokenManager.get_valid_access_token(db, row)
return GoogleDriveClient(token)


async def _youtube_client(db: AsyncSession, row: ConnectorConnection) -> YoutubeClient:

token = await TokenManager.get_valid_access_token(db, row)
return YoutubeClient(token)


async def _tasks_client(db: AsyncSession, row: ConnectorConnection) -> GoogleTasksClient:
token = await TokenManager.get_valid_access_token(db, row)
return GoogleTasksClient(token)


async def _people_client(db: AsyncSession, row: ConnectorConnection) -> GooglePeopleClient:
token = await TokenManager.get_valid_access_token(db, row)
return GooglePeopleClient(token)



async def _sheets_client(db: AsyncSession, row: ConnectorConnection) -> GoogleSheetsClient:
token = await TokenManager.get_valid_access_token(db, row)
return GoogleSheetsClient(token)


async def _docs_client(db: AsyncSession, row: ConnectorConnection) -> GoogleDocsClient:
token = await TokenManager.get_valid_access_token(db, row)
return GoogleDocsClient(token)


def _icloud_app_password_creds(row: ConnectorConnection) -> tuple[str, str, bool]:
creds = ConnectorService.decrypt_credentials(row)
user = str(creds.get("username") or creds.get("apple_id") or "").strip()
pw = str(creds.get("password") or creds.get("app_password") or "")
china = bool(creds.get("china_mainland"))
return user, pw, china

