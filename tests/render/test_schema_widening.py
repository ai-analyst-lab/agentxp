"""W0 schema-widening + core-finalizer tests (presentation layer).

These tests pin the Wave-0 contract that everything downstream renders against:

  1. A pre-widening ``report.json`` (schema_version 1) still validates against
     the widened ``Report`` model — old artifacts are never orphaned.
  2. The widened canonical fixture (schema_version 2) round-trips losslessly
     and carries every provenance / design-card / tree-reproduction scalar.
  3. ``terminal_step`` (persisted as ``Report.step_fired``) is the stable,
     int-comparable companion to the unstable ``step_fired`` trail — the W3
     verdict-tree reproduction compares against it, never the strings.
  4. ``finalize_report`` is deterministic, sources every verifiable number from
     the committed bundles (never agent prose), and recomputes the verdict via
     ``walk_tree`` — raising if the agent's claimed verdict diverges.

No real experiment dirs exist in the repo, so the finalizer is exercised
against synthetic bundle fixtures assembled into a tmp experiment dir.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from agentxp.finalize import FinalizeError, finalize_report
from agentxp.interpret.tree import TreeInput, walk_tree
from agentxp.schemas.report import Report

FIXTURES = Path(__file__).parent / "fixtures"
BUNDLES_SHIP = FIXTURES / "bundles_ship"


# ──────────────────────────────────────────────────────────────────────────
# Schema widening — old artifacts still validate, new ones round-trip
# ──────────────────────────────────────────────────────────────────────────

def test_v1_report_validates_against_widened_model():
    """A pre-widening report.json (no provenance / tree scalars) loads cleanly.

    The widening was additive + optional, so pydantic fills the new fields with
    their defaults rather than rejecting the legacy document.
    """
    raw = json.loads((FIXTURES / "report_v1.json").read_text())
    report = Report.model_validate(raw)

    assert report.schema_version == 1
    # Widened scalars are absent on a v1 doc → defaulted to None / 0.95.
    assert report.chain_hash is None
    assert report.locked_brief_hash is None
    assert report.agentxp_version is None
    assert report.n_observed is None
    assert report.baseline is None
    assert report.late_ratio is None
    assert report.ci_level == 0.95
    # The primary metric's per-arm widening is also absent on v1.
    assert report.primary.direction is None
    assert report.primary.n_arm_control is None


def test_v2_report_round_trips_losslessly():
    """The widened canonical fixture survives a model → json → model round-trip."""
    raw = json.loads((FIXTURES / "report_v2.json").read_text())
    report = Report.model_validate(raw)

    assert report.schema_version == 2
    # Provenance receipts are present and travel with the report.
    assert report.chain_hash
    assert report.locked_brief_hash
    assert report.agentxp_version == "0.1.0"
    # Design-card + tree-reproduction scalars are all populated.
    assert report.hypothesis
    assert report.power == 0.8
    assert report.n_observed == 91204
    assert report.n_required == 18000
    assert report.primary_direction == "higher_is_better"
    assert report.mde_pct == 2.0
    assert report.baseline == 0.178
    assert report.late_ratio == 0.87
    assert report.primary.direction == "higher_is_better"
    assert report.primary.n_arm_control == 45602

    # Round-trip: dumping and re-loading yields an equal model.
    reloaded = Report.model_validate(json.loads(report.model_dump_json()))
    assert reloaded == report


def test_v2_terminal_step_reproduces_via_walk_tree():
    """The persisted scalars re-run walk_tree to the SAME (verdict, terminal_step).

    This is the W3 reproduction contract in miniature: compare the int
    ``terminal_step`` against ``Report.step_fired``, never the trail strings.
    """
    report = Report.model_validate(json.loads((FIXTURES / "report_v2.json").read_text()))

    tree = walk_tree(
        TreeInput(
            srm_pass=report.diagnostics.srm_passed,
            guardrails=[],  # guardrails clear on this fixture (none violate)
            n_observed=report.n_observed,
            n_required=report.n_required,
            primary_ci_lower_95=report.primary.ci_95_lower,
            primary_ci_upper_95=report.primary.ci_95_upper,
            primary_ci_lower_90=report.primary.ci_90_lower,
            primary_ci_upper_90=report.primary.ci_90_upper,
            primary_lift_magnitude=report.primary.lift_absolute,
            primary_direction=report.primary_direction,
            mde_pct=report.mde_pct,
            baseline=report.baseline,
            srm_override_resolved=report.srm_override_resolved,
            late_ratio=report.late_ratio,
        )
    )

    assert tree.verdict == report.verdict == "SHIP"
    assert tree.terminal_step == report.step_fired == 7


def test_half_migrated_v2_with_missing_scalars_still_validates():
    """schema_version 2 with the tree scalars stripped is a legal model.

    This is the precondition for the W1/W3 "can't-check" gate: a half-migrated
    report (declares v2 but omits the reproduction scalars) must LOAD so that
    distill() can route it to UNVERIFIABLE rather than the loader rejecting it
    outright. The UNVERIFIABLE *resolution* lands in W1; here we pin only that
    the missing scalars are tolerated as None.
    """
    raw = json.loads((FIXTURES / "report_v2.json").read_text())
    for scalar in ("n_observed", "n_required", "primary_direction", "mde_pct", "baseline"):
        raw.pop(scalar, None)
    raw["chain_hash"] = None

    report = Report.model_validate(raw)
    assert report.schema_version == 2
    assert report.n_observed is None
    assert report.mde_pct is None
    assert report.baseline is None


# ──────────────────────────────────────────────────────────────────────────
# Core finalizer — deterministic, numbers police the agent
# ──────────────────────────────────────────────────────────────────────────

def _assemble_experiment(tmp_path: Path, *, src: Path = BUNDLES_SHIP) -> Path:
    """Lay the synthetic bundle fixtures out as a real experiment dir."""
    exp_dir = tmp_path / "exp_001"
    (exp_dir / "bundles").mkdir(parents=True)
    for bundle in ("analyzer.out.yaml", "interpreter.out.yaml", "monitor.out.yaml", "readout.out.yaml"):
        shutil.copy(src / bundle, exp_dir / "bundles" / bundle)
    shutil.copy(src / "experiment.yaml", exp_dir / "experiment.yaml")
    return exp_dir


def test_finalize_report_writes_canonical_json(tmp_path):
    exp_dir = _assemble_experiment(tmp_path)
    out_path = finalize_report(exp_dir)

    assert out_path == exp_dir / "report.json"
    report = Report.model_validate(json.loads(out_path.read_text()))

    assert report.schema_version == 2
    assert report.experiment_id == "exp_001"
    assert report.verdict == "SHIP"
    assert report.step_fired == 7
    # Numbers carried from the analyzer bundle, not agent prose.
    assert report.primary.lift_absolute == 0.032
    assert report.primary.direction == "higher_is_better"
    assert report.primary.n_arm_control == 45602
    assert report.primary.n_arm_treatment == 45602
    # Provenance computed by the core.
    assert report.agentxp_version == "0.1.0"
    assert report.locked_brief_hash  # sha256 of experiment.yaml
    assert report.chain_hash  # empty-log sha is still a stable receipt
    # Design + tree scalars sourced deterministically.
    assert report.n_required == 18000
    assert report.mde_pct == 2.0
    assert report.baseline == 0.178
    assert report.late_ratio == 0.87
    # Agent prose merged through.
    assert len(report.uncertainty_notes) == 2


def test_finalize_report_is_deterministic_except_timestamp(tmp_path):
    """Two finalizations of identical inputs agree on every verifiable field.

    Only ``generated_at`` (wall clock) is allowed to differ.
    """
    exp_a = _assemble_experiment(tmp_path / "a")
    exp_b = _assemble_experiment(tmp_path / "b")

    ra = Report.model_validate(json.loads(finalize_report(exp_a).read_text()))
    rb = Report.model_validate(json.loads(finalize_report(exp_b).read_text()))

    for field in (
        "verdict",
        "step_fired",
        "chain_hash",
        "locked_brief_hash",
        "n_observed",
        "n_required",
        "mde_pct",
        "baseline",
        "late_ratio",
        "primary_direction",
    ):
        assert getattr(ra, field) == getattr(rb, field), field


def test_finalize_report_raises_on_verdict_divergence(tmp_path):
    """If the agent's claimed verdict contradicts the recomputed one, finalize fails.

    The deterministic tree recompute is the agent-policing step: we corrupt the
    interpreter bundle to claim NO-SHIP-GUARDRAIL while the analyzer numbers
    recompute to SHIP, and assert the finalizer refuses to write.
    """
    exp_dir = _assemble_experiment(tmp_path)
    interp = exp_dir / "bundles" / "interpreter.out.yaml"
    text = interp.read_text().replace("verdict: SHIP", "verdict: NO-SHIP-GUARDRAIL")
    interp.write_text(text)

    with pytest.raises(FinalizeError, match="verdict divergence"):
        finalize_report(exp_dir)

    assert not (exp_dir / "report.json").exists()


def test_finalize_report_raises_on_missing_bundle(tmp_path):
    exp_dir = _assemble_experiment(tmp_path)
    (exp_dir / "bundles" / "analyzer.out.yaml").unlink()

    with pytest.raises(FinalizeError, match="analyzer bundle"):
        finalize_report(exp_dir)


def test_finalize_report_raises_when_interpreter_omits_verdict(tmp_path):
    """A missing claimed verdict must not silently bypass the agent-policing check.

    If the interpreter bundle has no `verdict`, there is nothing to cross-check
    the deterministic recompute against — the finalizer refuses rather than
    writing an unpoliced report.
    """
    exp_dir = _assemble_experiment(tmp_path)
    interp = exp_dir / "bundles" / "interpreter.out.yaml"
    text = "\n".join(
        line for line in interp.read_text().splitlines()
        if not line.startswith("verdict:")
    ) + "\n"
    interp.write_text(text)

    with pytest.raises(FinalizeError, match="missing 'verdict'"):
        finalize_report(exp_dir)

    assert not (exp_dir / "report.json").exists()


def test_finalize_report_derives_baseline_when_absent(tmp_path):
    """With no explicit analyzer baseline, the lift-identity fallback reconstructs it.

    baseline = lift_absolute / (lift_pct / 100) = 0.032 / 0.1798 = 0.178, which
    must still recompute SHIP at terminal_step 7.
    """
    exp_dir = _assemble_experiment(tmp_path)
    analyzer = exp_dir / "bundles" / "analyzer.out.yaml"
    text = "\n".join(
        line for line in analyzer.read_text().splitlines()
        if not line.strip().startswith("baseline:")
    ) + "\n"
    analyzer.write_text(text)

    report = Report.model_validate(json.loads(finalize_report(exp_dir).read_text()))
    assert report.verdict == "SHIP"
    assert report.step_fired == 7
    assert report.baseline == pytest.approx(0.178, rel=1e-3)
