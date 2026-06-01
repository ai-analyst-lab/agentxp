"""W2 glance adapter tests — 3-line verdict-first terminal readout.

Glance is rendered against a ViewBundle (VM + provenance), so these tests pin:
  - line 1 carries the verdict + lift + CI + guardrail phrase + confidence,
    all VERBATIM off the VM (no arithmetic in the adapter);
  - line 2 is the mandatory receipt with an HONEST chain token (OK / MISMATCH /
    unverifiable) derived from the live minimal hash check, never "verified";
  - the adapter itself emits exactly 2 lines (the optional hint is CLI chrome).
"""
from __future__ import annotations

from agentxp.render.adapters.glance import GLANCE_HINT, GlanceAdapter
from agentxp.render.provenance import Provenance, RenderStatus
from agentxp.render.viewmodel import (
    Diagnostics,
    GuardrailViolation,
    MetricRow,
    ReportVM,
    ViewBundle,
)


def _vm(**overrides) -> ReportVM:
    defaults = dict(
        experiment_id="exp_001",
        experiment_name="exp_001",
        verdict="SHIP",
        confidence_label="highly likely positive",
        rationale_one_line="Completion up; guardrails clear.",
        generated_at="2026-06-02T17:55:11+00:00",
        metric_table=[
            MetricRow(
                name="checkout_completion_rate",
                direction="higher_is_better",
                lift_str="+0.032 (+18.0%)",
                ci_95="[+0.014, +0.05]",
                ci_90="[+0.017, +0.047]",
                status="SHIP",
            )
        ],
        diagnostics=Diagnostics(srm_pass=True, late_ratio=0.87),
        uncertainty_notes=[],
        audit_trail=[],
    )
    defaults.update(overrides)
    return ReportVM(**defaults)


def _prov(**overrides) -> Provenance:
    defaults = dict(
        experiment_id="exp_001",
        render_status=RenderStatus.UNVERIFIABLE,
        status_reason="chain hash matches the recorded value",
        chain_hash_stored="abc123",
        chain_hash_live="abc123",
        hash_matches=True,
        replay_command="agentxp audit exp_001",
    )
    defaults.update(overrides)
    return Provenance(**defaults)


def _bundle(vm=None, prov=None) -> ViewBundle:
    return ViewBundle(vm=vm or _vm(), provenance=prov or _prov())


def test_glance_is_two_lines():
    out = GlanceAdapter().render(_bundle())
    lines = out.splitlines()
    assert len(lines) == 2


def test_glance_line1_carries_verdict_lift_ci_confidence_verbatim():
    out = GlanceAdapter().render(_bundle())
    line1 = out.splitlines()[0]
    assert "SHIP" in line1
    assert "+0.032 (+18.0%)" in line1
    assert "[+0.014, +0.05]" in line1
    assert "guardrails clear" in line1
    assert "highly likely positive" in line1


def test_glance_receipt_reads_OK_when_hash_matches():
    out = GlanceAdapter().render(_bundle())
    line2 = out.splitlines()[1]
    assert "agentxp audit exp_001" in line2
    assert "chain OK" in line2


def test_glance_receipt_reads_MISMATCH_on_active_failure():
    prov = _prov(
        render_status=RenderStatus.DRAFT_UNVERIFIED,
        status_reason="recomputed hash != recorded",
        chain_hash_live="deadbeef",
        hash_matches=False,
    )
    out = GlanceAdapter().render(_bundle(prov=prov))
    lines = out.splitlines()
    # W3-T4: an active failure prepends a DRAFT banner before the verdict; the
    # receipt line still carries the honest MISMATCH token.
    assert lines[0].startswith("⚠ DRAFT — UNVERIFIED")
    assert "chain MISMATCH" in out


def test_glance_receipt_reads_unverifiable_when_cannot_check():
    prov = _prov(
        status_reason="log.jsonl absent",
        chain_hash_live=None,
        hash_matches=None,
    )
    out = GlanceAdapter().render(_bundle(prov=prov))
    assert "chain unverifiable" in out.splitlines()[1]


def test_glance_guardrail_phrase_counts_violations():
    vm = _vm(
        diagnostics=Diagnostics(
            srm_pass=True,
            guardrails_violated=[GuardrailViolation(metric="latency_p95", detail="+12%")],
        )
    )
    out = GlanceAdapter().render(_bundle(vm=vm))
    assert "1 guardrail violation" in out.splitlines()[0]


def test_glance_flags_are_text_not_node():
    a = GlanceAdapter()
    assert a.format_id == "glance"
    assert a.binary is False
    assert a.requires_node is False
    assert GLANCE_HINT  # the hint text lives in the adapter module
