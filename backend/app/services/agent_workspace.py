"""File-backed workspace prompts (OpenClaw-style SOUL + AGENTS) + tool docs.

``SOUL.md`` and ``AGENTS.md`` live under ``backend/agent_workspace/`` by default
(or ``AQUILA_WORKSPACE_DIR``). The tool catalog is generated at runtime from the
live ``AGENT_TOOLS`` palette so it always matches dispatch.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.connector_connection import ConnectorConnection
from app.models.user import User
from app.schemas.agent_runtime_config import AgentRuntimeConfigResolved
from app.services.agent_harness.selector import HarnessMode
from app.services.agent_memory_service import AgentMemoryService
from app.services.agent_runtime_config_service import merge_stored_with_env
from app.services.user_time_context import build_datetime_context_section, normalize_time_format


def _effective_runtime(rt: AgentRuntimeConfigResolved | None) -> AgentRuntimeConfigResolved:
    return rt if rt is not None else merge_stored_with_env(None)

_DEFAULT_SOUL = """# Persona

You are the user's personal operations agent. The user is NON-TECHNICAL — never mention APIs, OAuth, JSON, model names, or any internal implementation. Speak like a friendly colleague.

You operate inside a chat app and have full live access to the user's Gmail, Google Calendar, Google Drive, Microsoft Outlook, and Microsoft Teams. You also have a small persistent memory (key/value scratchpad) for things the user wants you to remember across sessions, and a folder of skills (markdown recipes for common workflows). The host may inject existing scratchpad rows into your system message under "## Agent persistent memory" — treat that as ground truth before saying nothing is stored.

**Language:** Reply in the same language the user uses. Default to Spanish if unclear. Be concise.
"""

_DEFAULT_AGENTS = """# Rules of engagement

1. Every assistant turn MUST end in a tool call. Use the exact tool names from the tool reference in this system message (or from the API tool list when the host uses native tool calling).
2. `final_answer` is the terminator: call it (exactly once) to deliver the user-facing reply. After `final_answer` the turn ends. Never rely on free-form text alone for the user — they only see what you put in `final_answer.text` (or the equivalent tool call).
3. Ground factual claims with a tool BEFORE answering. For any question about the user's data (mail, calendar, files, Teams), or any preference / action the user asks you to remember or perform, first call the tool whose description matches the request, then summarize its result in `final_answer.text`. Never invent data; never paraphrase what a previous turn said about that data — re-check with a tool every time.
4. Cite bare ids inline in `final_answer.text` (e.g. "(gmail:msg_xyz)") and/or in `final_answer.citations`.

Almost every action runs immediately (label, mute, spam, archive, calendar, Drive). The ONLY exception is outbound email: `propose_email_send` and `propose_email_reply` create approval cards the user must tap before anything is sent. Never describe a sent reply as if it had already gone out.

When you discover a stable preference or a useful fact about the user, save it via `upsert_memory` (use keys like `memory.durable.*`, `memory.daily.YYYY-MM-DD`, `user.profile.*`, `agent.identity.*` — OpenClaw-style). Use `memory_search` or `recall_memory` before writing to avoid duplicates; use `memory_get` to read a full entry by key. When facing a multi-step workflow you've handled before, check `list_skills` and `load_skill` for a matching recipe.

**Before denying** that you have a stored name, preference, or fact, read the "## Agent persistent memory" section in this system message and/or call `memory_search` / `memory_get` (e.g. keys under `agent.identity.*`). Do not claim the scratchpad is empty if that section lists entries or a tool returns a row.

**Do not tell the user** that something was saved, stored, or "in memory" **from this turn** unless you **successfully called `upsert_memory` in this same turn** and the tool returned success. If you have not called it yet, either call it before `final_answer` or avoid claiming persistence — the host may still extract some facts automatically after the turn, but you must not promise that without a successful tool result.

To learn what this deployment offers or read workspace docs, use `describe_harness`, `list_workspace_files`, and `read_workspace_file` when the user asks how you work or how to change your behaviour (persona files live in the workspace).

For **important mail** or **inbox status** questions, use `gmail_list_messages` with an appropriate `q` query (e.g. `is:unread in:inbox`) — do not ask the user for a Gmail `thread_id` unless they are talking about a specific thread they already named.
"""

_GMAIL_PLAYBOOK = """# Gmail playbook

The Gmail tools are thin wrappers over Google's search syntax — favour `q=` over fetching everything and filtering yourself.

