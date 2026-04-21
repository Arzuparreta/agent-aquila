"""Workspace file reads are path-sandboxed."""

from __future__ import annotations

from app.services.agent_workspace import read_allowed_workspace_file
from app.services.skills_service import _skills_dir


def test_read_workspace_rejects_parent_segments() -> None:
    sk = _skills_dir()
    assert read_allowed_workspace_file("../etc/passwd", skills_root=sk) is None
    assert read_allowed_workspace_file("foo/../../SOUL.md", skills_root=sk) is None


def test_read_workspace_accepts_basename_md() -> None:
    sk = _skills_dir()
    raw = read_allowed_workspace_file("SOUL.md", skills_root=sk)
    assert raw is not None
    assert len(raw) > 10
