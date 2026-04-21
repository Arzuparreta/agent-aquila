"""Regression: ``pad_embedding`` takes a single vector; dimension comes from settings."""

from __future__ import annotations

from app.services.embedding_vector import pad_embedding


def test_pad_embedding_truncates_and_pads_to_configured_dim() -> None:
    from app.core.config import settings

    dim = settings.embedding_dimensions
    assert len(pad_embedding([0.25] * (dim + 50))) == dim
    assert len(pad_embedding([0.25] * 100)) == dim
