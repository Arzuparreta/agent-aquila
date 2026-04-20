"""Authoritative wall-clock context for the agent (user-local zone + formatting)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def resolve_user_zone(user_timezone: str | None) -> ZoneInfo:
    """Return a ZoneInfo for the user's IANA name, or UTC if missing/invalid."""
    raw = (user_timezone or "").strip()
    if not raw:
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(raw)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def normalize_time_format(value: str | None) -> str:
    v = (value or "auto").strip().lower()
    if v in ("auto", "12", "24"):
        return v
    return "auto"


def format_local_wall_time(dt_utc: datetime, zone: ZoneInfo, time_format: str) -> str:
    """Format ``dt_utc`` in ``zone`` according to ``time_format`` (auto|12|24)."""
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=UTC)
    local = dt_utc.astimezone(zone)
    tf = normalize_time_format(time_format)
    if tf == "12":
        return local.strftime("%Y-%m-%d %I:%M:%S %p")
    if tf == "24":
        return local.strftime("%Y-%m-%d %H:%M:%S")
    # auto: readable locale-neutral date + 24h time
    return local.strftime("%Y-%m-%d %H:%M:%S")


def build_datetime_context_section(
    *,
    now_utc: datetime | None = None,
    user_timezone: str | None = None,
    time_format: str = "auto",
) -> str:
    """Fixed markdown block for the system prompt (authoritative clock)."""
    now = now_utc or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    configured = (user_timezone or "").strip()
    zone = resolve_user_zone(user_timezone)
    tf = normalize_time_format(time_format)
    local_str = format_local_wall_time(now, zone, tf)
    if configured:
        try:
            ZoneInfo(configured)
            zone_line = configured
        except ZoneInfoNotFoundError:
            zone_line = f"{zone.key} (configured {configured!r} is not a valid IANA zone; using UTC)"
    else:
        zone_line = f"{zone.key} (not configured; default UTC — set your zone in Settings)"
    return (
        "# Current date and time (authoritative)\n\n"
        f"- Now (UTC, ISO): {now.isoformat()}\n"
        f"- User local time ({tf}): {local_str}\n"
        f"- IANA time zone: {zone_line}\n"
        "Use this for interpreting “today”, “tomorrow”, and scheduling. "
        "If unsure mid-turn, call `get_session_time`."
    )


def session_time_result(
    *,
    now_utc: datetime | None = None,
    user_timezone: str | None = None,
    time_format: str = "auto",
) -> dict[str, Any]:
    """Payload for the ``get_session_time`` tool."""
    now = now_utc or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    zone = resolve_user_zone(user_timezone)
    tf = normalize_time_format(time_format)
    return {
        "utc_iso": now.isoformat(),
        "user_local": format_local_wall_time(now, zone, tf),
        "iana_timezone": zone.key,
        "time_format": tf,
    }
