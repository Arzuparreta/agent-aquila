"""Vector padding helper for pgvector dimensions.

Embedding providers (OpenAI, Ollama, Cohere, …) all return float lists
that may not match our pgvector column dimension (1536). This helper
pads/truncates a vector to the expected size before INSERT/UPDATE.
"""

from __future__ import annotations

from app.core.config import settings


def pad_embedding(vec: list[float]) -> list[float]:
    dim = settings.embedding_dimensions
    if len(vec) >= dim:
        return vec[:dim]
    return vec + [0.0] * (dim - len(vec))
