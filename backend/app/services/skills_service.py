"""Filesystem-backed skill loader for the agent.

A "skill" is a short markdown file that describes a workflow the agent
can run on demand — "triage Gmail inbox", "silence a sender", "weekly
review". The agent calls ``list_skills`` to discover what is available
and ``load_skill`` to read the full body before executing it.

We deliberately keep this dead simple:
- No DB rows, no per-user customization in v1. Skills live under
  ``backend/skills/`` and ship with the app.
- Filenames become slugs (``gmail-triage.md`` → ``gmail-triage``).
- The first H1 (``# Title``) is the title; the first paragraph after
  the H1 is the summary used in the listing.
- Path traversal is rejected (slugs are restricted to a safe charset).

The folder is configurable via ``settings.skills_dir`` so an admin can
mount custom skills from a docker volume without rebuilding the image.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings

# Repo-relative default — overridden by AQUILA_SKILLS_DIR when set.
_DEFAULT_SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,80}$")


def _skills_dir() -> Path:
    custom = getattr(settings, "skills_dir", "") or ""
    if custom:
        p = Path(custom).expanduser().resolve()
        if p.exists():
            return p
    return _DEFAULT_SKILLS_DIR


@dataclass(frozen=True)
class Skill:
    slug: str
    title: str
    summary: str
    body: str


def _parse(slug: str, raw: str) -> Skill:
    """Extract title (first ``# ...``) and summary (first non-empty paragraph after it)."""
    title = slug
    summary = ""
    lines = raw.splitlines()
    in_body = False
    para: list[str] = []
    for line in lines:
        if not in_body:
            if line.startswith("# "):
                title = line[2:].strip() or slug
                in_body = True
            continue
        if line.strip():
            para.append(line.strip())
        elif para:
            break
    if para:
        summary = " ".join(para)
        if len(summary) > 240:
            summary = summary[:237].rstrip() + "…"
    return Skill(slug=slug, title=title, summary=summary, body=raw)


def list_skills() -> list[Skill]:
    """Return every ``*.md`` file in the skills directory, parsed.

    Skipped on missing folder so a fresh checkout that hasn't created
    ``backend/skills/`` yet doesn't crash the agent.
    """
    folder = _skills_dir()
    if not folder.exists():
        return []
    out: list[Skill] = []
    for path in sorted(folder.glob("*.md")):
        slug = path.stem
        if not _SLUG_RE.match(slug):
            continue
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            continue
        out.append(_parse(slug, raw))
    return out


def load_skill(slug: str) -> Skill | None:
    """Load a single skill body by slug, with a strict slug guard."""
    if not _SLUG_RE.match(slug or ""):
        return None
    path = _skills_dir() / f"{slug}.md"
    try:
        # Reject path traversal: resolved path must remain inside the folder.
        resolved = path.resolve()
        if not str(resolved).startswith(str(_skills_dir().resolve())):
            return None
        raw = resolved.read_text(encoding="utf-8")
    except OSError:
        return None
    return _parse(slug, raw)
