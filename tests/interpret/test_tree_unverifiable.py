"""T10 + T11 — UNVERIFIABLE wiring tests for walk_tree.

The verdict tree must short-circuit to UNVERIFIABLE whenever a step's required
input is None, rather than fall through to a SHIP-default. This file covers
each step's null-input contract and asserts the verdict ladder's priority
ordering survives partial-analysis conditions.

Audit context: v1 issue B5 found the tree would fall through to SHIP when a
required input was null; W0.11 added the UNVERIFIABLE Verdict value but did
not wire the short-circuit. W1.6 / T10 lands the wiring; this test file is
the closure-test that asserts the wiring holds.
"""
from __future__ import annotations

import pytest

from agentxp.interpret.tree import (
    REQUIRED_INPUTS_PER_STEP,
    TreeInput,
    Verdict,
    walk_tree,
)


def _ship_inputs(**overrides) -> TreeInput:
    """A baseline TreeInput that walks to SHIP at step 7."""
    base = dict(
        srm_pass=True,
        guardrails=[],
        n_observed=10_000,
        n_required=8_000,
        primary_ci_lower_95=0.05,
        primary_ci_upper_95=0.15,
        primary_ci_lower_90=0.06,
        primary_ci_upper_90=0.14,
        primary_lift_magnitude=0.10,
        primary_direction="higher_is_better",
        mde_pct=2.0,
        baseline=0.50,
    )
    base.update(overrides)
    return TreeInput(**base)


# ─────────────────────────────────────────────────────────────────────────────
# Baseline — the inputs that produce a SHIP without any null
# ─────────────────────────────────────────────────────────────────────────────


def test_baseline_walks_to_ship():
    """Sanity: with all required inputs non-None, the tree walks to SHIP."""
    res = walk_tree(_ship_inputs())
    assert res.verdict == "SHIP"
    assert res.terminal_step == 7


# ─────────────────────────────────────────────────────────────────────────────
# Step 0 — brief-derived inputs (mde_pct, baseline) needed before any step
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("missing_field", ["mde_pct", "baseline"])
def test_brief_derived_null_short_circuits_at_step_0(missing_field):
    """Brief-derived inputs needed by mde_absolute computation fail at step 0."""
    res = walk_tree(_ship_inputs(**{missing_field: None}))
    assert res.verdict == "UNVERIFIABLE"
    assert res.terminal_step == 0
    assert missing_field in res.diagnostics["missing_inputs"]


# ─────────────────────────────────────────────────────────────────────────────
# Per-step null contract — each step's first required input causes
# short-circuit at that step (and not before).
# ─────────────────────────────────────────────────────────────────────────────


def test_srm_pass_null_short_circuits_at_step_1():
    res = walk_tree(_ship_inputs(srm_pass=None))
    assert res.verdict == "UNVERIFIABLE"
    assert res.terminal_step == 1
    assert "srm_pass" in res.diagnostics["missing_inputs"]


def test_primary_ci_95_null_short_circuits_at_step_3():
    # Step 3 is the first step that needs primary CI; n_observed is also
    # needed, but the missing_inputs list will name only the actual nulls.
    res = walk_tree(_ship_inputs(primary_ci_lower_95=None))
    assert res.verdict == "UNVERIFIABLE"
    assert res.terminal_step == 3
    assert "primary_ci_lower_95" in res.diagnostics["missing_inputs"]


def test_n_observed_null_short_circuits_at_step_3():
    res = walk_tree(_ship_inputs(n_observed=None))
    assert res.verdict == "UNVERIFIABLE"
    assert res.terminal_step == 3


def test_primary_ci_90_null_short_circuits_at_step_5():
    res = walk_tree(_ship_inputs(primary_ci_lower_90=None))
    assert res.verdict == "UNVERIFIABLE"
    assert res.terminal_step == 5


def test_primary_lift_magnitude_null_short_circuits_at_step_6():
    res = walk_tree(_ship_inputs(primary_lift_magnitude=None))
    assert res.verdict == "UNVERIFIABLE"
    assert res.terminal_step == 6


# ─────────────────────────────────────────────────────────────────────────────
# No SHIP-default fall-through — confirm the failure mode B5 caught is fixed
# ─────────────────────────────────────────────────────────────────────────────


def test_no_ship_default_when_any_required_input_null():
    """For every field declared in REQUIRED_INPUTS_PER_STEP, setting it to
    None must NOT produce SHIP. This is the closure-test for the B5 bug:
    the tree never falls through to a confident-looking verdict on null
    input."""
    all_required: set[str] = set()
    for fields in REQUIRED_INPUTS_PER_STEP.values():
        all_required.update(fields)
    # Add the brief-derived step-0 fields.
    all_required.update({"mde_pct", "baseline"})

    for field_name in all_required:
        res = walk_tree(_ship_inputs(**{field_name: None}))
        assert res.verdict != "SHIP", (
            f"setting {field_name}=None produced SHIP (the B5 failure mode)"
        )
        assert res.verdict == "UNVERIFIABLE", (
            f"setting {field_name}=None produced {res.verdict}, expected UNVERIFIABLE"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Priority ordering preserved — an SRM failure still wins over missing
# downstream inputs (the verdict ladder's priority is the contract).
# ─────────────────────────────────────────────────────────────────────────────


def test_srm_failure_wins_over_missing_downstream_inputs():
    """An SRM failure at step 1 emits INVALID-SRM even when later required
    inputs are None — the tree never reaches the downstream check, so the
    nulls there are irrelevant."""
    res = walk_tree(
        _ship_inputs(
            srm_pass=False,            # step 1 fires INVALID-SRM
            srm_override_resolved=False,
            primary_ci_lower_95=None,  # would fire UNVERIFIABLE at step 3
            primary_lift_magnitude=None,
        )
    )
    assert res.verdict == "INVALID-SRM"
    assert res.terminal_step == 1


# ─────────────────────────────────────────────────────────────────────────────
# UNVERIFIABLE is in the Verdict closed set
# ─────────────────────────────────────────────────────────────────────────────


def test_unverifiable_is_in_verdict_closed_set():
    import typing
    args = typing.get_args(Verdict)
    assert "UNVERIFIABLE" in args
    assert len(args) == 9, f"expected 9 Verdict values, got {len(args)}: {args}"
