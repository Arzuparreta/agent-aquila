"""Dynamic importance rubric for multi-judge memory routing (per-user, online-updatable).

Stored as JSON in ``<memory_workspace>/rubric.json``. The committee's judge pass and
the optional adaptation step read/write this file so weaker models' static scores
are adjusted using user-specific evidence over time.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.models.user import User
from app.services.canonical_memory import ensure_user_memory_layout, export_rubric_path

logger = logging.getLogger(__name__)

DEFAULT_RUBRIC_VERSION = 1


@dataclass
class ImportanceRubric:
    version: int = DEFAULT_RUBRIC_VERSION
    # Dimension weights 0.0–1.0; normalized when applying
    w_user_preference: float = 0.22
    w_corrections: float = 0.18
    w_task_outcome: float = 0.20
    w_repetition: float = 0.15
    w_identity: float = 0.15
    w_ephemeral_penalty: float = 0.10
    # Bias added after weighted score (pre-sigmoid)
    base_bias: float = 0.0
    # Free-form learned nudges (e.g. domain-specific) — list of short strings
    user_conditioned_notes: list[str] = field(default_factory=list)
    # Last adaptation metadata
    last_adapted_at: str | None = None
    total_adaptation_steps: int = 0

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, d: Any) -> ImportanceRubric:
        if not isinstance(d, dict):
            return cls()
        return cls(
            version=int(d.get("version") or DEFAULT_RUBRIC_VERSION),
            w_user_preference=_f(d, "w_user_preference", 0.22),
            w_corrections=_f(d, "w_corrections", 0.18),
            w_task_outcome=_f(d, "w_task_outcome", 0.20),
            w_repetition=_f(d, "w_repetition", 0.15),
            w_identity=_f(d, "w_identity", 0.15),
            w_ephemeral_penalty=_f(d, "w_ephemeral_penalty", 0.10),
            base_bias=_f(d, "base_bias", 0.0),
            user_conditioned_notes=[
                str(x) for x in (d.get("user_conditioned_notes") or []) if str(x).strip()
            ][:200],
            last_adapted_at=(str(d.get("last_adapted_at")) if d.get("last_adapted_at") else None),
            total_adaptation_steps=int(d.get("total_adaptation_steps") or 0),
        )


def _f(d: dict[str, Any], k: str, default: float) -> float:
    try:
        return float(d.get(k, default))
    except (TypeError, ValueError):
        return default


def load_rubric(user: User) -> ImportanceRubric:
    path: Path = export_rubric_path(int(user.id))
    if not path.is_file():
        return ImportanceRubric()
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return ImportanceRubric()
    return ImportanceRubric.from_dict(data)


def save_rubric(user: User, rubric: ImportanceRubric) -> None:
    ensure_user_memory_layout(int(user.id))
    path = export_rubric_path(int(user.id))
    try:
        path.write_text(rubric.to_json(), encoding="utf-8")
    except OSError:
        logger.exception("agent_rubric: save failed user_id=%s", user.id)


def rubric_prompt_chunk(r: ImportanceRubric) -> str:
    """Short text injected into LLM system prompts for extraction/judges."""
    notes = " ".join(r.user_conditioned_notes[:30]) if r.user_conditioned_notes else "(none yet)"
    return (
        f"Rubric v{r.version} weights: user_pref={r.w_user_preference:.2f} corrections={r.w_corrections:.2f} "
        f"task={r.w_task_outcome:.2f} repetition={r.w_repetition:.2f} identity={r.w_identity:.2f} "
        f"ephemeral_penalty={r.w_ephemeral_penalty:.2f} base_bias={r.base_bias:.2f}.\n"
        f"User-conditioned notes: {notes}"
    )
