from __future__ import annotations
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.connector_connection import ConnectorConnection
from app.models.user import User
from app.services.agent.runtime_clients import (
    GmailClient, GoogleCalendarClient, GoogleDriveClient,
    GoogleSheetsClient, GoogleDocsClient, GoogleTasksClient,
    GooglePeopleClient, GitHubClient, SlackClient,
    TelegramBotClient, DiscordBotClient, LinearClient,
    NotionClient, ICloudCalDAVClient, YoutubeClient,
    share_file, upload_file,
)
        return {"error": "either content_text or content_base64 is required"}
    return await upload_file(provider, creds, path, body, mime)

@staticmethod
@staticmethod
async def _tool_sheets_read_range(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    row = await _resolve_connection(db, user, args, SHEETS_TOOL_PROVIDERS, label="Google Sheets")
    client = await _sheets_client(db, row)
    return await client.get_values(str(args["spreadsheet_id"]), str(args["range"]))

@staticmethod
@staticmethod
async def _tool_docs_get_document(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    row = await _resolve_connection(db, user, args, DOCS_TOOL_PROVIDERS, label="Google Docs")
    client = await _docs_client(db, row)
    return await client.get_document(str(args["document_id"]))

# ------------------------------------------------------------------
# YouTube, Tasks, People, iCloud CalDAV
# ------------------------------------------------------------------
@staticmethod
@staticmethod
@staticmethod
@staticmethod
@staticmethod
@staticmethod
@staticmethod
async def _tool_tasks_list_tasklists(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    row = await _resolve_connection(db, user, args, TASKS_TOOL_PROVIDERS, label="Google Tasks")
    client = await _tasks_client(db, row)
    return await client.list_tasklists(page_token=args.get("page_token"))

@staticmethod
async def _tool_tasks_list_tasks(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    row = await _resolve_connection(db, user, args, TASKS_TOOL_PROVIDERS, label="Google Tasks")
    client = await _tasks_client(db, row)
    sc = args.get("show_completed")
    return await client.list_tasks(
        str(args["tasklist_id"]),
        page_token=args.get("page_token"),
        show_completed=bool(sc) if sc is not None else None,
        due_min=args.get("due_min"),
        due_max=args.get("due_max"),

        max_results=int(args.get("max_results") or 100),
    )

@staticmethod
async def _tool_tasks_create_task(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    row = await _resolve_connection(db, user, args, TASKS_TOOL_PROVIDERS, label="Google Tasks")
    client = await _tasks_client(db, row)

    body: dict[str, Any] = {"title": str(args["title"])}
    if args.get("notes") is not None:
        body["notes"] = str(args["notes"])
    if args.get("due"):
        body["due"] = str(args["due"])
    return await client.insert_task(str(args["tasklist_id"]), body)

@staticmethod
async def _tool_tasks_update_task(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    row = await _resolve_connection(db, user, args, TASKS_TOOL_PROVIDERS, label="Google Tasks")
    client = await _tasks_client(db, row)
    body: dict[str, Any] = {}
    if args.get("title") is not None:
        body["title"] = str(args["title"])
    if args.get("notes") is not None:
        body["notes"] = str(args["notes"])
    if args.get("status"):
        body["status"] = str(args["status"])
    if args.get("due"):
        body["due"] = str(args["due"])
    return await client.patch_task(str(args["tasklist_id"]), str(args["task_id"]), body)

@staticmethod
async def _tool_tasks_delete_task(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    row = await _resolve_connection(db, user, args, TASKS_TOOL_PROVIDERS, label="Google Tasks")
    client = await _tasks_client(db, row)
    return await client.delete_task(str(args["tasklist_id"]), str(args["task_id"]))

@staticmethod
async def _tool_people_search_contacts(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    row = await _resolve_connection(db, user, args, PEOPLE_TOOL_PROVIDERS, label="Google Contacts")
    client = await _people_client(db, row)
    return await client.search_contacts(
        str(args["query"]),
        page_token=args.get("page_token"),
        page_size=int(args.get("page_size") or 20),
    )

@staticmethod
async def _tool_github_list_my_repos(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    row = await _resolve_connection(db, user, args, GITHUB_TOOL_PROVIDERS, label="GitHub")
    client = await _github_client(db, row)
    items = await client.list_user_repos(
        page=int(args.get("page") or 1),
        per_page=int(args.get("per_page") or 30),
    )
    return {"repos": items}

@staticmethod
async def _tool_github_list_repo_issues(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    row = await _resolve_connection(db, user, args, GITHUB_TOOL_PROVIDERS, label="GitHub")
    client = await _github_client(db, row)
    st = str(args.get("state") or "open")
    if st not in ("open", "closed", "all"):
        st = "open"
    items = await client.list_repo_issues(
        str(args["owner"]),
        str(args["repo"]),
        state=st,
        page=int(args.get("page") or 1),
        per_page=int(args.get("per_page") or 30),
    )
    return {"issues": items}

@staticmethod
async def _tool_slack_list_conversations(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    row = await _resolve_connection(db, user, args, SLACK_TOOL_PROVIDERS, label="Slack")
    client = await _slack_api_client(db, row)
    return await client.conversations_list(
        types=str(args.get("types") or "public_channel,private_channel"),
        cursor=args.get("cursor"),
        limit=int(args.get("limit") or 200),
    )

@staticmethod
async def _tool_slack_get_conversation_history(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    row = await _resolve_connection(db, user, args, SLACK_TOOL_PROVIDERS, label="Slack")
    client = await _slack_api_client(db, row)
    return await client.conversations_history(
        str(args["channel_id"]),
        limit=int(args.get("limit") or 50),
        cursor=args.get("cursor"),
    )

@staticmethod
async def _tool_linear_list_issues(

    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    row = await _resolve_connection(db, user, args, LINEAR_TOOL_PROVIDERS, label="Linear")
    client = await _linear_client(db, row)
    data = await client.list_issues(first=int(args.get("first") or 25))
    return data

@staticmethod
async def _tool_linear_get_issue(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    row = await _resolve_connection(db, user, args, LINEAR_TOOL_PROVIDERS, label="Linear")
    client = await _linear_client(db, row)
    return await client.get_issue(str(args["issue_id"]))

@staticmethod
async def _tool_notion_search(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:

