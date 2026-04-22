from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class DashboardStatusRead(BaseModel):
    database_ok: bool
    redis_configured: bool
    redis_ping_ok: bool
    arq_pool_ok: bool


class DashboardMetricsRead(BaseModel):
    agent_runs_last_24h: int
    agent_runs_completed_last_24h: int
    agent_runs_failed_last_24h: int
    agent_runs_needs_attention_last_24h: int


class OnboardingStatusRead(BaseModel):
    database_ok: bool
    redis_ok: bool
    has_ai_provider: bool
    connector_count: int
    telegram_configured: bool
    agent_async_runs: bool


class TelegramPairingRead(BaseModel):
    code: str
    expires_at: datetime


class TelegramLinkStatusRead(BaseModel):
    linked: bool
