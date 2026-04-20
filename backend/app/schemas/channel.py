"""Channel-agnostic messages for gateway / multi-channel integration."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class ChannelKind(str, Enum):
    """Stable identifiers for adapters (gateway, future Telegram/Slack, etc.)."""

    web = "web"
    gateway_stub = "gateway_stub"
    telegram = "telegram"
    slack = "slack"


class ChannelInboundMessage(BaseModel):
    """Inbound user text from any channel surface."""

    channel: ChannelKind = Field(description="Which adapter produced this message.")
    external_key: str = Field(
        max_length=512,
        description="Stable id for the remote conversation (chat id, channel+thread, etc.).",
    )
    text: str = Field(min_length=1, max_length=16000)


class ChannelDeliverResult(BaseModel):
    """Result of running the agent for one inbound channel message."""

    run_id: int
    chat_thread_id: int
    root_trace_id: str | None = None
    status: str
