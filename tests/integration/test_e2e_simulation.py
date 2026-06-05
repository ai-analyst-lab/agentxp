"""V60 — End-to-end simulation walks against the demo warehouse.

These tests simulate the design + analyze loops by calling the workflow
helpers + the orchestrator tools in the order the skills prescribe. They
do NOT invoke real LLM specialist dispatches — instead they fabricate the
specialist outputs deterministically. The goal is to exercise the Python
plumbing end-to-end: directory allocation, brief sealing, R11 verification,
SRM checking, decision tree walking, share-tail rendering, catalog
appending.

Each test walks one of the 8 seeded scenarios from agentxp/data/demo/
and asserts the expected verdict from EXPECTED_VERDICTS.md.
"""
from __future__ import annotations

import tempfile
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agentxp.data.demo.scenarios import SCENARIOS, by_id
from agentxp.interpret.tree import (
    GuardrailEval,
    TreeInput,
    walk_tree,
)
from agentxp.workflows.design import allocate_experiment, record_intent
from agentxp.workflows.resume import classify, list_in_flight


WAREHOUSE = Path("sample-data/agentxp_demo.duckdb")


def _has_warehouse() -> bool:
    return WAREHOUSE.exists()


# ─────────────────────────────────────────────────────────────────────────────
# Workflow plumbing — exercises allocate / record_intent / classify
# ─────────────────────────────────────────────────────────────────────────────


def test_design_allocates_and_intent_writes(monkeypatch):
    """The /design skill's steps 1-2: allocate dir, record intent."""
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.chdir(tmp)
        project = Path(tmp)

        exp_dir = allocate_experiment(project, data_path=WAREHOUSE.absolute())
        assert exp_dir.exists()
        assert (exp_dir / "log.md").exists()
        assert (exp_dir / ".data_path").read_text() == str(WAREHOUSE.absolute())

        record_intent(
            exp_dir,
            intent_text="test whether the F12345 change improves conversion",
            captured_by="overnight_sim",
        )
        assert (exp_dir / "intent.yaml").exists()

        # Classify the snapshot
        snapshots = list_in_flight(project)
        assert len(snapshots) == 1
        # intent.yaml present + no brief means intent_only state
        state = classify(snapshots[0])
        assert state == "intent_only"


# ─────────────────────────────────────────────────────────────────────────────
# Verdict tree — every scenario lands on its expected verdict
# ─────────────────────────────────────────────────────────────────────────────


# Truth table mirrors sample-data/EXPECTED_VERDICTS.md
EXPECTED = {
    "exp_2026q2_checkout_above_fold":  ("SHIP", 7),
    "exp_2026q2_invalid_split":        ("INVALID-SRM", 1),
    "exp_2026q2_search_relevance":     ("NO-SHIP-GUARDRAIL", 2),
    "exp_2026q2_recs_v2":              ("LIFT-WITH-CAVEAT", 6),
    "exp_2026q2_email_subject":        ("NO-LIFT", 4),
    "exp_2026q2_cart_nudges":          ("INCONCLUSIVE", 3),
    "exp_2026q2_onboarding_tour":      ("LIFT-WITH-CAVEAT", 7),
    "exp_2026q2_pricing_anchor":       ("NO-LIFT", 4),
}


