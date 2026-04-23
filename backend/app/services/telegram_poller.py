"""Telegram long polling (OpenClaw-style): worker pulls getUpdates — no public webhook URL required."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.services.connectors.telegram_bot_client import TelegramAPIError, TelegramBotClient
from app.services.telegram_integration_service import (
    TelegramPollTarget,
    list_telegram_poll_targets,
    offset_file_path_for_token,
)
from app.services.telegram_inbound_service import dispatch_telegram_bot_update

logger = logging.getLogger(__name__)


def _state_path_named(filename: str) -> Path:
    base = (getattr(settings, "aquila_user_data_dir", None) or "").strip()
    if not base:
        base = str(Path(__file__).resolve().parents[2] / ".local_data")
    p = Path(base)
    p.mkdir(parents=True, exist_ok=True)
    return p / filename


def _read_offset(path: Path) -> int | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        uid = data.get("last_update_id")
        return int(uid) if uid is not None else None
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _write_offset(path: Path, last_update_id: int) -> None:
    payload = json.dumps({"last_update_id": last_update_id}, indent=0)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)


async def _poll_single_bot(target: TelegramPollTarget, stop: asyncio.Event) -> None:
    token = target.bot_token
    path = _state_path_named(offset_file_path_for_token(token))
    client = TelegramBotClient(token)
    try:
        await client.delete_webhook(drop_pending_updates=False)
        logger.info("telegram deleteWebhook ok; long-polling one bot token")
    except TelegramAPIError as exc:
        logger.warning("telegram deleteWebhook failed (continuing): %s", exc)

    poll_timeout = target.poll_timeout
    if poll_timeout <= 0:
        poll_timeout = 45
    next_offset = _read_offset(path)

    async def _sleep_unless_stopped(seconds: float) -> None:
        try:
            await asyncio.wait_for(stop.wait(), timeout=seconds)
        except TimeoutError:
            pass

    while not stop.is_set():
        try:
            off = (next_offset + 1) if next_offset is not None else None
            lp = poll_timeout if poll_timeout > 0 else None
            data = await client.get_updates(offset=off, limit=50, long_poll_timeout=lp)
            rows = data.get("result") or []
            if not isinstance(rows, list):
                rows = []
            max_id = next_offset or 0
            for upd in rows:
                if not isinstance(upd, dict):
                    continue
                uid = upd.get("update_id")
                try:
                    async with AsyncSessionLocal() as db:
                        await dispatch_telegram_bot_update(db, upd, bot_token=token)
                except Exception:
                    logger.exception("telegram dispatch failed for update_id=%s", uid)
                if isinstance(uid, int):
                    max_id = max(max_id, uid)
            if rows and max_id > (next_offset or 0):
                next_offset = max_id
                _write_offset(path, max_id)
        except TelegramAPIError as exc:
            if exc.status_code == 409:
                logger.warning(
                    "telegram getUpdates 409 conflict — only one consumer per bot token; retrying soon"
                )
            else:
                logger.warning("telegram getUpdates error: %s", exc)
            await _sleep_unless_stopped(6.0 if exc.status_code == 409 else 3.0)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("telegram poll loop error")
            await _sleep_unless_stopped(5.0)


async def run_telegram_long_poll_supervisor(stop: asyncio.Event) -> None:
    if not settings.telegram_polling_enabled:
        logger.info("telegram long polling disabled (TELEGRAM_POLLING_ENABLED=false)")
        return
    while not stop.is_set():
        async with AsyncSessionLocal() as db:
            targets = await list_telegram_poll_targets(db)
        if not targets:
            try:
                await asyncio.wait_for(stop.wait(), timeout=12.0)
            except TimeoutError:
                pass
            continue
        logger.info("telegram poller: starting %d long-poll loop(s)", len(targets))
        try:
            await asyncio.gather(*[_poll_single_bot(t, stop) for t in targets])
        except asyncio.CancelledError:
            raise
