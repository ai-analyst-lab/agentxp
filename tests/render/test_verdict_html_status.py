"""render_verdict_html must quote a computed status, never claim VERIFIED.

Pre-audit the renderer hardcoded ``"render_status": "VERIFIED"`` — every
verdict HTML wore the green badge regardless of what the catalog row (the
computed status) said. Post-fix the renderer takes ``render_status`` from
the caller and defaults to UNVERIFIABLE (it is pure and cannot verify
anything itself).
"""
from __future__ import annotations

from agentxp.render.share_tail_html import render_verdict_html
from agentxp.render.viewmodel import ChartData, Diagnostics, MetricRow, ReportVM


def _vm() -> ReportVM:
    return ReportVM(
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
        charts=ChartData(
            lift_absolute=0.032,
            ci_95_lower=0.014,
            ci_95_upper=0.05,
            ci_90_lower=0.017,
            ci_90_upper=0.047,
            direction="higher_is_better",
        ),
    )


def test_default_status_is_unverifiable_not_verified():
    html = render_verdict_html(vm=_vm())
    assert "VERIFIED" not in html.replace("UNVERIFIABLE", "")
    assert "UNVERIFIABLE" in html


def test_caller_computed_status_is_quoted():
    html = render_verdict_html(vm=_vm(), render_status="DRAFT_UNVERIFIED")
    assert "DRAFT_UNVERIFIED" in html
