"""Turn profile strings for harness routing, tool scoping, and observability."""

from __future__ import annotations

from typing import Literal

AgentTurnProfile = Literal[
    "user_chat",
    "channel_inbound",
    "heartbeat",
    "automation",
]

TURN_PROFILE_USER_CHAT: AgentTurnProfile = "user_chat"
TURN_PROFILE_CHANNEL_INBOUND: AgentTurnProfile = "channel_inbound"
TURN_PROFILE_HEARTBEAT: AgentTurnProfile = "heartbeat"
TURN_PROFILE_AUTOMATION: AgentTurnProfile = "automation"

ALL_TURN_PROFILES: tuple[str, ...] = (
    "user_chat",
    "channel_inbound",
    "heartbeat",
    "automation",
)


def normalize_turn_profile(raw: str | None) -> str:
    s = (raw or TURN_PROFILE_USER_CHAT).strip().lower()
    return s if s in ALL_TURN_PROFILES else TURN_PROFILE_USER_CHAT
