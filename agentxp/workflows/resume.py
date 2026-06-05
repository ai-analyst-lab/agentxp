"""Resume helpers — used by orchestrator first-turn behavior.

NOT a slash command. ``/resume`` is reserved by Claude Code; the user
continues an in-flight experiment via ``/design --exp-id <existing>``
(pre-seal) or ``/analyze --brief <path>`` (post-seal). This module
exists for first-turn behavior in CLAUDE.md §8: when the user opens
the repo, the orchestrator lists in-flight experiments and asks which
to resume.

Public surface:
  - list_in_flight(project_root) -> list[ExperimentSnapshot]
  - classify(snapshot) -> ResumeState
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from agentxp.orchestrator.tools import (
    ExperimentSnapshot,
    read_experiment_dir,
)


ResumeState = Literal[
    "intent_only",
    "hypothesis_drafted",
    "brief_drafted",
    "brief_sealed",
    "analysis_in_progress",
    "complete",
]


def list_in_flight(project_root: Path) -> list[ExperimentSnapshot]:
    """Return one snapshot per experiment directory under ``project_root/experiments/``.

    Skips entries that aren't directories. Returns ``[]`` if no
    ``experiments/`` dir exists. Caller uses ``classify(snapshot)`` to
    decide what to do with each.
    """
    exp_root = Path(project_root) / "experiments"
    if not exp_root.exists():
        return []
    snapshots: list[ExperimentSnapshot] = []
    for child in sorted(exp_root.iterdir()):
        if child.is_dir():
            try:
                snapshots.append(read_experiment_dir(child))
            except FileNotFoundError:
                # Skipping unreadable dirs is safer than raising — the
                # user's first turn shouldn't crash on a stale dir.
                continue
    return snapshots


def classify(snapshot: ExperimentSnapshot) -> ResumeState:
    """Map a snapshot to its resume state.

    The classification is by artifact presence, not by enum transitions:

      - report.md present                          -> complete
      - brief.sealed.yaml present + analysis lands -> analysis_in_progress
      - brief.sealed.yaml present                  -> brief_sealed
      - brief.yaml present                         -> brief_drafted
      - hypothesis.yaml present                    -> hypothesis_drafted
      - otherwise                                   -> intent_only

    The orchestrator routes each state to the right verb: complete is a
    terminal no-op; analysis_in_progress + brief_sealed → /analyze;
    everything earlier → /design.
    """
    if snapshot.has_report:
        return "complete"
    if snapshot.brief_sealed and snapshot.has_analysis:
        return "analysis_in_progress"
    if snapshot.brief_sealed:
        return "brief_sealed"
    if snapshot.has_brief:
        return "brief_drafted"
    # Check intent.yaml vs hypothesis.yaml via the directory listing —
    # ExperimentSnapshot doesn't carry these explicitly today; check both.
    exp_dir = snapshot.exp_dir
    if (exp_dir / "hypothesis.yaml").exists():
        return "hypothesis_drafted"
    return "intent_only"


__all__ = ["list_in_flight", "classify", "ResumeState"]