- "¿Tengo correos sin leer?" → `gmail_list_messages` with `q="is:unread in:inbox"`, `max_results=10`.
- "Buscar correos de Bob de la última semana" → `gmail_list_messages` with `q="from:bob newer_than:7d"`.
- "Léeme este correo" (with `gmail_msg` in context) → `gmail_get_message` with that id and `format="full"`.
- "Archiva esto" → `gmail_modify_message` with `remove_label_ids=["INBOX"]`.
- "Márcalo como leído" → `gmail_modify_message` with `remove_label_ids=["UNREAD"]`.
- "Silencia a este remitente" → `gmail_silence_sender` with `email` and `mode="mute"`, or `gmail_create_filter` with `action={"removeLabelIds": ["INBOX","UNREAD"]}` plus `gmail_modify_thread` on the current thread.
- "Mándalo a spam" → `gmail_modify_thread` (or `gmail_modify_message`) with `add_label_ids=["SPAM"]`, `remove_label_ids=["INBOX"]` on the current item, then `gmail_silence_sender` with `mode="spam"` and the same `thread_id`/`message_id` so a filter also skips inbox for future mail. **Never** put `SPAM` in a filter `addLabelIds` — Gmail rejects it.
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
{{"name": "TOOL_NAME", "arguments": {{ ... }}}}
</tool_call>

- Use only tool names from the **Available tools (JSON)** section below.
- To show the user your reply, call the tool named `final_answer` with `arguments` like `{{"text": "...", "citations": []}}`.
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


def workspace_dir() -> Path:
    """Public root for SOUL.md / AGENTS.md (same as internal resolver)."""
    return _workspace_dir()


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


def palette_to_prompt_json(palette: list[dict[str, Any]], *, compact: bool) -> str:
    """Serialize tool definitions for prompted-mode system embed (optionally trimmed)."""
    if not compact:
        return json.dumps(palette, ensure_ascii=False, indent=2)
    slim: list[dict[str, Any]] = []
    for t in palette:
        fn = (t.get("function") or {}) if isinstance(t, dict) else {}
        name = str(fn.get("name") or "").strip()
        desc = str(fn.get("description") or "").replace("\n", " ").strip()
        if len(desc) > 280:
            desc = desc[:277] + "…"
        params = fn.get("parameters") if isinstance(fn.get("parameters"), dict) else {}
        slim.append(
            {
                "type": "function",
                "function": {"name": name, "description": desc, "parameters": params},
            }
        )
    return json.dumps(slim, ensure_ascii=False, separators=(",", ":"))


def build_tools_section_native(
    palette: list[dict[str, Any]], *, include_gmail_playbook: bool
) -> str:
    parts = [_NATIVE_TOOLS_NOTE + build_quick_tool_index(palette)]
    if include_gmail_playbook:
        parts.append(_GMAIL_PLAYBOOK)
    return "\n\n".join(parts)


def build_tools_section_prompted(
    palette: list[dict[str, Any]], *, include_gmail_playbook: bool, compact_json: bool
) -> str:
    tool_json = palette_to_prompt_json(palette, compact=compact_json)
    parts = [_PROMPTED_TOOL_INSTRUCTIONS.format(tool_json=tool_json)]
    if include_gmail_playbook:
        parts.append(_GMAIL_PLAYBOOK)
    return "\n\n".join(parts)


def build_tools_section(
    palette: list[dict[str, Any]],
    harness_mode: HarnessMode,
    *,
    prompt_tier: str,
    prompted_compact_json: bool,
) -> str:
    tier = (prompt_tier or "full").strip().lower()
    include_playbook = tier == "full"
    if harness_mode == "prompted":
        return build_tools_section_prompted(
            palette, include_gmail_playbook=include_playbook, compact_json=prompted_compact_json
        )
    return build_tools_section_native(palette, include_gmail_playbook=include_playbook)


def build_harness_facts_markdown(
    *,
    tool_count: int,
    max_tool_steps: int,
    harness_mode: str,
    prompt_tier: str,
    tool_palette_mode: str,
    connector_gated: bool,
    linked_providers: list[str],
    agent_paused: bool,
) -> str:
    prov = ", ".join(sorted(linked_providers)) if linked_providers else "(none linked)"
    return "\n".join(
        [
            "# Harness (runtime facts)",
            f"- Tools offered this turn: **{tool_count}**",
            f"- Max tool steps per turn: **{max_tool_steps}**",
            f"- Harness mode (effective): **{harness_mode}**",
            f"- Prompt tier: **{prompt_tier}**",
            f"- Tool palette setting: **{tool_palette_mode}**",
            f"- Connector-gated tool list: **{connector_gated}**",
            f"- Linked connector providers: {prov}",
            f"- Agent processing paused (dashboard): **{agent_paused}**",
            "",
        ]
    )


async def linked_connector_providers(db: AsyncSession, user_id: int) -> list[str]:
    r = await db.execute(
        select(ConnectorConnection.provider).where(ConnectorConnection.user_id == user_id)
    )
    return sorted({row[0] for row in r.all() if row[0]})


def _safe_rel_path(raw: str) -> Path | None:
    p = Path((raw or "").strip())
    if p.is_absolute() or ".." in p.parts:
        return None
    return p


def list_allowed_workspace_files(*, skills_root: Path) -> list[dict[str, str]]:
    """Non-recursive listing of `.md` files under workspace + skills roots."""
    ws = _workspace_dir().resolve()
    sk = skills_root.resolve()
    out: list[dict[str, str]] = []
    for label, root in (("workspace", ws), ("skills", sk)):
        if not root.is_dir():
            continue
        try:
            for child in sorted(root.iterdir()):
                if child.is_file() and child.suffix.lower() == ".md":
                    rel = child.name
                    out.append({"area": label, "path": rel, "name": child.name})
        except OSError:
            continue
    return out


