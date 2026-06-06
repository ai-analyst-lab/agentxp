"""W6.4 — persona × format fan-out helper for share-tail renders.

DIAGNOSTIC §A: the design verb's step-11 render produced only ``exec.md``
because ``render_share_tail`` is single-shot. The canonical layout in
every other experiment dir is ``{exec, operator, engineer} × {html,
pdf}`` per readout type (= 6 files). Without a fan-out helper, the skill
text becomes a manual loop the orchestrator has to encode at every
call-site.

This module exports ``fan_out`` which orchestrates the six calls in one
function, generates collision-resistant entry ids per row (W6.3), and
returns the six paths plus the catalog rows the render produced.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from agentxp.render.viewmodel import (
    DesignBriefVM,
    IntentVM,
    MidRunVM,
    VerdictVM,
)

# The canonical persona × format Cartesian. Locked here so the skill can
# cite a single source of truth, and so a future change to add a fourth
# persona or a third format lands in one place.

PERSONAS = ("exec", "operator", "engineer")
FORMATS = ("html", "pdf")


def fan_out(
    *,
    exp_dir: Path,
    experiment_id: str,
    readout_type: str,
    vm: IntentVM | DesignBriefVM | MidRunVM | VerdictVM,
    vm_sha256: str,
    timestamp: Optional[datetime] = None,
    entry_id_base: Optional[str] = None,
    strict_voice: bool = False,
) -> list[Path]:
    """Render the canonical 6-file persona × format layout for one readout.

    Parameters
    ----------
    exp_dir
        ``experiments/<id>/``.
    experiment_id
        The id used in catalog rows.
    readout_type
        ``"intent"``, ``"design_brief"``, ``"monitor_check"``, ``"verdict"``.
        Whatever ``render_share_tail`` accepts.
    vm
        The ViewModel for the readout. ``distill_*`` is the source.
    vm_sha256
        Pinning hash for the catalog row.
    timestamp
        Optional. When omitted, a single ``datetime.now(timezone.utc)``
        is captured at the start of fan-out so all six rows share the
        slot directory.
    entry_id_base
        Optional shared prefix for the six derived entry ids. When
        omitted, a fresh uuid4-derived base is generated. The six rows
        derive as ``f"{base}-{audience}-{fmt}"`` so the catalog walker
        can trace them back to one fan-out event.
    strict_voice
        Passed through to ``render_share_tail`` per row. When True,
        the first banned-vocab violation raises and aborts the
        remaining renders.

    Returns
    -------
    list[Path]
        The six output paths in deterministic ``(audience, fmt)`` order.
    """
    # Import here to avoid the module-load circular: tools imports render.
    from agentxp.orchestrator.tools import _new_entry_id, render_share_tail

    ts = timestamp or datetime.now(timezone.utc)
    base = entry_id_base or _new_entry_id(prefix="fan")

    out_paths: list[Path] = []
    for audience in PERSONAS:
        for fmt in FORMATS:
            entry_id = f"{base}-{audience}-{fmt}"
            p = render_share_tail(
                exp_dir=exp_dir,
                experiment_id=experiment_id,
                readout_type=readout_type,  # type: ignore[arg-type]
                vm=vm,
                vm_sha256=vm_sha256,
                audience=audience,  # type: ignore[arg-type]
                fmt=fmt,  # type: ignore[arg-type]
                entry_id=entry_id,
                timestamp=ts,
                strict_voice=strict_voice,
            )
            out_paths.append(p)
    return out_paths


__all__ = ["PERSONAS", "FORMATS", "fan_out"]
