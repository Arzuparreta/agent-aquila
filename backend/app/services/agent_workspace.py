"""File-backed workspace prompts (OpenClaw-style SOUL + AGENTS) + tool docs.

``SOUL.md`` and ``AGENTS.md`` live under ``backend/agent_workspace/`` by default
(or ``AQUILA_WORKSPACE_DIR``). The tool catalog is generated at runtime from the
live ``AGENT_TOOLS`` palette so it always matches dispatch.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.user import User
from app.services.agent_harness.selector import HarnessMode
from app.services.agent_memory_service import AgentMemoryService

_DEFAULT_SOUL = """# Persona

You are the user's personal operations agent. The user is NON-TECHNICAL — never mention APIs, OAuth, JSON, model names, or any internal implementation. Speak like a friendly colleague.

You operate inside a chat app and have full live access to the user's Gmail, Google Calendar, Google Drive, Microsoft Outlook, and Microsoft Teams. You also have a small persistent memory (key/value scratchpad) for things the user wants you to remember across sessions, and a folder of skills (markdown recipes for common workflows).

**Language:** Reply in the same language the user uses. Default to Spanish if unclear. Be concise.
"""

_DEFAULT_AGENTS = """# Rules of engagement

1. Every assistant turn MUST end in a tool call. Use the exact tool names from the tool reference in this system message (or from the API tool list when the host uses native tool calling).
2. `final_answer` is the terminator: call it (exactly once) to deliver the user-facing reply. After `final_answer` the turn ends. Never rely on free-form text alone for the user — they only see what you put in `final_answer.text` (or the equivalent tool call).
3. Ground factual claims with a tool BEFORE answering. For any question about the user's data (mail, calendar, files, Teams), or any preference / action the user asks you to remember or perform, first call the tool whose description matches the request, then summarize its result in `final_answer.text`. Never invent data; never paraphrase what a previous turn said about that data — re-check with a tool every time.
4. Cite bare ids inline in `final_answer.text` (e.g. "(gmail:msg_xyz)") and/or in `final_answer.citations`.

Almost every action runs immediately (label, mute, spam, archive, calendar, Drive). The ONLY exception is outbound email: `propose_email_send` and `propose_email_reply` create approval cards the user must tap before anything is sent. Never describe a sent reply as if it had already gone out.

When you discover a stable preference or a useful fact about the user, save it via `upsert_memory` so future turns benefit. When facing a multi-step workflow you've handled before, check `list_skills` and `load_skill` for a matching recipe.

For **important mail** or **inbox status** questions, use `gmail_list_messages` with an appropriate `q` query (e.g. `is:unread in:inbox`) — do not ask the user for a Gmail `thread_id` unless they are talking about a specific thread they already named.
"""

_GMAIL_PLAYBOOK = """# Gmail playbook

The Gmail tools are thin wrappers over Google's search syntax — favour `q=` over fetching everything and filtering yourself.

