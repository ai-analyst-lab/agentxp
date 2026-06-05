"""Analyze verb helpers — called by .claude/skills/analyze/SKILL.md.

The analyze verb runs from a sealed brief through verdict + readout. Its
first action — and the architectural wall (R11) — is to verify the
brief's three-part integrity lock. Any mismatch refuses entry; there is
no ``--force``.

Public surface:
  - verify_and_open(brief_path, project_root) -> SealedBrief
"""
from __future__ import annotations

from pathlib import Path

import yaml

from agentxp.schemas.brief_seal import (
    BriefSealMismatch,
    SealedBrief,
    verify_or_raise,
)


def verify_and_open(brief_path: Path, project_root: Path) -> SealedBrief:
    """Load + validate + verify a sealed brief. R11 wall enforcement.

    Returns the validated :class:`SealedBrief`. Raises:
      - :class:`FileNotFoundError` if ``brief_path`` does not exist.
      - :class:`pydantic.ValidationError` if the YAML isn't a SealedBrief.
      - :class:`BriefSealMismatch` if the three-part integrity lock fails
        (chain hash drift, metric YAML drift, or expected-shape drift).

    The caller (the analyze CLI / skill) catches :class:`BriefSealMismatch`
    at its boundary and refuses entry with the structured reason.
    """
    brief_path = Path(brief_path)
    project_root = Path(project_root)

    if not brief_path.exists():
        raise FileNotFoundError(f"brief path does not exist: {brief_path}")

    raw = yaml.safe_load(brief_path.read_text())
    sealed = SealedBrief(**raw)

    exp_dir = brief_path.parent
    design_chain_path = exp_dir / "log.md"
    metric_paths = {
        name: project_root / "metrics" / f"{name}.yaml"
        for name in sealed.metric_snapshot.keys()
    }

    verify_or_raise(
        sealed=sealed,
        design_chain_path=design_chain_path,
        metric_paths=metric_paths,
    )

    return sealed


__all__ = ["verify_and_open", "BriefSealMismatch"]
