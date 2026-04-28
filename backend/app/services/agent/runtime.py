"""Runtime helpers for agent."""
from typing import Any
from app.services.agent.harness.effective import (
    resolve_max_tool_steps_for_turn as _resolve_max_steps
)

def estimate_message_tokens(messages):
    return sum(len(str(m.get("content") or "")) // 4 for m in messages)

def plan_budget(messages, limits, requested_output_tokens=None):
    from dataclasses import dataclass
    @dataclass
    class Budget:
        input_budget: int
        reserved_output_tokens: int
        compacted: bool = False
    return Budget(input_budget=10000, reserved_output_tokens=2000)

def clamp_tool_content_by_tokens(content, max_tokens):
    return content

def content_sha256_preview(content):
    import hashlib
    return hashlib.sha256(content.encode()).hexdigest()[:16]

class NoActiveProviderError(Exception):
    pass

class LLMProviderError(Exception):
    def __init__(self, provider, message, hint):
        self.provider = provider
        self.message = message
        self.hint = hint
    def to_dict(self):
        return {"provider": self.provider, "message": self.message, "hint": self.hint}

# Type imports
if False:
    from app.services.agent_runtime_config_service import (
        UserAISettingsService,
    )