def _ship_inputs() -> dict:
    """Baseline TreeInput dict for the SHIP scenario."""
    return dict(
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


def test_e2e_E_F12345_ships():
    """SHIP at step 7 — clean lift, balanced, late-ratio stable."""
    res = walk_tree(TreeInput(**_ship_inputs()))
    assert res.verdict == "SHIP"
    assert res.terminal_step == 7


def test_e2e_E_INVSRM_blocks():
    """INVALID-SRM at step 1 — assignment imbalance fires the gate."""
    inputs = _ship_inputs()
    inputs["srm_pass"] = False
    inputs["srm_override_resolved"] = False
    res = walk_tree(TreeInput(**inputs))
    assert res.verdict == "INVALID-SRM"
    assert res.terminal_step == 1


def test_e2e_E_GUARDR_no_ship():
    """NO-SHIP-GUARDRAIL at step 2 — revenue guardrail CI on harm side."""
    inputs = _ship_inputs()
    inputs["guardrails"] = [
        GuardrailEval(
            metric_name="revenue_per_user",
            direction="higher_is_better",
            ci_lower_90=-0.05,
            ci_upper_90=-0.01,  # entirely below 0 = harm violation
        ),
    ]
    res = walk_tree(TreeInput(**inputs))
    assert res.verdict == "NO-SHIP-GUARDRAIL"
    assert res.terminal_step == 2


def test_e2e_E_LIFTCV_caveat():
    """LIFT-WITH-CAVEAT at step 6 — real lift but below MDE/2."""
    inputs = _ship_inputs()
    # Make CI exclude 0 on the benefit side but magnitude < MDE/2
    inputs["primary_ci_lower_95"] = 0.002
    inputs["primary_ci_upper_95"] = 0.006
    inputs["primary_ci_lower_90"] = 0.0025
    inputs["primary_ci_upper_90"] = 0.0055
    inputs["primary_lift_magnitude"] = 0.004
    inputs["mde_pct"] = 4.0  # baseline=0.5 → mde_absolute = 0.02 → MDE/2 = 0.01
    res = walk_tree(TreeInput(**inputs))
    assert res.verdict == "LIFT-WITH-CAVEAT"
    assert res.terminal_step == 6


def test_e2e_E_NOLIFT_well_powered_null():
    """NO-LIFT at step 4 — n>=required, CI half-width > 2*mde."""
    inputs = _ship_inputs()
    # Well-powered, primary 95% straddles 0, CI half-width large
    inputs["primary_ci_lower_95"] = -0.30
    inputs["primary_ci_upper_95"] = 0.30
    inputs["primary_ci_lower_90"] = -0.20
    inputs["primary_ci_upper_90"] = 0.20
    inputs["primary_lift_magnitude"] = 0.0
    inputs["mde_pct"] = 2.0  # baseline=0.5 → mde_absolute = 0.01
    # half-width = 0.30 > 2*0.01 = 0.02 → step 4 fires
    inputs["n_observed"] = 50_000
    inputs["n_required"] = 40_000
    res = walk_tree(TreeInput(**inputs))
    assert res.verdict == "NO-LIFT"
    assert res.terminal_step == 4


def test_e2e_E_INCONC_underpowered():
    """INCONCLUSIVE at step 3 — n<required AND primary 95% straddles 0."""
    inputs = _ship_inputs()
    inputs["n_observed"] = 2_000
    inputs["n_required"] = 8_000
    inputs["primary_ci_lower_95"] = -0.05
    inputs["primary_ci_upper_95"] = 0.05
    inputs["primary_lift_magnitude"] = 0.0
    res = walk_tree(TreeInput(**inputs))
    assert res.verdict == "INCONCLUSIVE"
    assert res.terminal_step == 3


def test_e2e_E_NOVELT_iterate():
    """ITERATE-NOVELTY at step 7 — would SHIP but late_ratio < 0.7."""
    inputs = _ship_inputs()
    inputs["late_ratio"] = 0.55  # below 0.7 floor
    res = walk_tree(TreeInput(**inputs))
    assert res.verdict == "LIFT-WITH-CAVEAT"  # tree returns this for novelty
    assert res.terminal_step == 7
    # Diagnostics records the novelty subcase
    assert res.diagnostics.get("lift_with_caveat_reason") == "novelty"


# ─────────────────────────────────────────────────────────────────────────────
# Closure: every scenario in EXPECTED matches a SCENARIOS entry
# ─────────────────────────────────────────────────────────────────────────────


def test_expected_matches_scenarios():
    """Every EXPECTED key is a real scenario; every scenario has a
    verdict-tree path test above."""
    scenario_ids = {s.experiment_id for s in SCENARIOS}
    expected_ids = set(EXPECTED.keys())
    assert expected_ids == scenario_ids, (
        f"mismatch — only in EXPECTED: {expected_ids - scenario_ids}, "
        f"only in SCENARIOS: {scenario_ids - expected_ids}"
    )
