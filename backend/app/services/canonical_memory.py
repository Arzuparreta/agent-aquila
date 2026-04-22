"""Per-user OpenClaw-style canonical markdown memory (source of truth for prompt injection).

Layout under ``<user_data_dir>/users/<user_id>/memory_workspace/``:

- ``MEMORY.md`` — long-term agent notes (maps keys ``memory.durable.*``, ``agent.identity.*``, etc.)
- ``USER.md`` — user profile (``user.profile.*``)
- ``memory/YYYY-MM-DD.md`` — daily notes (``memory.daily.YYYY-MM-DD``)
- ``DREAMS.md`` — human-readable consolidation / digest output (not used for key-value tool sync)
- ``rubric.json`` — dynamic importance rubric (see :mod:`app.services.agent_rubric`)

Machine-parseable lines live between ``<!-- aqv1 -->`` and ``<!-- /aqv1 -->`` markers. Each line:
``key|importance|content`` (content may contain ``\\n`` for newlines).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.models.user import User

logger = logging.getLogger(__name__)

_AQ_BEGIN = "<!-- aqv1 -->"
_AQ_END = "<!-- /aqv1 -->"
_LINE_RE = re.compile(
    r"^([^|]+)\|(\d{1,2})\|(.*)$"
)

_DEFAULT_MEMORY = """# Long-term memory (MEMORY)

Durable facts, decisions, and environment notes. The host keeps structured rows between the markers; you may add freeform markdown outside them.

{markers}
"""

_DEFAULT_USER = """# User profile (USER)

User preferences, identity, and communication style.

{markers}
"""

_DEFAULT_DREAMS = """# Dreams / consolidation diary

Autonomous memory consolidation and digest entries are appended here for review.
"""

_DAILY_NOTES = """# Daily notes ({day})