def read_allowed_workspace_file(rel: str, *, skills_root: Path) -> str | None:
    """Read a single `.md` file if it lives directly under workspace or skills root."""
    path = _safe_rel_path(rel)
    if path is None or len(path.parts) != 1:
        return None
    name = path.name
    if Path(name).suffix.lower() != ".md":
        return None
    ws = _workspace_dir().resolve()
    sk = skills_root.resolve()
    for root in (ws, sk):
        candidate = (root / name).resolve()
        try:
            if candidate.is_file() and candidate.parent == root:
                return candidate.read_text(encoding="utf-8")
        except OSError:
            continue
    return None


async def build_system_prompt(
    db: AsyncSession,
    user: User,
    *,
    tool_palette: list[dict[str, Any]],
    harness_mode: HarnessMode,
    thread_context_hint: str | None = None,
    tenant_hint: str | None = None,
    user_timezone: str | None = None,
    time_format: str = "auto",
    prompt_tier: str | None = None,
    agent_processing_paused: bool = False,
    runtime: AgentRuntimeConfigResolved | None = None,
) -> str:
    """Assemble system prompt: SOUL + AGENTS + optional facts + tools + memory + clock + thread hint."""
    del tenant_hint
    rt = _effective_runtime(runtime)
    tier = (prompt_tier or rt.agent_prompt_tier or "full").strip().lower()
    if tier not in ("full", "minimal", "none"):
        tier = "full"

    soul = _read_file("SOUL.md", _DEFAULT_SOUL) if tier != "none" else ""
    agents = _read_file("AGENTS.md", _DEFAULT_AGENTS)
    tools = build_tools_section(
        tool_palette,
        harness_mode,
        prompt_tier=tier,
        prompted_compact_json=rt.agent_prompted_compact_json,
    )

    parts: list[str] = []
    if soul:
        parts.append(soul)
    parts.append(agents)
    if rt.agent_include_harness_facts:
        provs = await linked_connector_providers(db, user.id)
        parts.append(
            build_harness_facts_markdown(
                tool_count=len(tool_palette),
                max_tool_steps=rt.agent_max_tool_steps,
                harness_mode=str(harness_mode),
                prompt_tier=tier,
                tool_palette_mode=rt.agent_tool_palette,
                connector_gated=rt.agent_connector_gated_tools,
                linked_providers=provs,
                agent_paused=agent_processing_paused,
            )
        )
    parts.append(tools)

    if tier != "none":
        memory_blob = await AgentMemoryService.recent_for_prompt(db, user)
        if memory_blob:
            parts.append(memory_blob)

    parts.append(
        build_datetime_context_section(
            user_timezone=user_timezone,
            time_format=normalize_time_format(time_format),
        )
    )
    if thread_context_hint:
        parts.append(f"Thread context: {thread_context_hint.strip()}")
    return "\n\n".join(parts)

_MEMORY_FLUSH_RULES = """# Memory flush (internal)

This turn runs **before** older chat turns are dropped from context (OpenClaw-style compaction). Persist **durable** facts and preferences so they are not lost.

- Use ``memory_search`` / ``recall_memory`` or ``list_memory`` to avoid duplicating existing notes.
- Use ``upsert_memory`` with keys such as:
  - ``memory.durable.*`` — long-term facts (OpenClaw ``MEMORY.md``).
  - ``memory.daily.YYYY-MM-DD`` — day-scoped notes (OpenClaw ``memory/YYYY-MM-DD.md``).
  - ``user.profile.*`` — identity and preferences (OpenClaw ``USER.md``).
- Keep entries short; update existing keys when possible.
- Finish with ``final_answer`` and a one-line summary (e.g. "Saved 2 notes" or "nothing to save") in the user's language.
"""


async def build_memory_flush_system_prompt(
    db: AsyncSession,
    user: User,
    *,
    tool_palette: list[dict[str, Any]],
    harness_mode: HarnessMode,
    user_timezone: str | None = None,
    time_format: str = "auto",
    prompt_tier: str = "minimal",
    runtime: AgentRuntimeConfigResolved | None = None,
) -> str:
    """Short system prompt for memory-only compaction flush runs."""
    rt = _effective_runtime(runtime)
    tier = (prompt_tier or "minimal").strip().lower()
    if tier not in ("full", "minimal", "none"):
        tier = "minimal"
    tools = build_tools_section(
        tool_palette,
        harness_mode,
        prompt_tier=tier,
        prompted_compact_json=rt.agent_prompted_compact_json,
    )
    parts: list[str] = [_MEMORY_FLUSH_RULES, tools]
    if tier != "none":
        memory_blob = await AgentMemoryService.recent_for_prompt(db, user)
        if memory_blob:
            parts.append(memory_blob)
    parts.append(
        build_datetime_context_section(
            user_timezone=user_timezone,
            time_format=normalize_time_format(time_format),
        )
    )
    return "\n\n".join(parts)
