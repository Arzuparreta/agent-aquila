"""Google People (Contacts) tool handlers."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.connectors.google_people_client import GooglePeopleClient

from .base import provider_connection


@provider_connection("people")
async def _tool_people_search_contacts(
    db: AsyncSession, user: User, client: GooglePeopleClient, args: dict[str, Any],
) -> dict[str, Any]:
    return await client.search_contacts(
        str(args["query"]),
        page_token=args.get("page_token"),
        page_size=int(args.get("page_size") or 20),
    )
