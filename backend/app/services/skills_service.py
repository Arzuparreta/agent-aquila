"""Filesystem-backed skill loader (AgentSkills / OpenClaw-style folders).

Each skill is a directory ``<slug>/`` containing ``SKILL.md`` with optional YAML
frontmatter (``name``, ``description``). Legacy flat ``*.md`` files in the
skills root are still discovered for compatibility.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
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


def _split_frontmatter(raw: str) -> tuple[dict[str, str], str]:
    """Single-line-key YAML-style frontmatter only (OpenClaw-compatible subset)."""
    text = raw.lstrip("\ufeff")
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    fm_block = parts[1].strip()
    body = parts[2].lstrip("\n")
    meta: dict[str, str] = {}
    for line in fm_block.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            k, _, v = line.partition(":")
            key = k.strip()
            val = v.strip().strip('"').strip("'")
            if key:
                meta[key] = val
    return meta, body


def _first_heading_and_summary(body: str, slug: str) -> tuple[str, str]:
    title = slug
    summary = ""
    lines = body.splitlines()
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
    return title, summary


@dataclass(frozen=True)
class Skill:
    slug: str
    title: str
    summary: str
    body: str
    metadata: dict[str, str] = field(default_factory=dict)


def _parse_skill_file(slug: str, raw: str) -> Skill:
    meta, body = _split_frontmatter(raw)
    title = (meta.get("name") or "").strip() or None
    summary = (meta.get("description") or "").strip() or None
    h1, para = _first_heading_and_summary(body, slug)
    return Skill(
        slug=slug,
        title=title or h1,
        summary=summary or para,
        body=body.strip(),
        metadata=meta,
    )


def list_skills() -> list[Skill]:
    folder = _skills_dir()
    if not folder.exists():
        return []
    root = folder.resolve()
    out: list[Skill] = []
    seen: set[str] = set()

    for path in sorted(folder.iterdir()):
        if not path.is_dir():
            continue
        slug = path.name
        if not _SLUG_RE.match(slug):
            continue
        smd = path / "SKILL.md"
        if not smd.is_file():
            continue
        try:
            raw = smd.read_text(encoding="utf-8")
        except OSError:
            continue
        out.append(_parse_skill_file(slug, raw))
        seen.add(slug)

    for path in sorted(folder.glob("*.md")):
        slug = path.stem
        if not _SLUG_RE.match(slug) or slug in seen:
            continue
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            continue
        out.append(_parse_skill_file(slug, raw))

    out.sort(key=lambda s: s.slug)
    return out


def load_skill(slug: str) -> Skill | None:
    if not _SLUG_RE.match(slug or ""):
        return None
    base = _skills_dir().resolve()
    # Prefer <slug>/SKILL.md
    dir_smd = (base / slug / "SKILL.md").resolve()
    flat = (base / f"{slug}.md").resolve()
    candidates = [dir_smd, flat]
    for path in candidates:
        try:
            if not str(path).startswith(str(base)):
                return None
            if path.is_file():
                raw = path.read_text(encoding="utf-8")
                return _parse_skill_file(slug, raw)
        except OSError:
            continue
    return None