- "¿Tengo correos sin leer?" → `gmail_list_messages` with `q="is:unread in:inbox"`, `max_results=10`.
- "Buscar correos de Bob de la última semana" → `gmail_list_messages` with `q="from:bob newer_than:7d"`.
- "Léeme este correo" (with `gmail_msg` in context) → `gmail_get_message` with that id and `format="full"`.
- "Archiva esto" → `gmail_modify_message` with `remove_label_ids=["INBOX"]`.
- "Márcalo como leído" → `gmail_modify_message` with `remove_label_ids=["UNREAD"]`.
- "Silencia a este remitente" → `gmail_create_filter` with `criteria={"from": "<email>"}` and `action={"removeLabelIds": ["INBOX","UNREAD"]}`; then `gmail_modify_thread` to apply it to the current thread too.
- "Mándalo a spam" → same filter shape but `action={"addLabelIds":["SPAM"], "removeLabelIds":["INBOX"]}`.
- "Borra esto" → `gmail_trash_message` (the user can still recover it from Gmail's trash).

If a tool returns `"error"` containing `gmail_rate_limited` or `upstream 429`, stop calling Gmail tools this turn and answer with a short note that Gmail is throttling and you'll retry shortly. Do NOT loop on the same tool — wait the suggested seconds.
"""

_NATIVE_TOOLS_NOTE = """# Tool reference (native)

Full JSON Schemas for each tool are supplied separately by the host API (`tools` parameter). Use the **exact** tool `name` strings shown in the quick index below. Prefer reading each tool's description in the API schema when choosing arguments.

## Quick index
"""


_PROMPTED_TOOL_INSTRUCTIONS = """# Tool calling (prompted mode)

The API may not expose tools separately. You **must** invoke tools by emitting one or more blocks in this exact shape (JSON object inside the tags, valid JSON only):

<tool_call>
{"name": "TOOL_NAME", "arguments": { ... }}
</tool_call>

- Use only tool names from the **Available tools (JSON)** section below.
- To show the user your reply, call the tool named `final_answer` with `arguments` like `{"text": "...", "citations": []}`.
- You may emit multiple `<tool_call>` blocks in one assistant message if the host allows multiple steps; otherwise emit one at a time.
- Do not wrap JSON in markdown code fences inside `<tool_call>`.

## Available tools (JSON)

The following definitions mirror the host tool schemas:

```json
{tool_json}
```

"""


def _workspace_dir() -> Path:
    custom = getattr(settings, "workspace_dir", "") or ""
    if custom:
        p = Path(custom).expanduser().resolve()
        if p.is_dir():
            return p
    return Path(__file__).resolve().parents[2] / "agent_workspace"


def _read_file(name: str, default: str) -> str:
    path = _workspace_dir() / name
    try:
        if path.is_file():
            return path.read_text(encoding="utf-8").strip()
    except OSError:
        pass
    return default.strip()


def build_quick_tool_index(palette: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for t in palette:
        fn = (t.get("function") or {}) if isinstance(t, dict) else {}
        n = str(fn.get("name") or "").strip()
        if not n:
            continue
        desc = str(fn.get("description") or "").strip()
        short = desc.replace("\n", " ")
        if len(short) > 160:
            short = short[:157] + "…"
        lines.append(f"- `{n}` — {short}")
    return "\n".join(lines) if lines else "(no tools)"


def build_tools_section_native(palette: list[dict[str, Any]]) -> str:
    return "\n\n".join(
        [
            _NATIVE_TOOLS_NOTE + build_quick_tool_index(palette),
            _GMAIL_PLAYBOOK,
        ]
    )


def build_tools_section_prompted(palette: list[dict[str, Any]]) -> str:
    tool_json = json.dumps(palette, ensure_ascii=False, indent=2)
    return "\n\n".join(
        [
            _PROMPTED_TOOL_INSTRUCTIONS.format(tool_json=tool_json),
            _GMAIL_PLAYBOOK,
        ]
    )


def build_tools_section(
    palette: list[dict[str, Any]],
    harness_mode: HarnessMode,
) -> str:
    if harness_mode == "prompted":
        return build_tools_section_prompted(palette)
    return build_tools_section_native(palette)


async def build_system_prompt(
    db: AsyncSession,
    user: User,
    *,
    tool_palette: list[dict[str, Any]],
    harness_mode: HarnessMode,
    thread_context_hint: str | None = None,
    tenant_hint: str | None = None,
) -> str:
    """Assemble system prompt: SOUL + AGENTS + tools + memory + thread hint."""
    del tenant_hint
    soul = _read_file("SOUL.md", _DEFAULT_SOUL)
    agents = _read_file("AGENTS.md", _DEFAULT_AGENTS)
    tools = build_tools_section(tool_palette, harness_mode)
    parts = [soul, agents, tools]
    memory_blob = await AgentMemoryService.recent_for_prompt(db, user)
    if memory_blob:
        parts.append(memory_blob)
    if thread_context_hint:
        parts.append(f"Thread context: {thread_context_hint.strip()}")
    return "\n\n".join(parts)
