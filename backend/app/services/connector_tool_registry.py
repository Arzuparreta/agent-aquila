"""Single source of truth: which ``ConnectorConnection.provider`` values unlock agent tools.

* **Gating** — :func:`required_providers_for_tool` drives
  ``agent_tools.filter_tools_for_user_connectors`` / ``tool_required_connector_providers``.
* **Dispatch** — :mod:`app.services.agent_service` passes the same tuples to
  ``_resolve_connection`` so connection resolution and tool visibility never drift.

When adding an integration: extend the relevant provider tuple (or add a new one) and
update :func:`required_providers_for_tool` once.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Provider tuples (stable order for SQL ``IN`` and user-facing errors)
# ---------------------------------------------------------------------------

GMAIL_TOOL_PROVIDERS: tuple[str, ...] = ("google_gmail", "gmail")

CALENDAR_TOOL_PROVIDERS: tuple[str, ...] = (
    "google_calendar",
    "gcal",
    "icloud_caldav",
    "graph_calendar",
    "microsoft_calendar",
    "outlook_calendar",
)

GRAPH_CALENDAR_TOOL_PROVIDERS: frozenset[str] = frozenset(
    {"graph_calendar", "microsoft_calendar", "outlook_calendar"}
)

DRIVE_TOOL_PROVIDERS: tuple[str, ...] = ("google_drive", "gdrive")

OUTLOOK_MAIL_TOOL_PROVIDERS: tuple[str, ...] = ("graph_mail",)

TEAMS_TOOL_PROVIDERS: tuple[str, ...] = ("graph_teams", "ms_teams")

YOUTUBE_TOOL_PROVIDERS: tuple[str, ...] = ("google_youtube",)

TASKS_TOOL_PROVIDERS: tuple[str, ...] = ("google_tasks",)

PEOPLE_TOOL_PROVIDERS: tuple[str, ...] = ("google_people",)

SHEETS_TOOL_PROVIDERS: tuple[str, ...] = ("google_sheets",)

DOCS_TOOL_PROVIDERS: tuple[str, ...] = ("google_docs",)

WHATSAPP_TOOL_PROVIDERS: tuple[str, ...] = ("whatsapp_business",)

ICLOUD_TOOL_PROVIDERS: tuple[str, ...] = ("icloud_caldav",)

GITHUB_TOOL_PROVIDERS: tuple[str, ...] = ("github",)

SLACK_TOOL_PROVIDERS: tuple[str, ...] = ("slack_bot",)

LINEAR_TOOL_PROVIDERS: tuple[str, ...] = ("linear",)

NOTION_TOOL_PROVIDERS: tuple[str, ...] = ("notion",)

TELEGRAM_TOOL_PROVIDERS: tuple[str, ...] = ("telegram_bot",)

DISCORD_TOOL_PROVIDERS: tuple[str, ...] = ("discord_bot",)

# Frozensets for fast gating (derived from tuples where we need identity checks in tests)
CALENDAR_TOOL_PROVIDERS_FROZEN: frozenset[str] = frozenset(CALENDAR_TOOL_PROVIDERS)


def connector_registry_snapshot() -> dict[str, list[str]]:
    """Stable summary for ``describe_harness`` / introspection (same data as gating)."""
    return {
        "gmail_tools_and_email_proposals": list(GMAIL_TOOL_PROVIDERS),
        "calendar_tools": list(CALENDAR_TOOL_PROVIDERS),
        "drive_tools": list(DRIVE_TOOL_PROVIDERS),
        "outlook_mail_tools": list(OUTLOOK_MAIL_TOOL_PROVIDERS),
        "teams_tools": list(TEAMS_TOOL_PROVIDERS),
        "youtube_tools": list(YOUTUBE_TOOL_PROVIDERS),
        "tasks_tools": list(TASKS_TOOL_PROVIDERS),
        "people_tools": list(PEOPLE_TOOL_PROVIDERS),
        "sheets_tools": list(SHEETS_TOOL_PROVIDERS),
        "docs_tools": list(DOCS_TOOL_PROVIDERS),
        "whatsapp_proposals": list(WHATSAPP_TOOL_PROVIDERS),
        "icloud_tools": list(ICLOUD_TOOL_PROVIDERS),
        "github_tools": list(GITHUB_TOOL_PROVIDERS),
        "slack_tools": list(SLACK_TOOL_PROVIDERS),
        "linear_tools": list(LINEAR_TOOL_PROVIDERS),
        "notion_tools": list(NOTION_TOOL_PROVIDERS),
        "telegram_tools": list(TELEGRAM_TOOL_PROVIDERS),
        "discord_tools": list(DISCORD_TOOL_PROVIDERS),
    }


def required_providers_for_tool(tool_name: str) -> frozenset[str] | None:
    """If the tool talks to a specific upstream, return acceptable ``ConnectorConnection.provider`` ids."""
    n = (tool_name or "").lower()
    if n.startswith("gmail_") or n.startswith("propose_email"):
        return frozenset(GMAIL_TOOL_PROVIDERS)
    if n.startswith("calendar_"):
        return CALENDAR_TOOL_PROVIDERS_FROZEN
    if n.startswith("drive_"):
        return frozenset(DRIVE_TOOL_PROVIDERS)
    if n.startswith("youtube_") or n == "propose_youtube_upload":
        return frozenset(YOUTUBE_TOOL_PROVIDERS)
    if n.startswith("tasks_"):
        return frozenset(TASKS_TOOL_PROVIDERS)
    if n.startswith("people_"):
        return frozenset(PEOPLE_TOOL_PROVIDERS)
    if n.startswith("sheets_"):
        return frozenset(SHEETS_TOOL_PROVIDERS)
    if n.startswith("docs_"):
        return frozenset(DOCS_TOOL_PROVIDERS)
    if n.startswith("icloud_drive_"):
        return frozenset(ICLOUD_TOOL_PROVIDERS)
    if n.startswith("icloud_contacts_"):
        return frozenset(ICLOUD_TOOL_PROVIDERS)
    if n in ("icloud_reminders_list", "icloud_notes_list", "icloud_photos_list"):
        return frozenset(ICLOUD_TOOL_PROVIDERS)
    if n == "propose_whatsapp_send":
        return frozenset(WHATSAPP_TOOL_PROVIDERS)
    if n.startswith("github_"):
        return frozenset(GITHUB_TOOL_PROVIDERS)
    if n.startswith("slack_"):
        return frozenset(SLACK_TOOL_PROVIDERS)
    if n == "propose_slack_post_message":
        return frozenset(SLACK_TOOL_PROVIDERS)
    if n.startswith("linear_") or n == "propose_linear_create_comment":
        return frozenset(LINEAR_TOOL_PROVIDERS)
    if n.startswith("notion_"):
        return frozenset(NOTION_TOOL_PROVIDERS)
    if n.startswith("telegram_") or n == "propose_telegram_send_message":
        return frozenset(TELEGRAM_TOOL_PROVIDERS)
    if n.startswith("discord_") or n == "propose_discord_post_message":
        return frozenset(DISCORD_TOOL_PROVIDERS)
    if n.startswith("outlook_"):
        return frozenset(OUTLOOK_MAIL_TOOL_PROVIDERS)
    if n.startswith("teams_"):
        return frozenset(TEAMS_TOOL_PROVIDERS)
    return None
