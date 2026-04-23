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


class ContextBudgetDebugRead(BaseModel):
    provider_kind: str
    model: str
    model_limits_source: str
    context_window: int
    max_output_tokens_default: int
    estimated_input_tokens: int
    input_budget_tokens: int
    reserved_output_tokens: int
    would_compact: bool
    runtime_flags: dict[str, bool]


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