{markers}
"""


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[2]


def user_data_root() -> Path:
    custom = (getattr(settings, "aquila_user_data_dir", None) or "").strip()
    if custom:
        return Path(custom).expanduser().resolve()
    return _backend_root() / "data"


def memory_workspace_dir(user_id: int) -> Path:
    return user_data_root() / "users" / str(int(user_id)) / "memory_workspace"


def _today_utc() -> date:
    return datetime.now(UTC).date()


def _ensure_file(path: Path, default_body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file():
        path.write_text(default_body, encoding="utf-8")


def ensure_user_memory_layout(user_id: int) -> Path:
    """Create MEMORY.md, USER.md, DREAMS.md, and ``memory/`` if missing. Returns workspace root."""
    root = memory_workspace_dir(user_id)
    mem = root / "MEMORY.md"
    usr = root / "USER.md"
    dreams = root / "DREAMS.md"
    daily_dir = root / "memory"
    daily_dir.mkdir(parents=True, exist_ok=True)

    markers = f"{_AQ_BEGIN}\n{_AQ_END}\n"
    _ensure_file(mem, _DEFAULT_MEMORY.format(markers=markers))
    _ensure_file(usr, _DEFAULT_USER.format(markers=markers))
    _ensure_file(dreams, _DEFAULT_DREAMS + "\n")
    return root


def _read_body(path: Path) -> str:
    try:
        if path.is_file():
            return path.read_text(encoding="utf-8")
    except OSError:
        pass
    return ""


def _parse_kv_block(text: str) -> list[tuple[str, int, str]]:
    out: list[tuple[str, int, str]] = []
    if _AQ_BEGIN not in text or _AQ_END not in text:
        return out
    try:
        inner = text.split(_AQ_BEGIN, 1)[1].split(_AQ_END, 1)[0]
    except IndexError:
        return out
    for line in inner.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _LINE_RE.match(line)
        if not m:
            continue
        key, imp_s, content = m.group(1).strip(), m.group(2), m.group(3)
        try:
            imp = max(0, min(10, int(imp_s)))
        except ValueError:
            imp = 0
        out.append((key, imp, content.replace("\\n", "\n")))
    return out


def _serialize_kv_block(rows: list[tuple[str, int, str]]) -> str:
    lines = []
    for key, imp, content in rows:
        safe = (content or "").replace("\n", "\\n")
        lines.append(f"{key.strip()}|{imp}|{safe}")
    body = "\n".join(lines)
    return f"{_AQ_BEGIN}\n{body}\n{_AQ_END}\n" if body else f"{_AQ_BEGIN}\n{_AQ_END}\n"


def _replace_kv_in_markdown(text: str, new_block: str) -> str:
    """``new_block`` is the full serialized block including ``<!-- aqv1 -->`` markers."""
    if _AQ_BEGIN in text and _AQ_END in text:
        before, rest = text.split(_AQ_BEGIN, 1)
        _, after = rest.split(_AQ_END, 1)
        return f"{before}{new_block}{after}"
    return f"{text.rstrip()}\n\n{new_block}\n"


def _target_path_for_key(user_id: int, key: str) -> tuple[Path, str]:
    k_raw = (key or "").strip()
    k = k_raw.lower()
    root = ensure_user_memory_layout(user_id)
    if k.startswith("user.profile") or k.startswith("prefs."):
        return root / "USER.md", k_raw
    if re.match(r"^memory\.daily\.\d{4}-\d{2}-\d{2}$", k):
        day = k.split("memory.daily.", 1)[1]
        p = root / "memory" / f"{day}.md"
        return p, k_raw
    return root / "MEMORY.md", k_raw


def _default_for_path(path: Path) -> str:
    if path.name == "USER.md":
        return _DEFAULT_USER.format(markers=f"{_AQ_BEGIN}\n{_AQ_END}\n")
    if path.parent.name == "memory" and path.suffix.lower() == ".md":
        return _DAILY_NOTES.format(day=path.stem, markers=f"{_AQ_BEGIN}\n{_AQ_END}\n")
    return _DEFAULT_MEMORY.format(markers=f"{_AQ_BEGIN}\n{_AQ_END}\n")


def sync_upsert_line(user: User, *, key: str, content: str, importance: int) -> None:
    """Insert or update one logical row in the canonical markdown store."""
    user_id = int(user.id)
    path, k = _target_path_for_key(user_id, key)
    if path.parent.name == "memory":
        path.parent.mkdir(parents=True, exist_ok=True)
    _ensure_file(path, _default_for_path(path))
    text = _read_body(path)
    if _AQ_BEGIN not in text:
        text = _default_for_path(path)
    rows = [r for r in _parse_kv_block(text) if r[0].lower() != k.lower()]
    rows.append((k, max(0, min(10, int(importance))), content.strip()))
    rows.sort(key=lambda r: (r[0].lower(), -r[1]))
    new_block = _serialize_kv_block(rows)
    updated = _replace_kv_in_markdown(text, new_block)
    try:
        path.write_text(updated, encoding="utf-8")
    except OSError:
        logger.exception("canonical_memory: write failed path=%s", path)


def sync_delete_key(user: User, *, key: str) -> None:
    user_id = int(user.id)
    path, k = _target_path_for_key(user_id, key)
    if not path.is_file():
        return
    text = _read_body(path)
    rows = [r for r in _parse_kv_block(text) if r[0].lower() != k.lower()]
    new_block = _serialize_kv_block(rows)
    if _AQ_BEGIN in text and _AQ_END in text:
        updated = _replace_kv_in_markdown(text, f"{_AQ_BEGIN}\n" + new_block.split(_AQ_BEGIN, 1)[1])
    else:
        updated = text
    try:
        path.write_text(updated, encoding="utf-8")
    except OSError:
        logger.exception("canonical_memory: delete write failed path=%s", path)


def read_all_kv(user_id: int) -> list[tuple[str, int, str]]:
    """All structured rows across MEMORY, USER, and daily files."""
    ensure_user_memory_layout(user_id)
    root = memory_workspace_dir(user_id)
    out: list[tuple[str, int, str]] = []
    for p in (root / "MEMORY.md", root / "USER.md"):
        out.extend(_parse_kv_block(_read_body(p)))
    mem_dir = root / "memory"
    if mem_dir.is_dir():
        for child in sorted(mem_dir.glob("*.md")):
            out.extend(_parse_kv_block(_read_body(child)))
    return out


def build_markdown_memory_prompt_section(user: User, *, char_budget: int = 12_000) -> str:
    """Frozen snapshot for system prompt: MEMORY + USER + today/yesterday daily files (plain text, bounded)."""
    ensure_user_memory_layout(int(user.id))
    root = memory_workspace_dir(int(user.id))
    parts: list[str] = [
        "# Canonical memory (OpenClaw-style)\n",
        "Structured rows in MEMORY.md, USER.md, and memory/YYYY-MM-DD.md are the source of truth. "
        "The key/value index in the database mirrors these files for search.\n",
    ]
    for label, relp in (
        ("MEMORY.md", "MEMORY.md"),
        ("USER.md", "USER.md"),
    ):
        p = root / relp
        body = _read_body(p).strip()
        if not body:
            continue
        parts.append(f"## {label}\n\n{body}\n")

    today = _today_utc()
    yday = date.fromordinal(today.toordinal() - 1)
    for d in (today, yday):
        p = root / "memory" / f"{d.isoformat()}.md"
        body = _read_body(p).strip()
        if body:
            parts.append(f"## memory/{d.isoformat()}.md\n\n{body}\n")

    blob = "\n".join(parts).strip()
    if len(blob) > char_budget:
        blob = blob[: char_budget - 1].rstrip() + "…"
    return f"## Agent canonical memory (markdown)\n\n{blob}\n" if blob else ""


@dataclass
class UserMemoryResetReport:
    deleted_files: int
    deleted_db_hint: str


def reset_user_memory_workspace(user: User) -> UserMemoryResetReport:
    """Remove the user's memory_workspace directory. Caller should TRUNCATE or delete agent_memories rows."""
    import shutil

    root = memory_workspace_dir(int(user.id))
    n = 0
    if root.is_dir():
        try:
            shutil.rmtree(root)
            n = 1
        except OSError:
            logger.exception("canonical_memory: rmtree failed %s", root)
    return UserMemoryResetReport(
        deleted_files=n,
        deleted_db_hint="Run SQL DELETE FROM agent_memories WHERE user_id=… or use the API that clears DB index.",
    )


def export_rubric_path(user_id: int) -> Path:
    return ensure_user_memory_layout(user_id) / "rubric.json"
