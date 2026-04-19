"""Tests for Gmail 429 retry parsing."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

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
