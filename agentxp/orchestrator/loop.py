"""Verb entry points (T80, replaces v0.1 store.py).

The orchestrator is a Claude Code session running with the project root
CLAUDE.md as its system prompt. It is *the* agent — it owns the user
conversation, decides path, dispatches specialists, runs the critic at
every commit, commits via git, and narrates results.

This module provides the Python-side scaffolding the orchestrator uses
inside a Claude Code session — not a "main loop" in the Python sense
(the agent IS the loop). Specifically:

  - run_design_verb(exp_dir, ...)    enter the design verb's loop
  - run_analyze_verb(brief_path, ...) enter the analyze verb's loop
  - VerbContext                       per-turn snapshot

Sub-agent dispatch lives in ``agentxp.orchestrator.bridge``
(``open_dispatch`` + ``complete_dispatch``). Pre-audit this module also
declared ``dispatch_specialist`` / ``dispatch_critic`` / ``LLMCaller``
as a parallel, never-wired dispatch path; the bridge replaced them in
W5 and the audit (S4.A) removed them here.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from agentxp.orchestrator.tools import (
    ExperimentSnapshot,
    read_experiment_dir,
)


# ─────────────────────────────────────────────────────────────────────────────
# Verb context — what the loop reads at the start of every turn
# ─────────────────────────────────────────────────────────────────────────────


class VerbContext(BaseModel):
    """Per-turn state of a verb's loop. Read fresh from disk at every turn."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    verb: Literal["design", "analyze"]
    snapshot: ExperimentSnapshot
    project_root: Path

    @property
    def terminal(self) -> bool:
        """Has the verb reached its termination condition?

        - design  terminates when the brief seals
        - analyze terminates when report.md is committed
        """
        if self.verb == "design":
            return self.snapshot.brief_sealed
        return self.snapshot.has_report


# ─────────────────────────────────────────────────────────────────────────────
# The verb runners — entry points for the design / analyze CLI commands
# ─────────────────────────────────────────────────────────────────────────────


def design_verb_initial_snapshot(exp_dir: Path) -> VerbContext:
    """Construct the initial VerbContext for a design-verb session.

    The CLI calls this; the agent then drives the loop using the tools
    in orchestrator/tools.py and bridge.open_dispatch /
    bridge.complete_dispatch.
    """
    snapshot = read_experiment_dir(exp_dir)
    return VerbContext(
        verb="design",
        snapshot=snapshot,
        project_root=exp_dir.parent.parent,
    )


def analyze_verb_initial_snapshot(
    *,
    exp_dir: Path,
    sealed_brief_path: Path,
) -> VerbContext:
    """Construct the initial VerbContext for an analyze-verb session.

    The CLI verifies the brief seal BEFORE calling this; reaching here
    means the three-part integrity lock passed.
    """
    snapshot = read_experiment_dir(exp_dir)
    return VerbContext(
        verb="analyze",
        snapshot=snapshot,
        project_root=exp_dir.parent.parent,
    )


__all__ = [
    "VerbContext",
    "design_verb_initial_snapshot",
    "analyze_verb_initial_snapshot",
]
