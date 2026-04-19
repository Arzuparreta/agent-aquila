"""Parse tool calls from model text (Qwen3 / Hermes-style ``<tool_call>`` tags)."""

from __future__ import annotations

import json
import re
from typing import Any

from app.services.llm_client import ChatToolCall, parse_json_object

_TOOL_CALL_BLOCK = re.compile(
    r"<tool_call>\s*(\{[\s\S]*?\})\s*</tool_call>",
    re.IGNORECASE,
)


def parse_tool_calls_from_content(content: str) -> tuple[list[ChatToolCall], list[str]]:
    """Extract ``ChatToolCall`` rows from assistant text; collect non-fatal parse notes."""
    errors: list[str] = []
    calls: list[ChatToolCall] = []
    text = content or ""
    for i, m in enumerate(_TOOL_CALL_BLOCK.finditer(text)):
        raw_json = m.group(1).strip()
        data = parse_json_object(raw_json)
        if not data:
            errors.append(f"<tool_call> block {i}: invalid JSON")
            continue
        name = str(data.get("name") or "").strip()
        if not name:
            errors.append(f"<tool_call> block {i}: missing name")
            continue
        args = data.get("arguments")
        if args is None:
            args = {k: v for k, v in data.items() if k != "name"}
        if not isinstance(args, dict):
            errors.append(f"<tool_call> block {i}: arguments must be an object")
            args = {}
        calls.append(
            ChatToolCall(
                id=f"prompted_{i}",
                name=name,
                arguments=args,
                raw_arguments=json.dumps(args, ensure_ascii=False),
            )
        )
    if not calls and text.strip():
        data = parse_json_object(text)
        if data and str(data.get("name") or "").strip():
            name = str(data["name"]).strip()
            args = data.get("arguments")
            if not isinstance(args, dict):
                args = {}
            calls.append(
                ChatToolCall(
                    id="prompted_0",
                    name=name,
                    arguments=args,
                    raw_arguments=json.dumps(args, ensure_ascii=False),
                )
            )
        elif text.strip():
            errors.append("no valid <tool_call>{...}</tool_call> blocks found")
    return calls, errors


def format_tool_results_for_prompt(
    calls: list[ChatToolCall],
    results: list[dict[str, Any]],
) -> str:
    """User-turn text that carries tool outputs back to the model in prompted mode."""
    payload: list[dict[str, Any]] = []
    for call, res in zip(calls, results):
        payload.append({"name": call.name, "tool_call_id": call.id, "result": res})
    return (
        "<tool_response>\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
        + "\n</tool_response>\n\n"
        "Continue with the next <tool_call> or call final_answer when ready."
    )
