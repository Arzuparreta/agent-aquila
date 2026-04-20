"""Regression tests for Alembic ``alembic_version.version_num`` width.

Historical failure: Alembic defaults ``version_num`` to VARCHAR(32). Revision ids
longer than 32 chars (e.g. ``0021_agent_traces_channel_bindings``) caused::

    asyncpg.exceptions.StringDataRightTruncationError: value too long for type character varying(32)

during ``UPDATE alembic_version SET version_num=...``, so ``alembic upgrade head``
aborted and the API container never started (UI then showed 500 / proxy errors).

The runtime guard lives in ``alembic/env.py`` (``_widen_alembic_version_num``).
"""

from __future__ import annotations

import ast
import pathlib

import pytest

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]
ENV_PY = BACKEND_ROOT / "alembic" / "env.py"
VERSIONS_DIR = BACKEND_ROOT / "alembic" / "versions"
# Must match the ALTER target in alembic/env.py
_EXPECTED_VERSION_NUM_WIDTH = 255


def _revision_strings() -> list[str]:
    out: list[str] = []
    for path in sorted(VERSIONS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "revision":
                    value = node.value
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        out.append(value.value)
                    break
    return out


def test_env_py_keeps_widen_guard_for_long_revision_ids() -> None:
    """If this fails, a refactor removed the guard; long revision ids will break Postgres upgrades again."""
    text = ENV_PY.read_text(encoding="utf-8")
    assert "_widen_alembic_version_num" in text, "Restore _widen_alembic_version_num in alembic/env.py"
    assert "ALEMBIC_VERSION_NUM_MAX_LENGTH" in text, "env.py must define ALEMBIC_VERSION_NUM_MAX_LENGTH for the ALTER"
    assert "VARCHAR(" in text and "255" in text, "env.py must ALTER alembic_version.version_num to a wide VARCHAR"
    assert "do_run_migrations" in text
    assert text.find("_widen_alembic_version_num") < text.find("context.run_migrations()"), (
        "_widen_alembic_version_num must run before context.run_migrations()"
    )


def test_migration_revision_ids_fit_widened_column() -> None:
    revs = _revision_strings()
    assert revs, f"No revision= assignments found under {VERSIONS_DIR}"
    too_long = [r for r in revs if len(r) > _EXPECTED_VERSION_NUM_WIDTH]
    assert not too_long, (
        f"Revision id(s) longer than {_EXPECTED_VERSION_NUM_WIDTH} chars: {too_long}. "
        "Shorten the id or raise _EXPECTED_VERSION_NUM_WIDTH in env.py and this test."
    )


@pytest.mark.parametrize(
    "needle",
    [
        "StringDataRightTruncation",
        "alembic_version",
        "VARCHAR(32)",
    ],
)
def test_env_py_documents_operational_triage(needle: str) -> None:
    """Grep-friendly tokens for agents searching the repo after a recurrence."""
    assert needle in ENV_PY.read_text(encoding="utf-8")
