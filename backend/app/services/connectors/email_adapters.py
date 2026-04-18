from __future__ import annotations

import asyncio
import base64
import smtplib
from email.mime.text import MIMEText
from typing import Any

import httpx

GRAPH_SEND = "https://graph.microsoft.com/v1.0/me/sendMail"
GMAIL_SEND = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"


async def send_email(
    provider: str,
    creds: dict[str, Any],
    to: list[str],
    subject: str,
    body: str,
    *,
    content_type: str = "text",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Send email via Microsoft Graph, Gmail API, SMTP, or mock (no network)."""
    if dry_run:
        if provider == "mock_email":
            return {"ok": True, "dry_run": True, "to": to, "subject": subject}
        token = creds.get("access_token") or creds.get("token")
        if provider in ("graph_mail", "microsoft_mail", "outlook", "google_gmail", "gmail") and not token:
            return {"ok": False, "error": "missing access_token in connection credentials"}
        if provider == "smtp":
            for key in ("host", "username", "password"):
                if not creds.get(key):
                    return {"ok": False, "error": f"missing smtp credential: {key}"}
        return {"ok": True, "dry_run": True, "provider": provider, "would_send_to": to, "subject": subject}

    if provider == "smtp":
        host = str(creds.get("host") or "")
        port = int(creds.get("port") or 587)
        username = str(creds.get("username") or "")
        password = str(creds.get("password") or "")
        use_tls = bool(creds.get("use_tls", True))
        if not host or not username:
            return {"ok": False, "error": "smtp requires host and username"}
        mime = MIMEText(body, "html" if content_type.lower() == "html" else "plain")
        mime["Subject"] = subject
        mime["From"] = str(creds.get("from_addr") or username)
        mime["To"] = ", ".join(to)

        def _send() -> None:
            with smtplib.SMTP(host, port, timeout=60) as smtp:
                if use_tls:
                    smtp.starttls()
                smtp.login(username, password)
                smtp.sendmail(mime["From"], to, mime.as_string())

        await asyncio.to_thread(_send)
        return {"ok": True, "via": "smtp"}

    if provider in ("graph_mail", "microsoft_mail", "outlook"):
        token = creds.get("access_token") or creds.get("token")
        if not token:
            return {"ok": False, "error": "missing access_token in connection credentials"}
        ct = "HTML" if content_type.lower() == "html" else "Text"
        message = {
            "subject": subject,
            "body": {"contentType": ct, "content": body},
            "toRecipients": [{"emailAddress": {"address": addr}} for addr in to],
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(GRAPH_SEND, json={"message": message}, headers={"Authorization": f"Bearer {token}"})
        if r.status_code >= 300:
            return {"ok": False, "status": r.status_code, "detail": r.text[:500]}
        return {"ok": True, "status": r.status_code}

    if provider in ("google_gmail", "gmail"):
        token = creds.get("access_token") or creds.get("token")
        if not token:
            return {"ok": False, "error": "missing access_token in connection credentials"}
        mime = MIMEText(body, "html" if content_type.lower() == "html" else "plain")
        mime["to"] = ", ".join(to)
        mime["subject"] = subject
        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode().rstrip("=")
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(GMAIL_SEND, json={"raw": raw}, headers={"Authorization": f"Bearer {token}"})
        if r.status_code >= 300:
            return {"ok": False, "status": r.status_code, "detail": r.text[:500]}
        return {"ok": True, "status": r.status_code, "id": r.json().get("id")}

    if provider == "mock_email":
        return {"ok": True, "mock": True, "to": to, "subject": subject}

    return {"ok": False, "error": f"unsupported email provider: {provider}"}
