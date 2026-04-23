"""Periodic consolidation: digest append + DB reindex from canonical (adaptive hybrid lane)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.user import User
from app.services.agent_memory_service import AgentMemoryService
from app.services.canonical_memory import memory_workspace_dir, read_all_kv, ensure_user_memory_layout

logger = logging.getLogger(__name__)


def _append_dreams_digest(user_id: int, line: str) -> None:
    ensure_user_memory_layout(user_id)
    path = memory_workspace_dir(user_id) / "DREAMS.md"
    ts = datetime.now(UTC).isoformat()
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n- **{ts}** — {line}\n")
    except OSError:
        logger.exception("consolidation: append DREAMS failed user_id=%s", user_id)


async def run_consolidation_sweep(
    db: AsyncSession,
    user: User,
) -> dict[str, int | str | bool]:
    """Append digest line, reindex ``agent_memories`` from canonical markdown."""
    rows = read_all_kv(int(user.id))
    top = sorted(rows, key=lambda t: -t[1])[:5]
    summary_bits = [f"{k}({i})" for k, i, _ in top]
    line = f"consolidation: {len(rows)} keys; top {', '.join(summary_bits) if summary_bits else '—'}"
    _append_dreams_digest(int(user.id), line)
    n = await AgentMemoryService.reindex_db_from_canonical(db, user, sync_canonical=False)
    try:
        from app.services.agent_user_context import refresh_user_context_overview

        await refresh_user_context_overview(db, user, force_llm=True)
    except Exception:  # noqa: BLE001
        logger.exception("consolidation: user context snapshot refresh failed user_id=%s", user.id)
    return {"keys": len(rows), "reindexed": n, "ok": True}


async def run_consolidation_for_all_active_users() -> dict[str, object]:
    """Worker entry: all active users (one DB session)."""
    from app.core.database import AsyncSessionLocal
    from app.models.user import User as UserModel

    out: list[dict[str, object]] = []
    async with AsyncSessionLocal() as session:
        users = list(
            (await session.execute(select(UserModel).where(UserModel.is_active.is_(True))))
            .scalars()
            .all()
        )
        for u in users:
            try:
                if not getattr(settings, "agent_memory_consolidation_enabled", True):
                    out.append({"user_id": u.id, "skipped": True, "reason": "disabled"})
                    continue
                stats = await run_consolidation_sweep(session, u)
                out.append(
                    {
                        "user_id": u.id,
                        "keys": stats.get("keys"),
                        "reindexed": stats.get("reindexed"),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("consolidation failed user %s: %s", u.id, exc)
                out.append({"user_id": u.id, "error": str(exc)[:200]})
    return {"sweeps": out}
