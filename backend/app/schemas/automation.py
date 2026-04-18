from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AutomationConditions(BaseModel):
    """Lightweight matcher dict; all provided fields must match (AND)."""

    model_config = ConfigDict(extra="allow")

    from_contains: str | None = None
    subject_contains: str | None = None
    body_contains: str | None = None
    direction: Literal["inbound", "outbound"] | None = None
    provider: str | None = None


class AutomationCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    trigger: Literal["email_received"] = "email_received"
    conditions: dict[str, Any] = Field(default_factory=dict)
    prompt_template: str = Field(..., min_length=1, max_length=8000)
    default_connection_id: int | None = None
    auto_approve: bool = False
    enabled: bool = True


class AutomationPatch(BaseModel):
    name: str | None = None
    conditions: dict[str, Any] | None = None
    prompt_template: str | None = None
    default_connection_id: int | None = None
    auto_approve: bool | None = None
    enabled: bool | None = None


class AutomationRead(BaseModel):
    id: int
    name: str
    trigger: str
    conditions: dict[str, Any]
    prompt_template: str
    default_connection_id: int | None
    auto_approve: bool
    enabled: bool
    last_run_at: datetime | None
    run_count: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
