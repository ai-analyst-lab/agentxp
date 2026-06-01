"""``distill()`` — the single, PURE projection from canonical Report to ReportVM.

Contract (the keystone of the presentation layer):
  - PURE: no I/O, no clock, no network, no warehouse, no audit log, no numpy.
    Given the same ``Report`` it returns an equal ``ReportVM`` every time and
    never mutates its input.
  - SOLE formatter: every number a human sees (lift, CI, sample %, ratios) is
    formatted here, exactly once. Adapters interpolate strings; they never do
    arithmetic.
  - SOLE version-skew handler: branches on ``report.schema_version`` so no
    downstream code has to. A v1 report distills to a valid (if sparser) VM.
  - Carries agent prose VERBATIM: ``verdict_rationale`` and each
    ``UncertaintyNote.detail`` pass through untouched. Drift there is a bug.
  - NEVER calls ``build_provenance()``. Verification is a separate impure step.
"""
from __future__ import annotations

from typing import Optional
from pathlib import PurePosixPath

from agentxp.schemas.report import MetricResult, Report
from agentxp.render.viewmodel import (
    AuditRow,
    ChartData,
    DesignCard,
    Diagnostics,
    GuardrailViolation,
    MetricRow,
    ReportVM,
)


# ──────────────────────────────────────────────────────────────────────────
# Formatting primitives — the ONLY place numbers become strings.
# ──────────────────────────────────────────────────────────────────────────

def _fmt_signed(x: float) -> str:
    """Signed compact float, e.g. 0.032 -> '+0.032', -1.4 -> '-1.4'."""
    return f"{x:+.4g}"


def _fmt_lift(absolute: float, relative: float) -> str:
    """Headline lift string: absolute with relative in parens, e.g. '+0.032 (+18.0%)'."""
    return f"{_fmt_signed(absolute)} ({relative:+.1f}%)"


def _fmt_ci(lower: float, upper: float) -> str:
    """CI interval string, e.g. '[+0.014, +0.05]'."""
    return f"[{_fmt_signed(lower)}, {_fmt_signed(upper)}]"


def _sample_pct(n_observed: Optional[int], n_required: Optional[int]) -> Optional[int]:
    """Observed-vs-required as a rounded percent, or None when either is absent."""
    if n_observed is None or not n_required:
        return None
    return round(n_observed / n_required * 100)


def _direction(d: Optional[str]) -> str:
    """Map a possibly-None canonical direction to the VM's closed set."""
    return d if d in ("higher_is_better", "lower_is_better", "neither") else "neither"


# ──────────────────────────────────────────────────────────────────────────
# Row builders
# ──────────────────────────────────────────────────────────────────────────

def _metric_row(m: MetricResult, *, status: str) -> MetricRow:
    return MetricRow(
        name=m.name,
        direction=_direction(m.direction),
        lift_str=_fmt_lift(m.lift_absolute, m.lift_relative),
        ci_95=_fmt_ci(m.ci_95_lower, m.ci_95_upper),
        ci_90=_fmt_ci(m.ci_90_lower, m.ci_90_upper),
        status=status,
    )


def _metric_table(report: Report) -> list[MetricRow]:
    """Flatten primary + guardrails + negative controls + segments → rows.

    Status is assigned WITHOUT re-deriving any verdict: the primary carries the
    committed verdict; guardrails/controls are "clear" (a real violation is
    surfaced separately via ``edge_case_flags`` → ``guardrails_violated``);
    each segment row is tagged "segment".
    """
    rows = [_metric_row(report.primary, status=report.verdict)]
    rows += [_metric_row(g, status="clear") for g in report.guardrails]
    rows += [_metric_row(nc, status="clear") for nc in report.negative_controls]
    rows += [
        _metric_row(s.primary, status="segment")
        for s in report.segments
    ]
    # Give segment rows their segment name rather than the inner metric name.
    seg_start = 1 + len(report.guardrails) + len(report.negative_controls)
    for row, seg in zip(rows[seg_start:], report.segments):
        row.name = f"{seg.segment_name} (segment)"
    return rows


def _guardrails_violated(report: Report) -> list[GuardrailViolation]:
    """Surface guardrail violations from committed edge-case flags (no re-derivation)."""
    out: list[GuardrailViolation] = []
    for flag in report.edge_case_flags:
        if flag.name == "guardrail_violation" and flag.status in ("flagged", "blocking"):
            out.append(GuardrailViolation(metric=flag.name, detail=flag.detail))
    return out


def _audit_trail(report: Report) -> list[AuditRow]:
    """Build the audit-trail rows from the cited bundle artifacts, purely.

    The richer per-stage timeline (with action ids from log.jsonl) is an I/O
    concern that lives in provenance/audit, not in this pure function. Here we
    cite the artifacts the report itself references, stamped with the report's
    own ``generated_at``.
    """
    committed_at = report.generated_at.isoformat()
    rows = [
        AuditRow(
            stage=PurePosixPath(bundle).name,
            committed_at=committed_at,
            action_id=bundle,
        )
        for bundle in report.audit_paths.bundles
    ]
    return rows


def _chart_data(report: Report) -> ChartData:
    """Carry the primary metric's stored numbers through for the SVG charts.

    Pure copy — no arithmetic, no inference. Per-arm counts pass through as-is
    (Optional), so a report without them yields a ChartData whose srm_split
    will omit downstream.
    """
    p = report.primary
    return ChartData(
        lift_absolute=p.lift_absolute,
        ci_95_lower=p.ci_95_lower,
        ci_95_upper=p.ci_95_upper,
        ci_90_lower=p.ci_90_lower,
        ci_90_upper=p.ci_90_upper,
        direction=_direction(p.direction),
        n_arm_control=p.n_arm_control,
        n_arm_treatment=p.n_arm_treatment,
    )


def _design_card(report: Report) -> DesignCard:
    return DesignCard(
        hypothesis=report.hypothesis,
        mde_pct=report.mde_pct,
        power=report.power,
        ci_level=report.ci_level,
        n_required=report.n_required,
        baseline=report.baseline,
    )


# ──────────────────────────────────────────────────────────────────────────
# distill — the public, pure entry point
# ──────────────────────────────────────────────────────────────────────────

def distill(report: Report) -> ReportVM:
    """Project a canonical ``Report`` into a fully-formatted ``ReportVM``.

    Pure and idempotent. ``report`` is not mutated. Never performs I/O and
    never calls ``build_provenance``.
    """
    diagnostics = Diagnostics(
        srm_pass=report.diagnostics.srm_passed,
        n_observed=report.n_observed,
        n_required=report.n_required,
        sample_pct=_sample_pct(report.n_observed, report.n_required),
        late_ratio=report.late_ratio,
        guardrails_violated=_guardrails_violated(report),
    )

    return ReportVM(
        experiment_id=report.experiment_id,
        # The canonical Report has no separate display name; use the id until a
        # name field is added. Kept as a single source so adapters never guess.
        experiment_name=report.experiment_id,
        verdict=str(report.verdict),
        confidence_label=str(report.primary.confidence_label.value),
        rationale_one_line=report.verdict_rationale,  # verbatim agent prose
        generated_at=report.generated_at.isoformat(),
        metric_table=_metric_table(report),
        diagnostics=diagnostics,
        uncertainty_notes=[n.detail for n in report.uncertainty_notes],  # verbatim
        audit_trail=_audit_trail(report),
        design=_design_card(report),
        charts=_chart_data(report),
    )


__all__ = ["distill"]
