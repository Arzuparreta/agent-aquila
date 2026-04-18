from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.models.deal import Deal
from app.models.email import Email
from app.models.event import Event
from app.models.rag_chunk import RagChunk
from app.models.user import User
from app.schemas.ai import SemanticSearchHit
from app.services.ai_providers import provider_kind_requires_api_key
from app.services.embedding_client import EmbeddingClient
from app.services.embedding_vector import pad_embedding
from app.services.user_ai_settings_service import UserAISettingsService

RRF_K = 60
VEC_CANDIDATES = 48
FTS_CANDIDATES = 48


def _snippet(text: str | None, limit: int = 240) -> str:
    if not text:
        return ""
    cleaned = " ".join(text.split())
    return cleaned if len(cleaned) <= limit else f"{cleaned[: limit - 1]}…"


def _rrf(rank_lists: list[list[int]], *, k: int = RRF_K) -> dict[int, float]:
    scores: dict[int, float] = defaultdict(float)
    for ranks in rank_lists:
        for i, chunk_id in enumerate(ranks):
            scores[chunk_id] += 1.0 / (k + i + 1)
    return scores


class SemanticSearchService:
    @staticmethod
    async def _entity_title_snippet(db: AsyncSession, entity_type: str, entity_id: int) -> tuple[str, str]:
        if entity_type == "contact":
            row = await db.get(Contact, entity_id)
            if not row:
                return ("", "")
            return (row.name, _snippet(row.notes))
        if entity_type == "email":
            row = await db.get(Email, entity_id)
            if not row:
                return ("", "")
            return (row.subject, _snippet(row.body))
        if entity_type == "deal":
            row = await db.get(Deal, entity_id)
            if not row:
                return ("", "")
            return (row.title, _snippet(row.notes))
        if entity_type == "event":
            row = await db.get(Event, entity_id)
            if not row:
                return ("", "")
            return (row.venue_name, _snippet(row.notes))
        return ("", "")

    @staticmethod
    async def _legacy_row_search(
        db: AsyncSession, qvec: list[float], limit_per_type: int
    ) -> list[SemanticSearchHit]:
        hits: list[SemanticSearchHit] = []
        contact_stmt = (
            select(Contact.id, Contact.name, Contact.notes, Contact.embedding.cosine_distance(qvec).label("dist"))
            .where(Contact.embedding.is_not(None))
            .order_by(Contact.embedding.cosine_distance(qvec))
            .limit(limit_per_type)
        )
        result = await db.execute(contact_stmt)
        for row in result.all():
            dist = float(row.dist)
            hits.append(
                SemanticSearchHit(
                    entity_type="contact",
                    entity_id=int(row.id),
                    score=max(0.0, 1.0 - dist),
                    title=row.name,
                    snippet=_snippet(row.notes),
                    citation=f"contact:{row.id}",
                    chunk_id=None,
                    match_sources=["vector_legacy"],
                    rrf_score=None,
                )
            )
        email_stmt = (
            select(Email.id, Email.subject, Email.body, Email.embedding.cosine_distance(qvec).label("dist"))
            .where(Email.embedding.is_not(None))
            .order_by(Email.embedding.cosine_distance(qvec))
            .limit(limit_per_type)
        )
        result = await db.execute(email_stmt)
        for row in result.all():
            dist = float(row.dist)
            hits.append(
                SemanticSearchHit(
                    entity_type="email",
                    entity_id=int(row.id),
                    score=max(0.0, 1.0 - dist),
                    title=row.subject,
                    snippet=_snippet(row.body),
                    citation=f"email:{row.id}",
                    chunk_id=None,
                    match_sources=["vector_legacy"],
                    rrf_score=None,
                )
            )
        deal_stmt = (
            select(Deal.id, Deal.title, Deal.notes, Deal.embedding.cosine_distance(qvec).label("dist"))
            .where(Deal.embedding.is_not(None))
            .order_by(Deal.embedding.cosine_distance(qvec))
            .limit(limit_per_type)
        )
        result = await db.execute(deal_stmt)
        for row in result.all():
            dist = float(row.dist)
            hits.append(
                SemanticSearchHit(
                    entity_type="deal",
                    entity_id=int(row.id),
                    score=max(0.0, 1.0 - dist),
                    title=row.title,
                    snippet=_snippet(row.notes),
                    citation=f"deal:{row.id}",
                    chunk_id=None,
                    match_sources=["vector_legacy"],
                    rrf_score=None,
                )
            )
        event_stmt = (
            select(Event.id, Event.venue_name, Event.notes, Event.embedding.cosine_distance(qvec).label("dist"))
            .where(Event.embedding.is_not(None))
            .order_by(Event.embedding.cosine_distance(qvec))
            .limit(limit_per_type)
        )
        result = await db.execute(event_stmt)
        for row in result.all():
            dist = float(row.dist)
            hits.append(
                SemanticSearchHit(
                    entity_type="event",
                    entity_id=int(row.id),
                    score=max(0.0, 1.0 - dist),
                    title=row.venue_name,
                    snippet=_snippet(row.notes),
                    citation=f"event:{row.id}",
                    chunk_id=None,
                    match_sources=["vector_legacy"],
                    rrf_score=None,
                )
            )
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[: limit_per_type * 4]

    @staticmethod
    async def search(db: AsyncSession, user: User, query: str, limit_per_type: int) -> list[SemanticSearchHit]:
        settings_row = await UserAISettingsService.get_or_create(db, user)
        if settings_row.ai_disabled:
            return []
        api_key = await UserAISettingsService.get_api_key(db, user)
        if provider_kind_requires_api_key(settings_row.provider_kind) and not api_key:
            return []
        q_raw = (await EmbeddingClient.embed_texts(api_key or "", settings_row, [query]))[0]
        qvec = pad_embedding(q_raw)

        chunk_cnt = await db.scalar(select(func.count()).select_from(RagChunk)) or 0
        if chunk_cnt > 0:
            vec_stmt = (
                select(RagChunk.id, RagChunk.entity_type, RagChunk.entity_id, RagChunk.content)
                .where(RagChunk.embedding.is_not(None))
                .order_by(RagChunk.embedding.cosine_distance(qvec))
                .limit(VEC_CANDIDATES)
            )
            vec_rows = (await db.execute(vec_stmt)).all()
            vec_ids = [int(r.id) for r in vec_rows]

            fts_ids: list[int] = []
            q = query.strip()
            if q and any(c.isalnum() for c in q):
                try:
                    fts_sql = text(
                        """
                        SELECT id
                        FROM rag_chunks
                        WHERE to_tsvector('english', content) @@ websearch_to_tsquery('english', :q)
                        ORDER BY ts_rank_cd(to_tsvector('english', content), websearch_to_tsquery('english', :q)) DESC
                        LIMIT :lim
                        """
                    )
                    fts_result = await db.execute(fts_sql, {"q": q, "lim": FTS_CANDIDATES})
                    fts_ids = [int(r[0]) for r in fts_result.all()]
                except Exception:
                    fts_ids = []

            vec_data = {int(r.id): r for r in vec_rows}
            fts_rows = []
            if fts_ids:
                fts_stmt = select(RagChunk.id, RagChunk.entity_type, RagChunk.entity_id, RagChunk.content).where(
                    RagChunk.id.in_(fts_ids)
                )
                fts_rows = (await db.execute(fts_stmt)).all()
            fts_data = {int(r.id): r for r in fts_rows}

            rank_lists: list[list[int]] = []
            if vec_ids:
                rank_lists.append(vec_ids)
            if fts_ids:
                rank_lists.append(fts_ids)

            if rank_lists:
                rrf_scores = _rrf(rank_lists)
                all_chunk_ids = set(rrf_scores.keys())
                chunk_rows: dict[int, Any] = {}
                for cid in all_chunk_ids:
                    if cid in vec_data:
                        chunk_rows[cid] = vec_data[cid]
                    elif cid in fts_data:
                        chunk_rows[cid] = fts_data[cid]

                entity_chunks: dict[tuple[str, int], list[tuple[int, float, str]]] = defaultdict(list)
                for cid, rrf_s in rrf_scores.items():
                    row = chunk_rows.get(cid)
                    if not row:
                        continue
                    et = str(row.entity_type)
                    eid = int(row.entity_id)
                    entity_chunks[(et, eid)].append((cid, rrf_s, str(row.content)))

                hits: list[SemanticSearchHit] = []
                for (et, eid), lst in entity_chunks.items():
                    lst.sort(key=lambda x: x[1], reverse=True)
                    best_cid, best_rrf, best_content = lst[0]
                    title, fallback_snip = await SemanticSearchService._entity_title_snippet(db, et, eid)
                    sources: list[str] = []
                    if best_cid in vec_ids:
                        sources.append("vector")
                    if best_cid in fts_ids:
                        sources.append("keyword")
                    hits.append(
                        SemanticSearchHit(
                            entity_type=et,
                            entity_id=eid,
                            score=best_rrf,
                            title=title or et,
                            snippet=_snippet(best_content) if best_content else fallback_snip,
                            citation=f"{et}:{eid}#chunk:{best_cid}",
                            chunk_id=best_cid,
                            match_sources=sources,
                            rrf_score=best_rrf,
                        )
                    )

                hits.sort(key=lambda h: (h.rrf_score or 0), reverse=True)
                return hits[: limit_per_type * 4]

        return await SemanticSearchService._legacy_row_search(db, qvec, limit_per_type)
