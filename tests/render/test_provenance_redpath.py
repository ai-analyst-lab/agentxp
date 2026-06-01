"""W3 release gate — the red-path + legitimate-override provenance test.

This is the load-bearing trust defense for every visual tier built on top of it
(W4+). It pins, against a real finalized experiment:

  - the HAPPY path: a valid log + matching chain hash + a verdict that
    reproduces from the recorded scalars resolves to VERIFIED, and the
    ``(verdict, terminal_step)`` pair is pinned so a silent change to
    ``interpret/tree.py`` fails LOUDLY here rather than shipping a wrong badge;
  - the TAMPERED-HASH path: a doctored ``chain_hash`` → DRAFT_UNVERIFIED at every
    tier (glance banner + md admonition + footer ``chain integrity: FAILED``);
  - the TAMPERED-VERDICT path: a sidecar whose verdict disagrees with the
    recorded decision-tree scalars → DRAFT via tree-reproduction failure (the
    hash still matches, so this can ONLY be caught by reproducing the verdict);
  - the LEGITIMATE-OVERRIDE path: a human NO-SHIP sign-off recorded in
    ``override_justification`` over a tree SHIP verdict STILL reproduces (the
    override never overwrites ``Report.verdict``) → VERIFIED, never DRAFT;
  - the receipts block is present and un-croppable in every state.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agentxp.finalize import finalize_report
from agentxp.render import ViewBundle, build_provenance, distill
from agentxp.render.adapters.glance import GlanceAdapter
from agentxp.render.adapters.markdown import MarkdownAdapter
from agentxp.render.provenance import RenderStatus
from agentxp.schemas.report import Report

FIXTURE_BUNDLES = Path(__file__).parent / "fixtures" / "bundles_ship"

# Pinned expectation — the ship fixture fires Step 7 (benefit-side lift, late
# ratio above the novelty floor) → SHIP. If a tree.py threshold change moves
# this, the happy-path test below flips to DRAFT and fails loudly.
PINNED_VERDICT = "SHIP"
PINNED_TERMINAL_STEP = 7


@pytest.fixture
def exp_dir(tmp_path: Path) -> Path:
    """A finalized experiment dir (SHIP) with a real, hash-matching log."""
    exp = tmp_path / "experiments" / "exp_001"
    (exp / "bundles").mkdir(parents=True)
    for name in (
        "analyzer.out.yaml",
        "interpreter.out.yaml",
        "monitor.out.yaml",
        "readout.out.yaml",
    ):
        shutil.copy(FIXTURE_BUNDLES / name, exp / "bundles" / name)
    shutil.copy(FIXTURE_BUNDLES / "experiment.yaml", exp / "experiment.yaml")
    (exp / "log.jsonl").write_text(
        json.dumps(
            {"event_name": "stage.committed", "stage": "analyze",
             "timestamp": "2026-06-02T17:55:11Z"}
        )
        + "\n",
        encoding="utf-8",
    )
    finalize_report(exp)
    return exp


def _load(exp: Path) -> Report:
    return Report.model_validate_json((exp / "report.json").read_text())


def _patch_report(exp: Path, **changes) -> Report:
    data = json.loads((exp / "report.json").read_text())
    data.update(changes)
    (exp / "report.json").write_text(json.dumps(data, indent=2))
    return _load(exp)


def _bundle(report: Report, exp: Path) -> ViewBundle:
    return ViewBundle(vm=distill(report), provenance=build_provenance(report, exp))


# ── Happy path — VERIFIED, and the verdict/step is pinned ───────────────────

def test_baseline_verifies_and_pins_verdict(exp_dir):
    report = _load(exp_dir)
    assert (report.verdict, report.step_fired) == (PINNED_VERDICT, PINNED_TERMINAL_STEP)

    prov = build_provenance(report, exp_dir)
    assert prov.render_status is RenderStatus.VERIFIED
    assert prov.hash_matches is True
    assert prov.chain_validation_ok is True
    assert prov.tree_reproduces is True


# ── Tampered hash — DRAFT at every tier ─────────────────────────────────────

def test_tampered_hash_is_draft_all_tiers(exp_dir):
    report = _patch_report(exp_dir, chain_hash="0" * 64)
    prov = build_provenance(report, exp_dir)
    assert prov.render_status is RenderStatus.DRAFT_UNVERIFIED
    assert prov.hash_matches is False

    bundle = _bundle(report, exp_dir)
    glance = GlanceAdapter().render(bundle)
    assert glance.splitlines()[0].startswith("⚠ DRAFT — UNVERIFIED")
    assert "chain MISMATCH" in glance

    md = MarkdownAdapter().render(bundle)
    assert "DRAFT — UNVERIFIED" in md
    assert "chain integrity: FAILED" in md
    # Receipts are part of the document, not a droppable addendum.
    assert "## Provenance" in md


# ── Tampered verdict — caught ONLY by tree-reproduction (hash still matches) ─

def test_tampered_verdict_fails_tree_reproduction(exp_dir):
    # The hash is untouched (it covers log.jsonl, not report.json), so the only
    # signal that the sidecar lies is that the verdict no longer reproduces.
    report = _patch_report(exp_dir, verdict="NO-LIFT")
    prov = build_provenance(report, exp_dir)
    assert prov.render_status is RenderStatus.DRAFT_UNVERIFIED
    assert prov.hash_matches is True
    assert prov.chain_validation_ok is True
    assert prov.tree_reproduces is False
    assert "reproduce" in prov.status_reason

    md = MarkdownAdapter().render(_bundle(report, exp_dir))
    assert "DRAFT — UNVERIFIED" in md


# ── Legitimate override — a human NO-SHIP over a tree SHIP still reproduces ──

def test_legitimate_override_still_verifies(exp_dir):
    override = {
        "reason_code": "directional_only",
        "rationale": "Holding the launch for a brand review unrelated to the metrics.",
        "authored_by": "shane@aieval.ai",
        "authored_at": datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc).isoformat(),
    }
    # Report.verdict stays the TREE verdict (SHIP); the override is a separate
    # layer. So the tree still reproduces and the report stays VERIFIED.
    report = _patch_report(exp_dir, override_justification=override)
    assert report.verdict == PINNED_VERDICT

    prov = build_provenance(report, exp_dir)
    assert prov.render_status is RenderStatus.VERIFIED
    assert prov.tree_reproduces is True

    # A legitimate override is never stamped DRAFT.
    glance = GlanceAdapter().render(_bundle(report, exp_dir))
    assert not glance.startswith("⚠ DRAFT")
    md = MarkdownAdapter().render(_bundle(report, exp_dir))
    assert "DRAFT — UNVERIFIED" not in md
    assert "## Provenance" in md
