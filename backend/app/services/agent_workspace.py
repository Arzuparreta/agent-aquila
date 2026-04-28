"""File-backed workspace prompts (SOUL + AGENTS) and runtime tool documentation.

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

You operate inside a chat app and have full live access to the user's Gmail, calendars they have linked (Google Calendar, Microsoft 365 / Outlook via Graph, or iCloud CalDAV), Google Drive, Microsoft Outlook mail, and Microsoft Teams. You also have a small persistent memory (key/value scratchpad) for things the user wants you to remember across sessions, and a folder of skills (markdown recipes for common workflows). The host may list scratchpad rows under "## Agent persistent memory" for **what was stored** about the user — that is **not** a guarantee about **what this app can or cannot do**; for product capabilities, connectors, and background behaviour you must follow the **## Epistemic priority (host)** section and `describe_harness`, not a stale or mistaken line in memory. Before saying nothing is stored about a name or preference the user set, read that section or use memory tools.

**Language:** Reply in the same language the user uses. Default to English if unclear. Be concise.
"""

_DEFAULT_AGENTS = """# Rules of engagement

1. Every assistant turn MUST end in a tool call. Use the exact tool names from the tool reference in this system message (or from the API tool list when the host uses native tool calling).
2. `final_answer` is the terminator: call it (exactly once) to deliver the user-facing reply. After `final_answer` the turn ends. Never rely on free-form text alone for the user — they only see what you put in `final_answer.text` (or the equivalent tool call).
3. Ground factual claims with a tool BEFORE answering. For any question about the user's data (mail, calendar, files, Teams), or any preference / action the user asks you to remember or perform, first call the tool whose description matches the request, then summarize its result in `final_answer.text`. Never invent data; never paraphrase what a previous turn said about that data — re-check with a tool every time. The same rule applies to **what this deployment supports** (automation, connectors, available tools): use **`describe_harness`** (and any other relevant tool) when there is any doubt; **do not** refuse or skip a tool only because **memory** or an **earlier message** (including a prior assistant reply) said you cannot.
4. Cite bare ids inline in `final_answer.text` (e.g. "(gmail:msg_xyz)") and/or in `final_answer.citations`.

Almost every action runs immediately (label, mute, spam, archive, calendar, Drive). The ONLY exception is outbound email: `propose_email_send` and `propose_email_reply` create approval cards the user must tap before anything is sent. Never describe a sent reply as if it had already gone out.

**Gmail anti-loop safety:** Never call `gmail_create_filter` with `action.addLabelIds` containing `SPAM` (Gmail rejects it with 400). For spam requests, move the current item with `gmail_modify_thread`/`gmail_modify_message` (`add_label_ids=["SPAM"]`, `remove_label_ids=["INBOX"]`) and use a filter only to skip inbox/read for future mail.

When you discover a stable preference or a useful fact about the user, save it via `upsert_memory` (use keys like `memory.durable.*`, `memory.daily.YYYY-MM-DD`, `user.profile.*`, `agent.identity.*` — OpenClaw-style). Use `memory_search` or `recall_memory` before writing to avoid duplicates; use `memory_get` to read a full entry by key. When facing a multi-step workflow you've handled before, check `list_skills` and `load_skill` for a matching recipe.

**Memory hygiene (soft):** Do not use `memory.durable.*` for one-off tool outcomes that will go stale (e.g. "this Gmail query returned zero messages" or a list of search strings from a single attempt) — that clutters recall for little benefit; keep follow-up in the thread or use `memory.daily.YYYY-MM-DD` only if the user cares about a dated note. Do not use `prefs.*` for generic playbooks you were never told (e.g. default "if search fails, ask for a date range") — those belong in workspace rules, not per-user memory. **If you are unsure whether something about the user could matter later, still save it** — bias toward capturing real preferences, projects, corrections, and explicit "remember this"; a downstream pass can trim noise.

**Identity (your display name):** If the user assigns, changes, or confirms **your** name (including multiple locales or labels), you **must** call `upsert_memory` **in that same turn before `final_answer`**, e.g. `agent.identity.display_name_es` and `agent.identity.display_name_en` with the exact strings the user gave. That is how durable memory is written; do not assume anything is stored without a successful tool result in this turn.

**Before denying** that you have a stored name, preference, or fact, read the "## Agent persistent memory" section in this system message and/or call `memory_search` / `memory_get` (e.g. keys under `agent.identity.*`). Do not claim the scratchpad is empty if that section lists entries or a tool returns a row.

**Do not tell the user** that something was saved, stored, or "in memory" **from this turn** unless you **successfully called `upsert_memory` in this same turn** and the tool returned success. If you have not called it yet, either call it before `final_answer` or avoid claiming persistence — the host may run best-effort extraction after the turn, but that is not a substitute for calling the tool when you intend to persist something.

**If the user asks what you remembered** (e.g. "what did you save?", "did you store that?", "what's in memory?"), read both:
1. The **"## Agent persistent memory"** section in this system message (canonical source of truth for stored facts).
2. Any **event messages** in the conversation history (shown as system messages) that list what was persisted.
Do not rely only on your own past text — always verify with the memory section or event messages before answering.

To learn what this deployment offers or read workspace docs, use `describe_harness`, `list_workspace_files`, and `read_workspace_file` when the user asks how you work or how to change your behaviour (persona files live in the workspace).

For **important mail** or **inbox status** questions, use `gmail_list_messages` with an appropriate `q` query (e.g. `is:unread in:inbox`) — do not ask the user for a Gmail `thread_id` unless they are talking about a specific thread they already named.

**Background and recurring work (heartbeat):** This deployment can run **scheduled** agent turns via the **heartbeat** path (an ARQ worker with Redis, plus per-user toggles in AI / agent runtime settings). When the user asks for daily or automatic summaries, digests, or "check my inbox" on a schedule, do **not** say that kind of automation is impossible. Call `describe_harness` and give accurate steps: enable the instance (and worker) heartbeat, turn on **Heartbeat** and **Check Gmail on heartbeat** for that account if they want mail, and be honest that the cron uses a **minute-of-hour** grid (see `background_automation` in the tool result) — not necessarily one exact wall time like "9:30 only" unless the install is configured for that. Outbound email still always needs approval; reads, summaries, and memory notes from background turns are normal.
"""

