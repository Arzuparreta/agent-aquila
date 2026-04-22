"""Per-user agent runtime overrides (merged with env defaults from ``config.settings``)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

AgentToolPalette = Literal["full", "compact"]
AgentPromptTier = Literal["full", "minimal", "none"]
AgentMemoryPostTurnMode = Literal["heuristic", "always", "committee", "adaptive"]


class AgentRuntimeConfigPartial(BaseModel):
    """PATCH payload: all fields optional. Use ``null`` in JSON to clear an override (revert to env default)."""

    agent_max_runs_per_hour: int | None = Field(default=None, ge=1, le=10_000)
    agent_max_tool_steps: int | None = Field(default=None, ge=1, le=100)
    agent_async_runs: bool | None = None
    agent_heartbeat_burst_per_hour: int | None = Field(default=None, ge=0, le=10_000)
    agent_heartbeat_enabled: bool | None = None
    agent_heartbeat_minutes: int | None = Field(default=None, ge=1, le=1440)
    agent_heartbeat_check_gmail: bool | None = None
    agent_tool_palette: AgentToolPalette | None = None
    agent_prompt_tier: AgentPromptTier | None = None
    agent_include_harness_facts: bool | None = None
    agent_connector_gated_tools: bool | None = None
    agent_prompted_compact_json: bool | None = None
    agent_history_turns: int | None = Field(default=None, ge=1, le=64)
    agent_thread_compact_after_pairs: int | None = Field(default=None, ge=0, le=500)
    agent_memory_flush_enabled: bool | None = None
    agent_memory_flush_max_steps: int | None = Field(default=None, ge=1, le=50)
    agent_memory_flush_max_transcript_chars: int | None = Field(default=None, ge=1000, le=500_000)
    agent_memory_post_turn_enabled: bool | None = None
    agent_memory_post_turn_mode: AgentMemoryPostTurnMode | None = None
    agent_channel_gateway_enabled: bool | None = None
    agent_email_domain_allowlist: str | None = None

    @field_validator("agent_memory_post_turn_mode", mode="before")
    @classmethod
    def _norm_post_turn_mode(cls, v: Any) -> Any:
        if v is None or isinstance(v, str) and not str(v).strip():
            return None
        m = str(v).strip().lower()
        if m not in ("heuristic", "always", "committee", "adaptive"):
            raise ValueError(
                "agent_memory_post_turn_mode must be heuristic, always, committee, or adaptive"
            )
        return m

    @field_validator("agent_tool_palette", mode="before")
    @classmethod
    def _norm_palette(cls, v: Any) -> Any:
        if v is None or isinstance(v, str) and not str(v).strip():
            return None
        m = str(v).strip().lower()
        if m not in ("full", "compact"):
            raise ValueError("agent_tool_palette must be full or compact")
        return m

    @field_validator("agent_prompt_tier", mode="before")
    @classmethod
    def _norm_tier(cls, v: Any) -> Any:
        if v is None or isinstance(v, str) and not str(v).strip():
            return None
        m = str(v).strip().lower()
        if m not in ("full", "minimal", "none"):
            raise ValueError("agent_prompt_tier must be full, minimal, or none")
        return m


class AgentRuntimeConfigResolved(BaseModel):
    """Effective config after merging env defaults with stored JSON overrides."""

    model_config = {"frozen": True}

    agent_max_runs_per_hour: int = Field(ge=1, le=10_000)
    agent_max_tool_steps: int = Field(ge=1, le=100)
    agent_async_runs: bool
    agent_heartbeat_burst_per_hour: int = Field(ge=0, le=10_000)
    agent_heartbeat_enabled: bool
    agent_heartbeat_minutes: int = Field(ge=1, le=1440)
    agent_heartbeat_check_gmail: bool
    agent_tool_palette: AgentToolPalette
    agent_prompt_tier: AgentPromptTier
    agent_include_harness_facts: bool
    agent_connector_gated_tools: bool
    agent_prompted_compact_json: bool
    agent_history_turns: int = Field(ge=1, le=64)
    agent_thread_compact_after_pairs: int = Field(ge=0, le=500)
    agent_memory_flush_enabled: bool
    agent_memory_flush_max_steps: int = Field(ge=1, le=50)
    agent_memory_flush_max_transcript_chars: int = Field(ge=1000, le=500_000)
    agent_memory_post_turn_enabled: bool
    agent_memory_post_turn_mode: AgentMemoryPostTurnMode
    agent_channel_gateway_enabled: bool
    agent_email_domain_allowlist: str = ""
