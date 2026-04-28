from __future__ import annotations
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.connector_connection import ConnectorConnection
from app.models.user import User

# From agent_service.py (Phase 5 refactor)

read_allowed_workspace_file,
)
from app.services.ai_providers import provider_kind_requires_api_key
from app.services.connector_tool_registry import (
CALENDAR_TOOL_PROVIDERS,
DISCORD_TOOL_PROVIDERS,
DOCS_TOOL_PROVIDERS,
DRIVE_TOOL_PROVIDERS,
GITHUB_TOOL_PROVIDERS,
GMAIL_TOOL_PROVIDERS,
GRAPH_CALENDAR_TOOL_PROVIDERS,
ICLOUD_TOOL_PROVIDERS,
LINEAR_TOOL_PROVIDERS,
NOTION_TOOL_PROVIDERS,
OUTLOOK_MAIL_TOOL_PROVIDERS,
PEOPLE_TOOL_PROVIDERS,
SHEETS_TOOL_PROVIDERS,
SLACK_TOOL_PROVIDERS,
TASKS_TOOL_PROVIDERS,

    row = await _resolve_connection(db, user, args, NOTION_TOOL_PROVIDERS, label="Notion")
    client = await _notion_client(db, row)
    return await client.search(
        str(args.get("query") or ""),
        page_size=int(args.get("page_size") or 20),
    )

@staticmethod
async def _tool_notion_get_page(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    row = await _resolve_connection(db, user, args, NOTION_TOOL_PROVIDERS, label="Notion")
    client = await _notion_client(db, row)
    return await client.get_page(str(args["page_id"]))

@staticmethod
async def _tool_telegram_get_me(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    row = await _resolve_connection(db, user, args, TELEGRAM_TOOL_PROVIDERS, label="Telegram")
    client = await _telegram_client(db, row)
    return await client.get_me()

@staticmethod
async def _tool_telegram_get_updates(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    row = await _resolve_connection(db, user, args, TELEGRAM_TOOL_PROVIDERS, label="Telegram")
    client = await _telegram_client(db, row)
    off = args.get("offset")
    return await client.get_updates(
        offset=int(off) if off is not None else None,
        limit=int(args.get("limit") or 40),
    )

@staticmethod
async def _tool_telegram_send_message(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    """Send a Telegram message immediately (auto-apply, no approval needed)."""
    text = str(args.get("text") or "").strip()
    if not text:
        return {"error": "text is required"}
    cid = args.get("chat_id")
    if cid is None:
        return {"error": "chat_id is required"}
    row = await _resolve_connection(db, user, args, TELEGRAM_TOOL_PROVIDERS, label="Telegram")

async def _tool_list_skills(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    del db, user, args
    return {
        "skills": [
            {"slug": s.slug, "title": s.title, "summary": s.summary}
            for s in _list_skills()
        ]
    }

@staticmethod
async def _tool_load_skill(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    del db, user
    s = _load_skill(str(args.get("slug") or ""))
    if not s:
        return {"found": False}
    return {
        "found": True,
        "slug": s.slug,
        "title": s.title,
        "summary": s.summary,
        "body": s.body,
        "metadata": s.metadata,
    }

@staticmethod
async def _tool_list_workspace_files(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    del db, user, args
    files = list_allowed_workspace_files(skills_root=_skills_dir())
    return {"files": files}

@staticmethod
async def _tool_read_workspace_file(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    del db, user
    path = str(args.get("path") or "")
    raw = read_allowed_workspace_file(path, skills_root=_skills_dir())
    if raw is None:
        return {"error": "file_not_found_or_not_allowed", "path": path}
    return {"path": path, "content": raw}

@staticmethod
@staticmethod
async def _tool_list_connectors(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    del args
    from app.services.connector_service import ConnectorService

    rows = await ConnectorService.list_connections(db, user)
    return {
        "connectors": [
            {
                "id": ConnectorService.to_read(c).id,
                "provider": c.provider,
                "label": c.label,
                "needs_reauth": ConnectorService.to_read(c).needs_reauth,
                "missing_scopes": ConnectorService.to_read(c).missing_scopes,
            }
            for c in rows
        ]
    }

@staticmethod
async def _tool_get_session_time(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    del args
    prefs = await UserAISettingsService.get_or_create(db, user)
    return session_time_result(
        user_timezone=getattr(prefs, "user_timezone", None),
        time_format=getattr(prefs, "time_format", None) or "auto",
    )

@staticmethod
async def _tool_web_search(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    del db, user

    if not bool(settings.web_search_enabled):
        return {"error": "web_search is disabled by server config"}
    query = str(args.get("query") or "").strip()
    if not query:
        return {"error": "query is required"}
    max_results = min(
        max(int(args.get("max_results") or settings.web_search_max_results or 8), 1),
        20,
    )
    client = WebSearchClient()
    return await client.search(query, max_results=max_results)

@staticmethod
async def _tool_web_fetch(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    del db, user
    if not bool(settings.web_search_enabled):
        return {"error": "web_search/web_fetch is disabled by server config"}
    url = str(args.get("url") or "").strip()
    if not url:
        return {"error": "url is required"}
    max_chars_raw = args.get("max_chars")
    max_chars = int(max_chars_raw) if max_chars_raw is not None else None
    client = WebSearchClient()
    return await client.fetch_url(url, max_chars=max_chars)

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
        db,
        user,

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

    ctx = _agent_ctx.get()
    redirect_base = (ctx.get("oauth_redirect_base") or "") if ctx else ""

    return await start_oauth(
        db,
        user,
        provider=str(args.get("provider") or ""),
        service=str(args.get("service") or "all"),
        redirect_base=redirect_base,
    )

@staticmethod
async def _tool_scheduled_task_create(
    db: AsyncSession, user: User, args: dict[str, Any]

) -> dict[str, Any]:
    name = str(args.get("name") or "").strip()
    instruction = str(args.get("instruction") or "").strip()
    schedule_type = str(args.get("schedule_type") or "").strip().lower()
    if not name or not instruction:
        return {"error": "name and instruction are required"}
    prefs = await UserAISettingsService.get_or_create(db, user)
    user_timezone = getattr(prefs, "user_timezone", None)
    scheduled_at = None
    if args.get("scheduled_at"):
        from dateutil.parser import parse as parse_dt
        from zoneinfo import ZoneInfo
        from app.services.user_time_context import resolve_user_zone
        raw_scheduled = str(args.get("scheduled_at"))
        scheduled_at = parse_dt(raw_scheduled)
        if scheduled_at.tzinfo is None:
            if user_timezone:
                user_zone = resolve_user_zone(user_timezone)
                scheduled_at = scheduled_at.replace(tzinfo=user_zone)
            else:
                scheduled_at = scheduled_at.replace(tzinfo=UTC)
        scheduled_at = scheduled_at.astimezone(UTC)

    source_channel = _agent_ctx.get().get("source_channel")
    try:
        task = await ScheduledTaskService.create_task(
            db,
            user,
            name=name,
            instruction=instruction,
            schedule_type=schedule_type,
            timezone=args.get("timezone"),
            interval_minutes=args.get("interval_minutes"),
            hour_local=args.get("hour_local"),
            minute_local=args.get("minute_local"),
            cron_expr=args.get("cron_expr"),
            rrule_expr=args.get("rrule_expr"),
            weekdays=args.get("weekdays") if isinstance(args.get("weekdays"), list) else None,
            scheduled_at=scheduled_at,
            enabled=bool(args.get("enabled", True)),
            source_channel=source_channel,
        )
        await db.commit()
        await db.refresh(task)
        return {"task": AgentService._scheduled_task_to_dict(task)}
    except ValueError as exc:
        await db.rollback()
        return {"error": str(exc)}

@staticmethod
async def _tool_scheduled_task_list(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    tasks = await ScheduledTaskService.list_tasks(
        db, user, enabled_only=bool(args.get("enabled_only", False))
    )
    return {"tasks": [AgentService._scheduled_task_to_dict(t) for t in tasks]}

@staticmethod
async def _tool_scheduled_task_update(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    tid_raw = args.get("task_id")
    try:
        tid = int(tid_raw)
    except (TypeError, ValueError):
        return {"error": "task_id is required"}
    task = await db.get(ScheduledTask, tid)
    if task is None or task.user_id != user.id:
        return {"error": "task_not_found"}
    if "name" in args:
        task.name = str(args.get("name") or "").strip()[:255] or task.name
    if "instruction" in args:
        instr = str(args.get("instruction") or "").strip()
        if instr:
            task.instruction = instr
    if "enabled" in args:
        task.enabled = bool(args.get("enabled"))

    schedule_fields = {
        k: args.get(k)
        for k in (
            "schedule_type",

            "timezone",
            "interval_minutes",
            "hour_local",
            "minute_local",
            "cron_expr",
            "rrule_expr",
            "weekdays",
            "scheduled_at",
        )
        if k in args
    }
    if schedule_fields:
        try:
            from dateutil.parser import parse as parse_dt
            scheduled_at_arg = None
            if schedule_fields.get("scheduled_at") is not None:
                scheduled_at_arg = parse_dt(str(schedule_fields.get("scheduled_at")))
                if scheduled_at_arg.tzinfo is None:
                    scheduled_at_arg = scheduled_at_arg.replace(tzinfo=UTC)
            normalized = ScheduledTaskService.normalize_schedule(
                schedule_type=str(schedule_fields.get("schedule_type") or task.schedule_type),
                timezone=(
                    str(schedule_fields.get("timezone"))
                    if schedule_fields.get("timezone") is not None
                    else task.timezone
                ),
                interval_minutes=(
                    int(schedule_fields.get("interval_minutes"))
                    if schedule_fields.get("interval_minutes") is not None
                    else task.interval_minutes
                ),
                hour_local=(
                    int(schedule_fields.get("hour_local"))
                    if schedule_fields.get("hour_local") is not None
                    else task.hour_local
                ),
                minute_local=(
                    int(schedule_fields.get("minute_local"))
                    if schedule_fields.get("minute_local") is not None
                    else task.minute_local
                ),
                cron_expr=(
                    str(schedule_fields.get("cron_expr"))
                    if schedule_fields.get("cron_expr") is not None
                    else task.cron_expr
                ),
                rrule_expr=(
                    str(schedule_fields.get("rrule_expr"))
                    if schedule_fields.get("rrule_expr") is not None
                    else task.rrule_expr
                ),
                weekdays=(
                    schedule_fields.get("weekdays")
                    if isinstance(schedule_fields.get("weekdays"), list)
                    else task.weekdays
                ),
                scheduled_at=scheduled_at_arg if scheduled_at_arg is not None else task.scheduled_at,
            )
        except (TypeError, ValueError) as exc:
            await db.rollback()
            return {"error": str(exc)}
        task.schedule_type = normalized["schedule_type"]
        task.timezone = normalized["timezone"]
        task.interval_minutes = normalized["interval_minutes"]
        task.hour_local = normalized["hour_local"]
        task.minute_local = normalized["minute_local"]
        task.cron_expr = normalized["cron_expr"]
        task.rrule_expr = normalized["rrule_expr"]
        task.weekdays = normalized["weekdays"]
        task.scheduled_at = normalized.get("scheduled_at")
        task.next_run_at = ScheduledTaskService.compute_next_run(now_utc=datetime.now(UTC), task=task)
    await db.commit()
    await db.refresh(task)
    return {"task": AgentService._scheduled_task_to_dict(task)}

@staticmethod
async def _tool_scheduled_task_delete(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    tid_raw = args.get("task_id")
    try:
        tid = int(tid_raw)
    except (TypeError, ValueError):
        return {"error": "task_id is required"}
    task = await db.get(ScheduledTask, tid)
    if task is None or task.user_id != user.id:
        return {"error": "task_not_found"}
    await db.delete(task)
    await db.commit()
    return {"ok": True, "deleted_task_id": tid}

# ------------------------------------------------------------------
# Proposal tools (email / WhatsApp / YouTube upload — human approval)
# ------------------------------------------------------------------
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
        "message": "Proposal recorded. The user must approve it before it is executed.",
    }

@staticmethod
def _idem(args: dict[str, Any]) -> str | None:
    raw = args.get("idempotency_key")
    return str(raw).strip()[:128] if raw is not None and str(raw).strip() else None

@staticmethod
async def _tool_propose_email_send(
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
    return await AgentService._insert_proposal(
        db,
        user,
        run_id,
        "email_send",
        payload,
        f"Send email: {payload['subject'][:80]}",
        idempotency_key=AgentService._idem(args),
    )

@staticmethod
async def _tool_propose_email_reply(
    db: AsyncSession, user: User, run_id: int, args: dict[str, Any]
) -> dict[str, Any]:
    thread_id = str(args.get("thread_id") or "").strip()
    if not thread_id:
        return {"error": "thread_id required"}
    to_raw = args.get("to")
    to_list: list[str] | None = None
    if to_raw:
        to_list = to_raw if isinstance(to_raw, list) else [str(to_raw)]
    # If 'to' is omitted we leave it for the executor to derive from
    # the live thread headers; we no longer have a local Email mirror
    # to look up the last inbound sender, so the agent SHOULD include
    # ``to`` (or call ``gmail_get_thread`` first to discover it).
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
    return await AgentService._insert_proposal(
        db,
        user,
        run_id,
        "email_reply",
        payload,
        f"Reply in thread: {payload['subject'][:80] or thread_id}",
        idempotency_key=AgentService._idem(args),
    )

@staticmethod
async def _tool_propose_whatsapp_send(
    db: AsyncSession, user: User, run_id: int, args: dict[str, Any]
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
    return await AgentService._insert_proposal(
        db,
        user,
        run_id,
        "whatsapp_send",
        payload,
        f"WhatsApp → {to_e164[:40]}",
        idempotency_key=AgentService._idem(args),
    )

@staticmethod
@staticmethod
async def _tool_propose_slack_post_message(
    db: AsyncSession, user: User, run_id: int, args: dict[str, Any]
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
    return await AgentService._insert_proposal(
        db,
        user,
        run_id,
        "slack_post",
        payload,
        f"Slack post → {channel[:40]}",
        idempotency_key=AgentService._idem(args),
    )

@staticmethod
async def _tool_propose_linear_create_comment(
    db: AsyncSession, user: User, run_id: int, args: dict[str, Any]
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
    return await AgentService._insert_proposal(
        db,
        user,
        run_id,
        "linear_comment",
        payload,
        f"Linear comment → {iid[:40]}",
        idempotency_key=AgentService._idem(args),
    )

@staticmethod
async def _tool_propose_telegram_send_message(
    db: AsyncSession, user: User, run_id: int, args: dict[str, Any]
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
    return await AgentService._insert_proposal(
        db,
        user,
        run_id,
        "telegram_message",
        payload,
        f"Telegram → {str(cid)[:40]}",
        idempotency_key=AgentService._idem(args),
    )

@staticmethod
@staticmethod
async def _dispatch_tool(
    db: AsyncSession,
    user: User,
    run_id: int,
    thread_id: int | None,
    call: ChatToolCall,
) -> tuple[dict[str, Any], PendingProposal | None]:
    """Execute one model-issued tool call.

    Returns ``(result_dict, pending_proposal_or_None)``. The result is
    what we feed back to the model and persist as the tool step.
    """
    del thread_id  # not needed in the OpenClaw dispatcher (no auto-apply CRM)
    tool_name = call.name or ""
    args = call.arguments if isinstance(call.arguments, dict) else {}

    if tool_name not in AGENT_TOOL_NAMES:
        return ({"error": f"unknown tool {tool_name!r}"}, None)

    replay = _replay_ctx.get()
    if replay is not None:
        result = replay.next_tool_result()
        prop_id = result.get("proposal_id") if isinstance(result, dict) else None
        if prop_id:
            prop = await db.get(PendingProposal, int(prop_id))
            return (result, prop)
        return (result, None)

    entry = AgentService._DISPATCH.get(tool_name)
    if entry is None:
        return ({"error": f"unhandled tool: {tool_name}"}, None)
    handler_name, takes_run_id = entry
    handler = getattr(AgentService, handler_name)

    try:
        if takes_run_id:
            result = await handler(db, user, run_id, args)
        else:
            result = await handler(db, user, args)
    except ConnectorNeedsReauth as exc:
        return (
            {
                "error": "connector_needs_reauth",
                "connection_id": exc.connection_id,
                "provider": exc.provider,
                "message": str(exc),
            },
            None,
        )
    except OAuthError as exc:
        return ({"error": f"oauth_error: {exc}"}, None)
    except (
        GmailAPIError,
        CalendarAPIError,
        DriveAPIError,
        GraphAPIError,
        YoutubeAPIError,
        WhatsAppAPIError,
        GoogleTasksAPIError,
        GooglePeopleAPIError,
        GoogleSheetsAPIError,
        GoogleDocsAPIError,
        ICloudCalDAVError,
        GitHubAPIError,
        SlackAPIError,
        LinearAPIError,
        NotionAPIError,
        TelegramAPIError,
        DiscordAPIError,
        WebSearchAPIError,
    ) as exc:
        return ({"error": f"upstream {exc.status_code}: {exc.detail[:300]}"}, None)
    except Exception as exc:  # noqa: BLE001 — surface tool errors to the model
        return ({"error": str(exc)[:500]}, None)

    prop_id = result.get("proposal_id") if isinstance(result, dict) else None
    if prop_id:
        prop = await db.get(PendingProposal, int(prop_id))
        return (result, prop)
    return (result, None)

# ------------------------------------------------------------------
# Memory flush (OpenClaw-style, before thread compaction)
# ------------------------------------------------------------------
@staticmethod
async def run_agent_invalid_preflight(
    db: AsyncSession,
    user: User,
    message: str,
    *,
    thread_id: int | None = None,
) -> AgentRunRead | None:
    settings_row = await UserAISettingsService.get_or_create(db, user)
    if getattr(settings_row, "agent_processing_paused", False):
        run = AgentRun(
            user_id=user.id,
            status="failed",
            user_message=message,
            error="The agent is paused. Resume it from the dashboard (Settings).",
            chat_thread_id=thread_id,
        )
        db.add(run)
        await db.commit()
        await db.refresh(run)
        return AgentService._to_read(run, [], [])
    if settings_row.ai_disabled:
        run = AgentRun(
            user_id=user.id,
            status="failed",
            user_message=message,
            error="AI is disabled for this user",
            chat_thread_id=thread_id,
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
            chat_thread_id=thread_id,
        )
        db.add(run)
        await db.commit()
        await db.refresh(run)
        return AgentService._to_read(run, [], [])
    return None

@staticmethod
async def abort_pending_run_queue_unavailable(
    db: AsyncSession,
    *,
    run: AgentRun,
    placeholder_message: ChatMessage,
) -> AgentRunRead:
    """The worker queue could not take this run — never run the LLM in the HTTP handler.

    OpenClaw-style: agent turns are processed out-of-band. A failed enqueue means the
    infrastructure is down or misconfigured; we surface a clear system row instead
    of blocking the request (and tripping Next.js / reverse-proxy timeouts) or leaving
    a ``…`` placeholder row up forever.
    """
    err = (
        "Could not start the assistant: the job queue is unavailable. "

        "Ensure Redis and the ARQ worker are running and REDIS_URL is set."
    )
    run.status = "failed"
    run.error = err
    placeholder_message.role = "system"
    placeholder_message.content = err
    await db.commit()
    await db.refresh(run)
    await db.refresh(placeholder_message)
    return AgentService._to_read(run, [], [])


@staticmethod
async def create_pending_agent_run(
    db: AsyncSession,
    user: User,
    message: str,
    *,
    thread_id: int | None = None,
    turn_profile: str = TURN_PROFILE_USER_CHAT,
) -> AgentRun:
    root_trace = new_trace_id()
    run = AgentRun(
        user_id=user.id,
        status="pending",
        user_message=message,
        root_trace_id=root_trace,
        chat_thread_id=thread_id,
        turn_profile=normalize_turn_profile(turn_profile),
    )
    db.add(run)
    await db.flush()
    return run


@staticmethod
async def run_agent(
    db: AsyncSession,
    user: User,
    message: str,
    *,
    prior_messages: list[dict[str, str]] | None = None,
    thread_id: int | None = None,
    thread_context_hint: str | None = None,
    replay: AgentReplayContext | None = None,
    turn_profile: str | None = None,
    agent_ctx: dict[str, Any] | None = None,
) -> AgentRunRead:
    """Run one agent turn.

    ``prior_messages``: optional ``[{role, content}, ...]`` of previous user/assistant
      turns from the same chat thread (so multi-turn conversations are coherent).
    ``thread_id``: persisted on AgentRun so executed actions / proposals can route
      their inline cards back into the right chat thread.
    ``thread_context_hint``: a short system-injected context blurb such as
      ``"Conversation about thread #42"``.
    ``replay``: when set, non-``final_answer`` tools consume scripted results from
      :class:`~app.services.agent_replay.AgentReplayContext` (regression tests).
    ``turn_profile``: harness kind (``user_chat``, ``channel_inbound``, ``heartbeat``, etc.).
    ``agent_ctx``: optional dict of context passed to tool handlers (e.g. ``source_channel``).
    """

    early = await AgentService.run_agent_invalid_preflight(db, user, message, thread_id=thread_id)
    if early is not None:
        return early

    root_trace = new_trace_id()
    tpf = normalize_turn_profile(turn_profile)
    run = AgentRun(
        user_id=user.id,
        status="running",
        user_message=message,
        root_trace_id=root_trace,
        chat_thread_id=thread_id,
        turn_profile=tpf,
    )
    db.add(run)
    await db.flush()

    ctx_token = None
    if agent_ctx:
        ctx_token = _agent_ctx.set(agent_ctx)

    try:
        return await AgentService._execute_agent_loop(
            db,
            user,
            run,
            prior_messages=prior_messages,
            thread_context_hint=thread_context_hint,

            replay=replay,
        )
    finally:
        if ctx_token is not None:
            _agent_ctx.reset(ctx_token)

@staticmethod
async def _execute_agent_loop(
    db: AsyncSession,
    user: User,
    run: AgentRun,
    *,
    prior_messages: list[dict[str, str]] | None = None,
    thread_context_hint: str | None = None,
    replay: AgentReplayContext | None = None,
    tool_palette_override: list[dict[str, Any]] | None = None,
    system_prompt_override: str | None = None,
    max_tool_steps_override: int | None = None,
) -> AgentRunRead:
    message = run.user_message
    thread_id = run.chat_thread_id
    settings_row = await UserAISettingsService.get_or_create(db, user)
    rt = await resolve_for_user(db, user)
    api_key = await UserAISettingsService.get_api_key(db, user)
    tp = normalize_turn_profile(getattr(run, "turn_profile", None) or TURN_PROFILE_USER_CHAT)
    eff_max = resolve_max_tool_steps_for_turn(rt, tp)
    if max_tool_steps_override is not None:
        eff_max = int(max_tool_steps_override)
    turn_tools = (
        tool_palette_override

