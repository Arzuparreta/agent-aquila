from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class AttachmentRead(BaseModel):
    id: int
    filename: str
    mime_type: str
    size_bytes: int
    thread_id: int | None = None
    created_at: datetime
    embedded: bool
    has_text: bool
