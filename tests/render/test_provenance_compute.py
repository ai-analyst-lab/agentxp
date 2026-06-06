"""W4 — provenance compute closure tests.

W4.1 — build_provenance_for_brief is a pure function over the experiment
dir's on-disk state. Closes the R9 bypass (DIAGNOSTIC §A): pre-W4 the
orchestrator passed provenance_render_status as a Literal string;
render_share_tail trusted the label. Post-W4 the status is computed.

W4.2 — render_share_tail no longer accepts provenance_render_status as
a parameter. The catalog still records it (RenderCompletedEvent
unchanged), but the value comes from build_provenance_for_brief, not
from the caller.
"""
from __future__ import annotations

import inspect
import subprocess
from pathlib import Path

import pytest

from agentxp.orchestrator.tools import render_share_tail
from agentxp.render.provenance import (
    RenderStatus,
    build_provenance_for_brief,
)


def test_render_share_tail_signature_drops_provenance_param() -> None:
    """W4.2 — render_share_tail no longer accepts provenance_render_status."""
    params = inspect.signature(render_share_tail).parameters
    assert "provenance_render_status" not in params, (
        "render_share_tail must not accept provenance_render_status — "
        "the value is computed from disk now (W4.2 / debate §3.4)."
    )


def test_intent_readout_always_draft_unverified(tmp_path: Path) -> None:
    """W4.1 — intent is never VERIFIED. The user's prose pre-seal cannot lock."""
    exp_dir = tmp_path / "exp_test"
    exp_dir.mkdir()
    status = build_provenance_for_brief(exp_dir, "intent")
    assert status is RenderStatus.DRAFT_UNVERIFIED


def test_monitor_check_readout_always_draft_unverified(tmp_path: Path) -> None:
    """W4.1 — monitor halt is operational context, never sealed."""
    exp_dir = tmp_path / "exp_test"
    exp_dir.mkdir()
    status = build_provenance_for_brief(exp_dir, "monitor_check")
    assert status is RenderStatus.DRAFT_UNVERIFIED


def test_unknown_readout_type_is_unverifiable(tmp_path: Path) -> None:
    """W4.1 — unknown kind returns UNVERIFIABLE so the orchestrator can surface
    it as a bug rather than silently landing as a draft.
    """
    exp_dir = tmp_path / "exp_test"
    exp_dir.mkdir()
    status = build_provenance_for_brief(exp_dir, "report")  # not in design verb
    assert status is RenderStatus.UNVERIFIABLE


def test_design_brief_without_seal_is_draft(tmp_path: Path) -> None:
    """W4.1 — no brief.sealed.yaml means DRAFT_UNVERIFIED, not VERIFIED."""
    exp_dir = tmp_path / "exp_test"
    exp_dir.mkdir()
    status = build_provenance_for_brief(exp_dir, "design_brief")
    assert status is RenderStatus.DRAFT_UNVERIFIED


def test_design_brief_with_invalid_seal_is_draft(tmp_path: Path) -> None:
    """W4.1 — a seal file present but malformed → DRAFT_UNVERIFIED, never VERIFIED."""
    exp_dir = tmp_path / "exp_test"
    exp_dir.mkdir()
    (exp_dir / "brief.sealed.yaml").write_text("not: valid sealed brief shape\n")
    status = build_provenance_for_brief(exp_dir, "design_brief")
    assert status is RenderStatus.DRAFT_UNVERIFIED


def test_r9_bypass_closed_orchestrator_cannot_label_intent_as_verified(
    tmp_path: Path,
) -> None:
    """W4 acceptance — an orchestrator cannot upgrade intent → VERIFIED through
    a parameter, because the parameter no longer exists and the computed
    value for intent is structurally DRAFT_UNVERIFIED.
    """
    exp_dir = tmp_path / "exp_test"
    exp_dir.mkdir(parents=True)
    # An orchestrator that "knows" the intent is fine still cannot mark it
    # VERIFIED through any code path build_provenance_for_brief admits.
    for readout_type in ("intent", "monitor_check"):
        assert build_provenance_for_brief(exp_dir, readout_type) is not RenderStatus.VERIFIED
