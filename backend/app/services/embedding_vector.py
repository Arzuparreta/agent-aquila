"""Vector padding for pgvector dimensions — kept separate to avoid circular imports with embedding_service ↔ rag_index_service."""

from __future__ import annotations

from app.core.config import settings


def pad_embedding(vec: list[float]) -> list[float]:
    dim = settings.embedding_dimensions
    if len(vec) >= dim:
        return vec[:dim]
    return vec + [0.0] * (dim - len(vec))