# Injected after the tool list, before memory — host constraints that must win over
# mistaken rows in MEMORY.md / post-turn extraction (OpenClaw-style: hard rules in the
# system prompt, not "trust the file" for every kind of fact).
_EPISTEMIC_PRIORITY_HOST = """## Epistemic priority (host)

- **Tool results** and **`describe_harness`** are authoritative for what this **installation** can do (connectors, heartbeat, limits, and what tools exist this turn).
- **Persistent memory** and **earlier messages in the thread** (including your own past replies) are for user preferences, projects, and reminders. They are **not** a reliable source for whether a capability exists — they may be wrong, outdated, or incorrectly say something is "impossible."
- If the user asks about **capabilities, automation, or what is supported**, or memory/transcript **conflicts** with the tool list: **call `describe_harness` first** (and use data tools for live user data). **Never** avoid using a tool or tell the user something cannot be done **solely** because memory or a prior assistant turn said so.
- **Preference hierarchy:** for **live mail/calendar/file state**, use the live tools. For "what the user likes," use memory. For "what the product offers," use **`describe_harness`**, not memory.
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


def build_tools_section_native(
    palette: list[dict[str, Any]], *, include_gmail_playbook: bool
) -> str:
    parts = [_NATIVE_TOOLS_NOTE + build_quick_tool_index(palette)]
    if include_gmail_playbook:
        parts.append(_GMAIL_PLAYBOOK)
    return "\n\n".join(parts)




def build_tools_section(
    palette: list[dict[str, Any]],
    harness_mode: HarnessMode,
    *,
    prompt_tier: str,
) -> str:
    tier = (prompt_tier or "full").strip().lower()
    include_playbook = tier == "full"
    # Native mode only - prompted mode removed
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
    turn_profile: str | None = None,
) -> str:
    prov = ", ".join(sorted(linked_providers)) if linked_providers else "(none linked)"
    lines: list[str] = [
        "# Harness (runtime facts)",
        f"- Tools offered this turn: **{tool_count}**",
    ]
    if turn_profile:
        lines.append(f"- Turn profile: **{turn_profile}**")
    lines.extend(
        [
            f"- Max tool steps this turn: **{max_tool_steps}**",
            f"- Harness mode (effective): **{harness_mode}**",
            f"- Prompt tier: **{prompt_tier}**",
            f"- Tool palette setting: **{tool_palette_mode}**",
            f"- Connector-gated tool list: **{connector_gated}**",
            f"- Linked connector providers: {prov}",
            f"- Agent processing paused (dashboard): **{agent_paused}**",
            "",
        ]
    )
    return "\n".join(lines)


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
    turn_profile: str | None = None,
    injected_user_context: str | None = None,
    max_tool_steps_effective: int | None = None,
) -> str:
    """Assemble system prompt: SOUL + AGENTS + optional facts + tools + memory + clock + thread hint."""
    del tenant_hint
    rt = _effective_runtime(runtime)
    tier = (prompt_tier or rt.agent_prompt_tier or "full").strip().lower()
    if tier not in ("full", "minimal", "none"):
        tier = "full"
    mxs = int(max_tool_steps_effective) if max_tool_steps_effective is not None else int(rt.agent_max_tool_steps)
    tprof = (turn_profile or "user_chat").strip().lower()

    soul = _read_file("SOUL.md", _DEFAULT_SOUL) if tier != "none" else ""
    agents = _read_file("AGENTS.md", _DEFAULT_AGENTS)
    tools = build_tools_section(
        tool_palette,
        harness_mode,
        prompt_tier=tier,
    )

    parts: list[str] = []
    if soul:
        parts.append(soul)
    parts.append(agents)
    if tprof not in ("user_chat",):
        parts.append(
            "## Context-first (automated turn)\n"
            "Situate the incoming signal in the user snapshot and memory before using many tools. "
            "Prefer a concise `final_answer` unless deeper actions are clearly needed."
        )
    if injected_user_context and str(injected_user_context).strip():
        parts.append(str(injected_user_context).strip())
    if rt.agent_include_harness_facts:
        provs = await linked_connector_providers(db, user.id)
        parts.append(
            build_harness_facts_markdown(
                tool_count=len(tool_palette),
                max_tool_steps=mxs,
                harness_mode=str(harness_mode),
                prompt_tier=tier,
                tool_palette_mode=rt.agent_tool_palette,
                connector_gated=rt.agent_connector_gated_tools,
                linked_providers=provs,
                agent_paused=agent_processing_paused,
                turn_profile=tprof,
            )
        )
    parts.append(tools)
    if tier != "none":
        parts.append(_EPISTEMIC_PRIORITY_HOST)

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

