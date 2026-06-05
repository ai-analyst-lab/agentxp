"""T40/T41 — spine view-model closure tests.

The four share-tail VMs (IntentVM, DesignBriefVM, MidRunVM, VerdictVM) are
the presentation spine. The critical invariant is on MidRunVM: it must
not carry any outcome-bearing field, so that the system architecturally
cannot peek at experiment outcomes during monitoring.

These tests assert:
  1. Each spine VM exists and has model_config = extra="forbid".
  2. MidRunVM does not declare any forbidden field name (closure-test
     against _MID_RUN_FORBIDDEN_FIELDS).
  3. distill_mid_run signature does not accept analyzer outputs as
     parameters (signature-level enforcement).
  4. distill_intent / distill_design_brief / distill_mid_run are pure
     functions returning valid VMs from valid inputs.
"""
from __future__ import annotations

import inspect

import pytest
from pydantic import ValidationError

from agentxp.render.distill import (
    distill_design_brief,
    distill_intent,
    distill_mid_run,
)
from agentxp.render.viewmodel import (
    DesignBriefVM,
    IntentVM,
    MidRunVM,
    VerdictVM,
    _MID_RUN_FORBIDDEN_FIELDS,
)


# ─────────────────────────────────────────────────────────────────────────────
# Existence + extra="forbid"
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("vm_cls", [IntentVM, DesignBriefVM, MidRunVM, VerdictVM])
def test_spine_vm_is_extra_forbid(vm_cls):
    assert vm_cls.model_config.get("extra") == "forbid", (
        f"{vm_cls.__name__} must be extra='forbid' (R10)"
    )


# ─────────────────────────────────────────────────────────────────────────────
# CRITICAL — MidRunVM peek-prevention closure
# ─────────────────────────────────────────────────────────────────────────────


def test_mid_run_vm_has_no_peek_revealing_fields():
    """The R10 / peek-prevention discipline made executable.

    If a developer adds lift / CI / p-value / per-arm magnitudes to
    MidRunVM, this test fails BEFORE the change can land. Surfacing such
    a field is a visible architectural choice that requires amending
    _MID_RUN_FORBIDDEN_FIELDS too — at which point both edits show up
    in code review.
    """
    declared = set(MidRunVM.model_fields.keys())
    overlap = _MID_RUN_FORBIDDEN_FIELDS & declared
    assert not overlap, (
        f"MidRunVM declares peek-revealing fields: {overlap}. "
        f"See agentxp/render/viewmodel.py and rebuild/CLAUDE.md R10."
    )


def test_distill_mid_run_signature_does_not_accept_analyzer_outputs():
    """The function signature is the wall: no analyzer-output params."""
    sig = inspect.signature(distill_mid_run)
    param_names = set(sig.parameters.keys())
    overlap = _MID_RUN_FORBIDDEN_FIELDS & param_names
    assert not overlap, (
        f"distill_mid_run accepts forbidden params: {overlap}. "
        f"A caller could pass outcome data through these — peek-prevention "
        f"breaks at the signature."
    )


# ─────────────────────────────────────────────────────────────────────────────
# distill functions are pure and produce valid VMs
# ─────────────────────────────────────────────────────────────────────────────


def test_distill_intent_returns_intent_vm():
    vm = distill_intent(
        experiment_id="exp_001",
        intent_text="test whether the new checkout button improves completion",
        captured_at="2026-06-04T14:32:00Z",
        captured_by="shane@aieval.ai",
    )
    assert isinstance(vm, IntentVM)
    assert vm.experiment_id == "exp_001"
    assert "checkout" in vm.intent_text


def test_distill_intent_is_pure():
    """Identical inputs → identical output."""
    args = dict(
        experiment_id="exp_001",
        intent_text="test X",
        captured_at="2026-06-04T14:32:00Z",
        captured_by="user@x",
    )
    a = distill_intent(**args)
    b = distill_intent(**args)
    assert a.model_dump() == b.model_dump()


def test_distill_design_brief_returns_brief_vm():
    vm = distill_design_brief(
        experiment_id="exp_001",
        sealed_brief_payload={
            "hypothesis": "treatment improves conversion",
            "primary_metric": "conversion_rate",
            "primary_decision_rule": "ship if lift_relative > 2% with p < 0.05",
            "mde_text": "+2.0% relative",
            "power_text": "80% at α=0.05, n_required=24,572",
            "guardrails_summary": ["revenue: no decrease > 1%"],
            "cohorts_summary": ["all new_users"],
            "expected_arm_ratio_text": "50/50 control / treatment",
        },
        integrity_lock={
            "design_chain_hash": "a" * 64,
            "metric_snapshot": {"conversion_rate": "b" * 64, "revenue": "c" * 64},
            "expected_shape": {"assignment_unit": "user_id"},
            "sealed_at": "2026-06-04T15:00:00Z",
        },
    )
    assert isinstance(vm, DesignBriefVM)
    assert vm.metric_snapshot_count == 2
    assert vm.design_chain_hash_short.startswith("a" * 12)


def test_distill_mid_run_returns_mid_run_vm():
    vm = distill_mid_run(
        experiment_id="exp_001",
        halt_reason="srm_yellow",
        halt_summary_text="assignment ratio drifted past warning threshold",
        triggered_at="2026-06-08T12:00:00Z",
        elapsed_text="ran for 4 days; halt fired at day 4 12:00 UTC",
        suggested_resolutions=[
            "wait for additional data and re-check at day 7",
            "investigate the assignment service for misconfiguration",
            "override and continue (record reason)",
        ],
        srm_chi2=0.0008,
        srm_threshold=0.0005,
    )
    assert isinstance(vm, MidRunVM)
    assert vm.halt_reason == "srm_yellow"
    # The VM does not even allow setting lift; defensive check.
    with pytest.raises(ValidationError):
        MidRunVM(
            experiment_id="exp_001",
            halt_reason="srm_yellow",
            halt_summary_text="x",
            triggered_at="2026-06-08T12:00:00Z",
            elapsed_text="x",
            suggested_resolutions=[],
            lift=0.10,  # FORBIDDEN — extra=forbid rejects
        )


# ─────────────────────────────────────────────────────────────────────────────
# Closure: every halt_reason is in the Literal set
# ─────────────────────────────────────────────────────────────────────────────


_VALID_HALT_REASONS = {"srm_yellow", "srm_red", "guardrail_breach", "exposure_stale"}


@pytest.mark.parametrize("reason", _VALID_HALT_REASONS)
def test_mid_run_vm_accepts_each_halt_reason(reason):
    vm = MidRunVM(
        experiment_id="exp_001",
        halt_reason=reason,
        halt_summary_text="x",
        triggered_at="2026-06-08T12:00:00Z",
        elapsed_text="x",
        suggested_resolutions=[],
    )
    assert vm.halt_reason == reason


def test_mid_run_vm_rejects_invalid_halt_reason():
    with pytest.raises(ValidationError):
        MidRunVM(
            experiment_id="exp_001",
            halt_reason="something_else",
            halt_summary_text="x",
            triggered_at="2026-06-08T12:00:00Z",
            elapsed_text="x",
            suggested_resolutions=[],
        )
