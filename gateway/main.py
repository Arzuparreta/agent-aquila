#!/usr/bin/env python3
"""Minimal gateway stub: POST /channels/gateway/deliver with bearer auth."""

from __future__ import annotations

import argparse
import os
import sys
import urllib.error
import urllib.request


def _post_json(url: str, token: str, body: dict) -> dict:
    import json

    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {exc.code}: {detail}") from exc


def main() -> None:
    parser = argparse.ArgumentParser(description="Deliver one message through the Aquila gateway stub.")
    parser.add_argument("--text", default="Gateway ping", help="User message text")
    parser.add_argument(
        "--external-key",
        default="stub-chat-1",
        help="Stable id for this remote conversation (binding key)",
    )
    args = parser.parse_args()

    base = (os.environ.get("AQUILA_API_BASE") or "http://localhost:8000").rstrip("/")
    token = os.environ.get("AQUILA_TOKEN") or ""
    if not token:
        print("Set AQUILA_TOKEN to a JWT from POST /api/v1/auth/login", file=sys.stderr)
        sys.exit(1)

    url = f"{base}/api/v1/channels/gateway/deliver"
    out = _post_json(
        url,
        token,
        {
            "channel": "gateway_stub",
            "external_key": args.external_key,
            "text": args.text,
        },
    )
    print(out)


if __name__ == "__main__":
    main()
