"""CRUD + recall for the agent's persistent memory.

The agent's "memory" is just rows in ``agent_memories`` keyed by
``(user_id, key)``. Unlike the chat history (transcript) or connector
mirrors (gone after the OpenClaw refactor), this table stores the
agent's *own* notes — preferences, recurring tasks, facts the user
asked it to remember.

Three entry points:
- :func:`upsert` — write/update a memory by key.
- :func:`delete` — drop a memory by key.
- :func:`recall` — search by semantic similarity (when an embedding
  provider is configured) or fall back to recency + tag filter.

Two convenience helpers are used by the agent loop itself:
- :func:`recent_for_prompt` returns the top-N memories formatted as a
  bullet list to splice into the system prompt every chat turn.
- :func:`list_for_user` powers the Settings → Memory viewer.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_memory import AgentMemory
from app.models.user import User
from app.services.ai_provider_config_service import AIProviderConfigService
from app.services.embedding_client import EmbeddingClient
from app.services.embedding_vector import pad_embedding
from app.services.user_ai_settings_service import UserAISettingsService

logger = logging.getLogger(__name__)

# How many memories to splice into the system prompt on each turn.
SYSTEM_PROMPT_LIMIT = 12
# How many results recall() returns by default.
RECALL_DEFAULT_LIMIT = 6


async def _embed_one(db: AsyncSession, user: User, text: str) -> tuple[list[float] | None, str | None]:
    """Return ``(vector, model)`` or ``(None, None)`` if embedding is unavailable.

    Failures are swallowed: memory writes must succeed even when the
    embedding provider is down. Recall just falls back to recency.
    """
    settings_row = await UserAISettingsService.get_or_create(db, user)
    if settings_row.ai_disabled:
        return None, None
    ctx = await AIProviderConfigService.resolve_embedding_runtime(db, user)
    if ctx is None:
        return None, None
    try:
        vectors = await EmbeddingClient.embed_texts(ctx, [text])
    except Exception:  # noqa: BLE001 — best-effort
        logger.warning("agent_memory: embedding call failed, falling back to no-vector", exc_info=True)
        return None, None
    if not vectors:
        return None, None
    return pad_embedding(vectors[0], 1536), ctx.embedding_model


class AgentMemoryService:
    @staticmethod
    async def upsert(
        db: AsyncSession,
        user: User,
        *,
        key: str,
        content: str,
        importance: int = 0,
        tags: list[str] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> AgentMemory:
        key = key.strip()[:200]
        if not key:
            raise ValueError("memory key is required")
        content = content.strip()
        if not content:
            raise ValueError("memory content is required")
        existing = (
            await db.execute(
                select(AgentMemory).where(
                    AgentMemory.user_id == user.id, AgentMemory.key == key
                )
            )
        ).scalar_one_or_none()
        vec, model = await _embed_one(db, user, f"{key}\n{content}")
        if existing:
            existing.content = content
            existing.importance = max(0, int(importance))
            existing.tags = list(tags) if tags is not None else existing.tags
            existing.meta = meta if meta is not None else existing.meta
            if vec is not None:
                existing.embedding = vec
                existing.embedding_model = model
            await db.commit()
            await db.refresh(existing)
            return existing
        row = AgentMemory(
            user_id=user.id,
            key=key,
            content=content,
            importance=max(0, int(importance)),
            tags=list(tags) if tags else None,
            embedding=vec,
            embedding_model=model,
            meta=meta,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row

    @staticmethod
    async def delete(db: AsyncSession, user: User, *, key: str) -> bool:
        row = (
            await db.execute(
                select(AgentMemory).where(
                    AgentMemory.user_id == user.id, AgentMemory.key == key
                )
            )
        ).scalar_one_or_none()
        if not row:
            return False
        await db.delete(row)
        await db.commit()
        return True

    @staticmethod
    async def get(db: AsyncSession, user: User, *, key: str) -> AgentMemory | None:
        return (
            await db.execute(
                select(AgentMemory).where(
                    AgentMemory.user_id == user.id, AgentMemory.key == key
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def list_for_user(
        db: AsyncSession, user: User, *, limit: int = 200
    ) -> list[AgentMemory]:
        stmt = (
            select(AgentMemory)
            .where(AgentMemory.user_id == user.id)
            .order_by(desc(AgentMemory.importance), desc(AgentMemory.updated_at))
            .limit(limit)
        )
        return list((await db.execute(stmt)).scalars().all())

    @staticmethod
    async def recall(
        db: AsyncSession,
        user: User,
        *,
        query: str | None = None,
        tags: list[str] | None = None,
        limit: int = RECALL_DEFAULT_LIMIT,
    ) -> list[dict[str, Any]]:
        """Return memories ranked by similarity to ``query`` (best effort).

        Pure recency fallback when no query is given or embeddings can't
        be computed. ``tags`` further filter the result set.
        """
        limit = max(1, min(50, int(limit)))
        # Embedding-driven recall when possible.
        vec: list[float] | None = None
        if query and query.strip():
            vec, _ = await _embed_one(db, user, query.strip())

        if vec is not None:
            stmt = (
                select(AgentMemory, AgentMemory.embedding.l2_distance(vec).label("dist"))
                .where(AgentMemory.user_id == user.id)
                .where(AgentMemory.embedding.isnot(None))
                .order_by("dist")
                .limit(limit * 3)
            )
            rows = (await db.execute(stmt)).all()
            results: list[tuple[AgentMemory, float]] = [(r[0], float(r[1])) for r in rows]
        else:
            stmt = (
                select(AgentMemory)
                .where(AgentMemory.user_id == user.id)
                .order_by(desc(AgentMemory.importance), desc(AgentMemory.updated_at))
                .limit(limit * 3)
            )
            rows = (await db.execute(stmt)).scalars().all()
            results = [(r, 0.0) for r in rows]

        if tags:
            tagset = {t.lower() for t in tags}
            results = [
                (m, d)
                for m, d in results
                if m.tags and any(t.lower() in tagset for t in m.tags)
            ]

        results = results[:limit]
        return [
            {
                "id": m.id,
                "key": m.key,
                "content": m.content,
                "importance": m.importance,
                "tags": m.tags,
                "updated_at": m.updated_at.isoformat() if m.updated_at else None,
                "score": (1.0 - dist) if dist else None,
            }
            for m, dist in results
        ]

    @staticmethod
    async def recent_for_prompt(
        db: AsyncSession, user: User, *, limit: int = SYSTEM_PROMPT_LIMIT
    ) -> str:
        """Render the agent's most relevant memories as a markdown bullet list.

        Used by ``agent_workspace.build_system_prompt`` to warm the chat
        with whatever the agent has already learned about this user. We
        sort high-importance memories first, then fill the remainder with
        the most recently updated rows.
        """
        rows = await AgentMemoryService.list_for_user(db, user, limit=limit)
        if not rows:
            return ""
        lines = ["## Agent persistent memory\n"]
        for m in rows:
            star = "★ " if (m.importance or 0) >= 1 else ""
            content_short = (m.content or "").strip()
            if len(content_short) > 280:
                content_short = content_short[:277].rstrip() + "…"
            lines.append(f"- {star}**{m.key}** — {content_short}")
        lines.append("")
        return "\n".join(lines)
