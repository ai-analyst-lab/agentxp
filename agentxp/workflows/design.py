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


def load_intent(intent_path: Path):
    """Project the on-disk ``intent.yaml`` into a bundle-shaped IntentText.

    The on-disk artifact carries audit metadata — ``schema_version`` (the
    file format version) and ``captured_by`` (the email/handle of the user
    who recorded the intent). The bundle type ``IntentText`` deliberately
    does NOT carry these (R10 — the specialist sees only what the schema
    declares; audit metadata stays on disk and on the render path).

    Pre-load_intent callers wrote ``IntentText(**yaml.safe_load(path))``
    which fails with ``Extra inputs are not permitted`` on the audit
    fields. This helper does the projection. The smoke test that
    surfaced the gap is ``working/architect-brief/SESSION_TRANSCRIPT.md``
    Step-1 (the original session) and the post-build smoke run that
    landed at ``experiments/exp_1f51bcf6/``.

    Returns a ``(IntentText, audit_dict)`` pair so callers that need the
    audit metadata for rendering or logging do not have to re-read the
    YAML themselves.
    """
    import yaml

    from agentxp.schemas.bundles import IntentText

    raw = yaml.safe_load(Path(intent_path).read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"intent.yaml at {intent_path} is not a mapping")

    bundle = IntentText(text=raw["text"], captured_at=raw["captured_at"])
    audit = {
        "schema_version": raw.get("schema_version"),
        "captured_by": raw.get("captured_by"),
    }
    return bundle, audit


__all__ = ["allocate_experiment", "record_intent"]
