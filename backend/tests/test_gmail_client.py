"""Tests for Gmail client: 429 parsing + REST body shapes (mocked httpx)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.connectors.gmail_client import GmailClient


def test_seconds_until_retry_deadline_from_google_error_json() -> None:
    body = """{
  "error": {
    "message": "User-rate limit exceeded.  Retry after 2026-04-19T23:39:25.148Z",
    "errors": [
      {
        "message": "User-rate limit exceeded.  Retry after 2026-04-19T23:39:25.148Z",
        "domain": "global",
        "reason": "rateLimitExceeded"
      }
    ]
  }
}"""
    fixed_now = datetime(2026, 4, 19, 23, 30, 0, tzinfo=timezone.utc)
    with patch("app.services.connectors.gmail_client.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now
        mock_dt.fromisoformat = datetime.fromisoformat
        seconds = GmailClient._seconds_until_gmail_retry_deadline(body)
    # 23:30 → 23:39:25.148 ≈ 565.148 s
    assert seconds is not None
    assert 564.0 < seconds < 566.0


def test_seconds_until_retry_deadline_returns_none_without_match() -> None:
    assert GmailClient._seconds_until_gmail_retry_deadline("{}") is None
    assert GmailClient._seconds_until_gmail_retry_deadline("") is None


@pytest.mark.asyncio
async def test_modify_thread_sends_camel_case_labels() -> None:
    captured: list[dict | None] = []

    async def on_request(method, url, *, params=None, json=None, headers=None):
        captured.append(json)
        return httpx.Response(200, json={"id": "t1"})

    mock_inner = MagicMock()
    mock_inner.request = AsyncMock(side_effect=on_request)

    class _ACM:
        async def __aenter__(self):
            return mock_inner

        async def __aexit__(self, *args):
            return None

    with patch("app.services.connectors.gmail_client.httpx.AsyncClient", return_value=_ACM()):
        client = GmailClient("tok")
        await client.modify_thread(
            "thread-1",
            add_label_ids=["SPAM"],
            remove_label_ids=["INBOX"],
        )
    assert captured == [{"addLabelIds": ["SPAM"], "removeLabelIds": ["INBOX"]}]


@pytest.mark.asyncio
async def test_create_filter_posts_criteria_and_action() -> None:
    captured: list[dict | None] = []

    async def on_request(method, url, *, params=None, json=None, headers=None):
        captured.append(json)
        return httpx.Response(200, json={"id": "filt-1"})

    mock_inner = MagicMock()
    mock_inner.request = AsyncMock(side_effect=on_request)

    class _ACM:
        async def __aenter__(self):
            return mock_inner

        async def __aexit__(self, *args):
            return None

    with patch("app.services.connectors.gmail_client.httpx.AsyncClient", return_value=_ACM()):
        client = GmailClient("tok")
        await client.create_filter(
            criteria={"from": "a@example.com"},
            action={"removeLabelIds": ["INBOX", "UNREAD"]},
        )
    assert captured == [
        {
            "criteria": {"from": "a@example.com"},
            "action": {"removeLabelIds": ["INBOX", "UNREAD"]},
        }
    ]
