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
from agentxp.render.provenance import RenderStatus
from agentxp.render.viewmodel import (
    AuditRow,
    ChartData,
    DesignCard,
    Diagnostics,
    GuardrailViolation,
    IndexRowVM,
    IndexVM,
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
        # Human-readable title when the brief recorded one (schema v2 `name`),
        # else the id. Single source so adapters never guess.
        experiment_name=report.name or report.experiment_id,
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


# ──────────────────────────────────────────────────────────────────────────
# distill_index — the pure cross-experiment projection
# ──────────────────────────────────────────────────────────────────────────

def distill_index(rows: list[IndexRowVM]) -> IndexVM:
    """Aggregate already-built index rows into an :class:`IndexVM` with tallies.

    PURE: no I/O, no re-derivation. Each row was projected once (via
    ``ReportVM.to_index_row`` or ``IndexRowVM.error_row``) at the I/O boundary
    in the index adapter — the only place a render status can be resolved (that
    needs ``build_provenance``, which is impure). This function never touches a
    raw ``Report``; it only counts statuses, so the index stays a strict
    projection over numbers that were each formatted exactly once.
    """
    n_verified = sum(1 for r in rows if r.render_status is RenderStatus.VERIFIED)
    n_draft = sum(
        1 for r in rows if r.render_status is RenderStatus.DRAFT_UNVERIFIED
    )
    n_unverifiable = sum(
        1 for r in rows if r.render_status is RenderStatus.UNVERIFIABLE
    )
    return IndexVM(
        rows=rows,
        n_total=len(rows),
        n_verified=n_verified,
        n_draft=n_draft,
        n_unverifiable=n_unverifiable,
    )


# ──────────────────────────────────────────────────────────────────────────
# Spine distill functions (T41) — one per share-tail moment.
#
# Each is PURE: no I/O, no time.time(), no chain access, no re-derivation.
# The orchestrator computes inputs and passes them in; the function
# projects them into the corresponding spine VM.
#
# distill_mid_run's signature is the wall: it does NOT accept analyzer
# outputs as parameters. Adding such a parameter would surface as a
# visible signature change AND fail the closure test in
# tests/render/test_spine_vms.py.
# ──────────────────────────────────────────────────────────────────────────

from agentxp.render.viewmodel import (   # noqa: E402 — at bottom for layer ordering
    DesignBriefVM,
    IntentVM,
    MidRunVM,
    VerdictVM,
)


def distill_intent(
    *,
    experiment_id: str,
    intent_text: str,
    captured_at: str,
    captured_by: str,
) -> IntentVM:
    """T41 — pure distill for the intent share-tail moment (design verb).

    Renders the user's pre-registered intent without any analysis context.
    Identical inputs produce identical output (audit replay).
    """
    return IntentVM(
        experiment_id=experiment_id,
        intent_text=intent_text,
        captured_at=captured_at,
        captured_by=captured_by,
    )


def _power_curve_svg(n_per_group: int, mde_pct: float, baseline: float) -> dict:
    """Build an inline SVG polyline + tick labels for the power-vs-MDE curve.

    Approximation: at α=0.05, power=0.80, two-proportion,
        n ≈ 16 · p · (1−p) / (baseline · mde_rel)²
    Sweep mde over [0.25×, 4×] of the design MDE.
    """
    svg_x0, svg_x1 = 80, 600
    svg_y0, svg_y1 = 20, 160
    plot_w, plot_h = svg_x1 - svg_x0, svg_y1 - svg_y0
    mde_rel = max(mde_pct / 100.0, 1e-6)
    mde_min = max(0.005, mde_rel * 0.25)
    mde_max = mde_rel * 4.0

    def n_for(m: float) -> float:
        if m <= 0:
            return 1e9
        return 16.0 * baseline * (1.0 - baseline) / (baseline * m) ** 2

    y_max_n = max(n_per_group * 4, n_for(mde_min)) or 1.0

    def x_for(m: float) -> float:
        return svg_x0 + (m - mde_min) / (mde_max - mde_min) * plot_w

    def y_for(n: float) -> float:
        return svg_y1 - min(1.0, n / y_max_n) * plot_h

    pts = [
        f"{x_for(mde_min + i * (mde_max - mde_min) / 39):.1f},"
        f"{y_for(n_for(mde_min + i * (mde_max - mde_min) / 39)):.1f}"
        for i in range(40)
    ]
    y_ticks = [
        {"y": svg_y0 + i * (plot_h / 4), "label": f"{int(y_max_n * (3 - i) / 4):,}"}
        for i in range(4)
    ]
    x_ticks = [
        {"x": x_for(mde_min + i * (mde_max - mde_min) / 4),
         "label": f"{(mde_min + i * (mde_max - mde_min) / 4) * 100:.1f}%"}
        for i in range(5)
    ]
    return {
        "curve_points": " ".join(pts),
        "y_ticks": y_ticks,
        "x_ticks": x_ticks,
        "design_x": x_for(mde_rel),
        "design_y": y_for(n_per_group),
    }


def distill_design_brief(
    *,
    experiment_id: str,
    sealed_brief_payload: dict,
    integrity_lock: dict,
    scenario_meta: Optional[dict] = None,
) -> DesignBriefVM:
    """T41 — pure distill for the design-brief share-tail moment.

    Renders the sealed brief + integrity lock receipt. Fires after the
    brief seals (the design verb's terminal share-tail). No analysis
    output exists at this moment by R11 (the wall has not been crossed).

    ``scenario_meta`` carries editorial fields the brief itself does not
    pre-register (display_name, owner_team, mechanism_prose, decision_rule
    short summary, historical_baseline_context, secondary_metric_names).
    All optional; the template tolerates empties.
    """
    brief = sealed_brief_payload
    meta = scenario_meta or {}
    expected = brief.get("expected_shape", {}) or integrity_lock.get(
        "expected_shape", {}
    )
    chain_hash = integrity_lock.get("design_chain_hash", "")
    metric_snapshot = integrity_lock.get("metric_snapshot", {}) or {}

    # Derived numerics — defensive against missing fields (tests pass partial briefs).
    baseline = float(brief.get("baseline", 0.0) or 0.0)
    mde_pct = float(brief.get("mde_pct", 0.0) or 0.0)
    n_total = int(brief.get("n_required", 0) or 0)
    n_per_group = max(n_total // 2, 0)
    arms = list(brief.get("arms", []) or [])

    # Guardrails — both structured + summary lines for the table block.
    guardrails = list(brief.get("guardrails", []) or [])
    guardrails_summary = brief.get("guardrails_summary") or [
        f"{g['metric_name']} ({g.get('direction', '?')}) — "
        f"nim_relative = {g.get('nim_relative', 0):+}"
        for g in guardrails
    ]

    # Power text + duration text — built once here so the template can read flat strings.
    power_text = brief.get("power_text") or (
        f"80% power at α=0.05, two-sided; baseline {baseline:.2f}, "
        f"MDE {brief.get('mde_text', '')}, n_required = {n_total:,}"
        if n_total
        else ""
    )
    duration_text = meta.get("duration_text", "")

    # Section prose — falls back to neutral defaults if the orchestrator did
    # not supply scenario-specific copy.
    primary_metric_name = brief.get("primary_metric", "")
    guardrail_names = ", ".join(g.get("metric_name", "") for g in guardrails)
    at_a_glance_prose = meta.get("at_a_glance_prose") or (
        f"Pre-registered before any analysis. Decision is binary against "
        f"{primary_metric_name}: a {brief.get('mde_text', '')} relative lift "
        f"over a {baseline * 100:.1f}% baseline requires {n_per_group:,} per "
        f"arm at the standard α / power settings. "
        f"Guardrails: {guardrail_names}." if primary_metric_name else ""
    )
    metrics_section_prose = meta.get("metrics_section_prose") or (
        f"Primary is {primary_metric_name}; secondaries inform interpretation "
        f"but do not influence the verdict. Guardrails block ship if their CI "
        f"crosses the pre-registered non-inferiority margin in the adverse "
        f"direction."
    )
    power_section_prose = meta.get("power_section_prose") or (
        f"To resolve a {brief.get('mde_text', '')} relative effect against a "
        f"{baseline * 100:.1f}% baseline, the design requires {n_per_group:,} "
        f"per arm. Tighter detection thresholds climb the curve to the left."
        if n_per_group else ""
    )
    assignment_section_prose = meta.get("assignment_section_prose") or (
        (
            f"Each user is randomly assigned at first exposure to "
            f"{arms[0]} or {arms[1]} in a {brief.get('expected_arm_ratio_text', '')} "
            f"split. Events before first_exposure_at are not attributed to "
            f"the experiment."
        ) if len(arms) >= 2 else ""
    )

    # Power curve — only meaningful when we have the inputs.
    if n_per_group and mde_pct and baseline:
        pc = _power_curve_svg(n_per_group, mde_pct, baseline)
    else:
        pc = {"curve_points": "", "y_ticks": [], "x_ticks": [],
              "design_x": 0.0, "design_y": 0.0}

    return DesignBriefVM(
        experiment_id=experiment_id,
        display_name=meta.get("display_name", ""),
        owner_team=meta.get("owner_team", ""),
        hypothesis_text=brief.get("hypothesis", ""),
        mechanism_prose=meta.get("mechanism_prose", ""),
        historical_baseline_context=meta.get("historical_baseline_context", ""),
        primary_metric_name=primary_metric_name,
        primary_metric_type=brief.get("primary_metric_type", "proportion"),
        primary_direction=brief.get("primary_direction", "higher_is_better"),
        primary_decision_rule=brief.get("primary_decision_rule", ""),
        decision_rule_short=meta.get("decision_rule_short", ""),
        secondary_metric_names=meta.get("secondary_metric_names", []),
        mde_text=brief.get("mde_text", ""),
        baseline=baseline,
        power_text=power_text,
        n_per_group=n_per_group,
        n_total=n_total,
        duration_text=duration_text,
        guardrails=guardrails,
        guardrails_summary=guardrails_summary,
        cohorts=list(brief.get("cohorts", []) or []),
        cohorts_summary=brief.get("cohorts_summary", []),
        assignment_unit=expected.get("assignment_unit", "user_id"),
        arms=arms,
        expected_arm_ratio_text=brief.get("expected_arm_ratio_text", ""),
        at_a_glance_prose=at_a_glance_prose,
        metrics_section_prose=metrics_section_prose,
        power_section_prose=power_section_prose,
        assignment_section_prose=assignment_section_prose,
        power_curve_points=pc["curve_points"],
        power_x_ticks=pc["x_ticks"],
        power_y_ticks=pc["y_ticks"],
        design_x=pc["design_x"],
        design_y=pc["design_y"],
        design_chain_hash=chain_hash,
        design_chain_hash_short=(chain_hash[:12] + "…") if chain_hash else "",
        metric_snapshot=metric_snapshot,
        metric_snapshot_count=len(metric_snapshot),
        sealed_at=integrity_lock.get("sealed_at", ""),
        sealed_by=integrity_lock.get("sealed_by", ""),
    )


def distill_mid_run(
    *,
    experiment_id: str,
    halt_reason: str,
    halt_summary_text: str,
    triggered_at: str,
    elapsed_text: str,
    suggested_resolutions: list[str],
    srm_chi2: Optional[float] = None,
    srm_threshold: Optional[float] = None,
) -> MidRunVM:
    """T41 — pure distill for the monitor-halt share-tail moment.

    PEEK-PREVENTION PROPERTY: the signature **does not accept** lift, CI,
    p-value, per-arm magnitudes, or any other analyzer-output parameter.
    A caller cannot pass outcome information through — the function
    signature is the wall. The closure test in tests/render/test_spine_vms.py
    asserts this property programmatically.

    Fires only when the orchestrator's automated monitor halt fires
    (SRM yellow/red, guardrail breach, exposure stale). Never on routine
    progress; the user reads the mid-run readout only when an action is
    required.
    """
    return MidRunVM(
        experiment_id=experiment_id,
        halt_reason=halt_reason,    # type: ignore[arg-type]
        halt_summary_text=halt_summary_text,
        triggered_at=triggered_at,
        elapsed_text=elapsed_text,
        suggested_resolutions=suggested_resolutions,
        srm_chi2=srm_chi2,
        srm_threshold=srm_threshold,
    )


def distill_verdict(report: Report) -> VerdictVM:
    """T41 — pure distill for the verdict-committed share-tail moment.

    VerdictVM = ReportVM (same shape, share-tail framing). This wrapper
    exists so the orchestrator can use the same distill_* API shape for
    all four spine moments.
    """
    return distill(report)


__all__ = [
    "distill",
    "distill_index",
    "distill_intent",
    "distill_design_brief",
    "distill_mid_run",
    "distill_verdict",
]
