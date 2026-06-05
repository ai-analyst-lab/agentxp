"""Design verb helpers — called by .claude/skills/design/SKILL.md.

The design verb pre-registers an experiment: intent → semantic models →
metrics → hypothesis → brief → data plan → sealed brief. These helpers
do the Python-side allocation and bookkeeping; the agentic loop (which
specialist to dispatch when, which gate to confirm) lives in the skill.

Public surface:
  - allocate_experiment(project_root, *, data_path=None, experiment_id=None) -> Path
  - record_intent(exp_dir, intent_text, captured_by) -> Path
"""
from __future__ import annotations

import datetime as _dt
import uuid
from pathlib import Path
from typing import Optional


def _new_experiment_id() -> str:
    """Generate a short ULID-flavored experiment id: ``exp_<8-hex>``."""
    return f"exp_{uuid.uuid4().hex[:8]}"


def allocate_experiment(
    project_root: Path,
    *,
    data_path: Optional[Path] = None,
    experiment_id: Optional[str] = None,
) -> Path:
    """Allocate a fresh experiment directory under ``project_root/experiments/``.

    Returns the absolute path to the new directory. Seeds ``log.md`` with
    a single open-line entry. If ``data_path`` is supplied, stashes the
    resolved path at ``.data_path`` for the orchestrator to pick up.

    Raises ``FileExistsError`` if ``experiment_id`` is supplied and the directory
    already exists (no silent collision).
    """
    experiment_id = experiment_id or _new_experiment_id()
    exp_dir = Path(project_root) / "experiments" / experiment_id
    if exp_dir.exists():
        raise FileExistsError(
            f"experiment directory already exists: {exp_dir}"
        )
    exp_dir.mkdir(parents=True)

    ts = _dt.datetime.now(_dt.timezone.utc).isoformat()
    log = exp_dir / "log.md"
    log.write_text(
        f"# log — {experiment_id}\n\n"
        f"- `{ts}` — design verb opened\n"
    )

    if data_path is not None:
        (exp_dir / ".data_path").write_text(str(Path(data_path).resolve()))

    return exp_dir


def record_intent(
    exp_dir: Path,
    intent_text: str,
    captured_by: str,
) -> Path:
    """Write ``intent.yaml`` and append a log entry. Returns the intent path.

    The intent is the user's plain-English statement of what they want to
    test. It's the trigger for everything downstream: semantic models,
    metrics, hypothesis, brief. The orchestrator dispatches the designer
    after this lands.

    Raises ``ValueError`` if ``intent_text`` is empty or whitespace-only.
    """
    if not intent_text or not intent_text.strip():
        raise ValueError("intent_text must be non-empty")
    if not captured_by or not captured_by.strip():
        raise ValueError("captured_by must be non-empty")

    exp_dir = Path(exp_dir)
    ts = _dt.datetime.now(_dt.timezone.utc).isoformat()
    intent_path = exp_dir / "intent.yaml"

    # Minimal YAML — the schema lives in agentxp/schemas/experiment.py; this
    # writer keeps the format flat so log.md remains readable.
    intent_path.write_text(
        f"schema_version: 1\n"
        f"text: |\n"
        f"  {intent_text.strip()}\n"
        f"captured_at: {ts}\n"
        f"captured_by: {captured_by}\n"
    )

    log = exp_dir / "log.md"
    with log.open("a") as f:
        f.write(f"- `{ts}` — intent captured by {captured_by}\n")

    return intent_path


__all__ = ["allocate_experiment", "record_intent"]
