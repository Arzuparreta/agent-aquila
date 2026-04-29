"""Sheets and Docs tool handlers."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.connectors.google_sheets_client import GoogleSheetsClient
from app.services.connectors.google_docs_client import GoogleDocsClient

from .base import provider_connection


@provider_connection("sheets")
async def _tool_sheets_read_range(
    db: AsyncSession, user: User, client: GoogleSheetsClient, args: dict[str, Any],
) -> dict[str, Any]:
    return await client.get_values(str(args["spreadsheet_id"]), str(args["range"]))


@provider_connection("docs")
async def _tool_docs_get_document(
    db: AsyncSession, user: User, client: GoogleDocsClient, args: dict[str, Any],
) -> dict[str, Any]:
    return await client.get_document(str(args["document_id"]))
