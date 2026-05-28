"""Per-stage decision artifact writer for OpenXP v0.1.

Each user-visible stage commit produces ONE ``decisions/{ordinal:02d}-{stage}.yaml``
file in the experiment directory. The ordinal is a 0-based, zero-padded sequence
so files sort lexicographically in chain order. Decisions capture the user's
intent and the system's resolution at one stage boundary; they are read by
``agentxp audit`` (W_hooks.4) and replayed by ``openxp resume`` (W5).

Write ordering per §10: ``experiment.yaml → decisions/*.yaml → state.yaml →
emit(stage.committed)``. The OrchestratorStore calls ``write_decision`` inside
the ``_commit_stage`` critical section BEFORE the state.yaml update, so a crash
leaves no orphan state pointing at a missing decision.

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §10, §22.5, §1.8.12.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from openxp.audit.storage import _atomic_write_bytes
from openxp.schemas.state import _enforce_utc


class Decision(BaseModel):
    """One per-stage decision record (schema_version=1).

    Captures the user's intent and the system's resolution at one stage
    boundary. Anchored by ``action_id`` of the ``stage.committed`` event for
    this stage (so ``agentxp audit`` can cross-walk decisions ↔ log.jsonl).
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    ordinal: int
    stage: str
    decided_at: datetime
    action_id: str
    artifacts_written: list[str] = Field(default_factory=list)
    user_input: Optional[str] = None
    agent_outputs: list[dict[str, Any]] = Field(default_factory=list)
    gate_resolved: Optional[dict[str, Any]] = None

    @field_validator("decided_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return _enforce_utc(v)


def _filename(ordinal: int, stage: str) -> str:
    """Zero-padded ordinal + stage suffix, matching the §1.8.12 convention."""
    return f"{ordinal:02d}-{stage}.yaml"


def write_decision(exp_dir: Path, decision: Decision) -> Path:
    """Atomic write of ``experiments/{exp_id}/decisions/{ordinal:02d}-{stage}.yaml``.

    - Creates ``decisions/`` subdirectory if needed.
    - Atomic via tempfile + ``os.replace`` (delegates to ``_atomic_write_bytes``).
    - chmod 0o600 on the final file.
    - YAML output via ``yaml.safe_dump(..., sort_keys=False)`` so the on-disk
      field order matches the model definition.

    Returns the absolute path written.
    """
    decisions_dir = exp_dir / "decisions"
    decisions_dir.mkdir(parents=True, exist_ok=True)

    path = decisions_dir / _filename(decision.ordinal, decision.stage)
    payload = decision.model_dump(mode="json")
    data = yaml.safe_dump(payload, sort_keys=False).encode("utf-8")

    _atomic_write_bytes(path, data, mode=0o600)
    return path


def read_decision(exp_dir: Path, ordinal: int) -> Decision:
    """Load ``decisions/{ordinal:02d}-*.yaml`` from disk.

    Resolves the stage suffix automatically by globbing. Raises
    ``FileNotFoundError`` when no matching file exists.
    """
    decisions_dir = exp_dir / "decisions"
    pattern = f"{ordinal:02d}-*.yaml"
    matches = sorted(decisions_dir.glob(pattern)) if decisions_dir.exists() else []
    if not matches:
        raise FileNotFoundError(
            f"No decision file found for ordinal {ordinal:02d} in {decisions_dir}"
        )
    doc = yaml.safe_load(matches[0].read_text(encoding="utf-8"))
    return Decision.model_validate(doc)


def read_all_decisions(exp_dir: Path) -> list[Decision]:
    """Load every ``decisions/*.yaml`` in ordinal order.

    Lexicographic sort by filename matches chronological order because the
    ordinal prefix is zero-padded.
    """
    decisions_dir = exp_dir / "decisions"
    if not decisions_dir.exists():
        return []
    decisions: list[Decision] = []
    for path in sorted(decisions_dir.glob("*.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        decisions.append(Decision.model_validate(doc))
    decisions.sort(key=lambda d: d.ordinal)
    return decisions


def next_ordinal(exp_dir: Path) -> int:
    """Return the next ordinal to use.

    Walks ``decisions/`` to find the highest existing ordinal; returns
    ``max + 1``. Returns ``0`` if the directory is missing or empty.
    """
    decisions_dir = exp_dir / "decisions"
    if not decisions_dir.exists():
        return 0
    highest = -1
    for path in decisions_dir.glob("*.yaml"):
        prefix = path.name.split("-", 1)[0]
        try:
            n = int(prefix)
        except ValueError:
            continue
        if n > highest:
            highest = n
    return highest + 1


__all__ = [
    "Decision",
    "write_decision",
    "read_decision",
    "read_all_decisions",
    "next_ordinal",
]
