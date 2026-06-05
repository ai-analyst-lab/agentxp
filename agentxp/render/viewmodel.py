"""Render view-models — the flat projection every adapter renders against.

`distill()` (``agentxp/render/distill.py``) is the SOLE producer of a
:class:`ReportVM` from the canonical ``agentxp.schemas.report.Report``. Adapters
(markdown, glance, html, …) consume a :class:`ViewBundle` — never the canonical
``Report`` directly — so numbers are formatted exactly once, in ``distill()``,
and the authenticity receipts travel inseparably alongside the rendered numbers.

Layering:
    report.json  --distill()-->  ReportVM           (pure, no I/O)
    report.json  --build_provenance()-->  Provenance (impure: hashes, chain)
    CLI assembles ViewBundle(ReportVM, Provenance)   --> adapter.render(bundle)

This module imports the provenance contract (``Provenance`` / ``RenderStatus``)
but provenance.py never imports this module — the dependency is one-directional.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from agentxp.render.provenance import Provenance, RenderStatus

# Re-export so adapters can `from agentxp.render.viewmodel import RenderStatus`.
__all__ = [
    "MetricRow",
    "GuardrailViolation",
    "Diagnostics",
    "ChartData",
    "AuditRow",
    "DesignCard",
    "IndexRowVM",
    "IndexVM",
    "ReportVM",
    "ViewBundle",
    "Provenance",
    "RenderStatus",
    # Spine VMs (T40)
    "IntentVM",
    "DesignBriefVM",
    "MidRunVM",
    "VerdictVM",
    "_MID_RUN_FORBIDDEN_FIELDS",
]


# ──────────────────────────────────────────────────────────────────────────
# Row / block sub-models — all strings are PREFORMATTED by distill().
# An adapter never does arithmetic or number formatting; it interpolates.
# ──────────────────────────────────────────────────────────────────────────

class MetricRow(BaseModel):
    """One row in the headline-metrics table. Strings preformatted by distill()."""
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    name: str
    direction: Literal["higher_is_better", "lower_is_better", "neither"]
    lift_str: str        # e.g., "+0.032 (+18.0%)" — absolute (relative)
    ci_95: str           # e.g., "[+0.014, +0.05]"
    ci_90: str           # e.g., "[+0.017, +0.047]"
    status: str          # e.g., "SHIP", "clear", "violated", "segment"


class GuardrailViolation(BaseModel):
    """One row in the optional guardrail-violations subsection."""
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    metric: str
    detail: str


class Diagnostics(BaseModel):
    """Flat diagnostics block — the 5-flag panel inputs.

    ``n_observed`` / ``n_required`` / ``sample_pct`` are Optional because a
    pre-widening (schema_version 1) report does not carry them; distill() maps
    a missing value to ``None`` rather than fabricating one.
    """
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    srm_pass: bool
    n_observed: Optional[int] = None
    n_required: Optional[int] = None
    sample_pct: Optional[int] = None                    # e.g., 107 for 107%
    late_ratio: Optional[float] = None                  # None → "unavailable"
    guardrails_violated: list[GuardrailViolation] = Field(default_factory=list)


class ChartData(BaseModel):
    """Raw stored numbers the SVG charts plot — copied, never re-derived.

    distill() carries the primary metric's stored values through verbatim so
    ``charts.py`` can plot them without touching the canonical Report. The
    per-arm counts are Optional: when absent, ``charts.srm_split`` omits rather
    than fabricating a split.
    """
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    lift_absolute: float
    ci_95_lower: float
    ci_95_upper: float
    ci_90_lower: float
    ci_90_upper: float
    direction: Literal["higher_is_better", "lower_is_better", "neither"]
    n_arm_control: Optional[int] = None
    n_arm_treatment: Optional[int] = None


class AuditRow(BaseModel):
    """One row in the audit-trail table — artifact + commit timestamp + ref."""
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    stage: str           # artifact / stage name, e.g. "analyzer.out.yaml"
    committed_at: str    # ISO-8601 string, already formatted by distill()
    action_id: str       # path or ULID; markdown template truncates to 12 chars


class DesignCard(BaseModel):
    """Pre-registered design parameters — display surface for the exec card (W4).

    All Optional: a v1 report omits these; distill() carries them through when
    present and leaves them None otherwise (rendered as "not recorded").
    """
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    hypothesis: Optional[str] = None
    mde_pct: Optional[float] = None
    power: Optional[float] = None
    ci_level: float = 0.95
    n_required: Optional[int] = None
    baseline: Optional[float] = None


class IndexRowVM(BaseModel):
    """One row in the static experiment-index navigator (W6).

    Built from a ReportVM + the resolved render status so the index can show a
    verdict, confidence, a one-line lift + CI, and the verification badge per
    experiment. An experiment that could not be read/validated yields an
    ERROR row (``error`` set, placeholder display strings, status UNVERIFIABLE)
    so one bad experiment never aborts the whole index.
    """
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    experiment_id: str
    experiment_name: str
    verdict: str
    confidence_label: str
    lift_str: str
    ci_95: str
    generated_at: str
    render_status: RenderStatus
    error: Optional[str] = None

    @classmethod
    def error_row(cls, experiment_id: str, error: str) -> "IndexRowVM":
        """A status-only row for an experiment whose report.json can't be read.

        Carries no derived numbers (there is no valid Report to derive from) —
        just the id, the error marker, and an UNVERIFIABLE badge.
        """
        return cls(
            experiment_id=experiment_id,
            experiment_name=experiment_id,
            verdict="—",
            confidence_label="—",
            lift_str="—",
            ci_95="—",
            generated_at="",
            render_status=RenderStatus.UNVERIFIABLE,
            error=error,
        )


class IndexVM(BaseModel):
    """The cross-experiment navigator projection — a list of rows + tallies.

    Pure projection: ``distill_index`` aggregates already-built rows and counts
    their statuses. It re-derives nothing; the per-row verdict/lift/CI strings
    were each formatted once by the single-experiment ``distill()``.
    """
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    rows: list[IndexRowVM]
    n_total: int
    n_verified: int
    n_draft: int
    n_unverifiable: int


# ──────────────────────────────────────────────────────────────────────────
# ReportVM — the full flat projection a single-experiment adapter renders.
# Field names match templates/experiment-report.md so the markdown template
# renders against this unchanged.
# ──────────────────────────────────────────────────────────────────────────

class ReportVM(BaseModel):
    """Flat, fully-formatted projection of one experiment's ``report.json``.

    The canonical ``Report`` holds numbers; ``ReportVM`` holds the strings a
    human reads. distill() is the only producer. Agent prose
    (``rationale_one_line``, ``uncertainty_notes``) is carried VERBATIM — any
    drift there is a bug, not a formatting choice.
    """
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    experiment_id: str
    experiment_name: str
    verdict: str                       # one of §1.8.17 8 values
    confidence_label: str              # one of §1.8.10 7 values
    rationale_one_line: str            # verbatim report.verdict_rationale
    generated_at: str                  # ISO-8601, formatted by distill()
    metric_table: list[MetricRow]
    diagnostics: Diagnostics
    uncertainty_notes: list[str]       # 1-5 caveats, verbatim
    audit_trail: list[AuditRow]
    design: DesignCard = Field(default_factory=DesignCard)
    charts: ChartData

    def to_index_row(self, render_status: RenderStatus) -> IndexRowVM:
        """Project this VM into an index row, given a resolved render status.

        Pure projection — reuses the already-formatted primary lift/CI strings
        rather than reformatting any number.
        """
        primary = self.metric_table[0] if self.metric_table else None
        return IndexRowVM(
            experiment_id=self.experiment_id,
            experiment_name=self.experiment_name,
            verdict=self.verdict,
            confidence_label=self.confidence_label,
            lift_str=primary.lift_str if primary else "n/a",
            ci_95=primary.ci_95 if primary else "n/a",
            generated_at=self.generated_at,
            render_status=render_status,
        )


# ──────────────────────────────────────────────────────────────────────────
# ViewBundle — (formatted numbers + authenticity receipts), assembled by the CLI
# ──────────────────────────────────────────────────────────────────────────

class ViewBundle(BaseModel):
    """What every adapter receives: the formatted VM plus its provenance.

    The CLI assembles ``ViewBundle(distill(report), build_provenance(report,
    exp_dir))``. Bundling the receipts WITH the numbers is the structural
    guarantee that polish never travels without proof — an adapter cannot emit
    the verdict block while dropping the chain-hash receipt, because both arrive
    in the same object.
    """
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)
    schema_version: Literal[1] = 1
    vm: ReportVM
    provenance: Provenance

    @property
    def render_status(self) -> RenderStatus:
        return self.provenance.render_status


# ──────────────────────────────────────────────────────────────────────────
# Spine VMs (T40) — one per share-tail moment.
#
# Each fires inline (chat) and on disk after a specific orchestrator commit:
#   - IntentVM       after intent capture          (design verb)
#   - DesignBriefVM  after brief seal              (design verb)
#   - MidRunVM       on monitor halt only          (analyze verb)
#   - VerdictVM      after verdict commits         (analyze verb; this is
#                                                   essentially a slice of
#                                                   the existing ReportVM)
#
# All have extra="forbid". The critical peek-prevention invariant is on
# MidRunVM: it MUST NOT carry any outcome-bearing field (lift, CI, p_value,
# per-arm magnitudes). The closure test in tests/render/test_spine_vms.py
# asserts this — a developer who adds such a field gets caught at code
# review by the test, not at production by a peek.
# ──────────────────────────────────────────────────────────────────────────


class IntentVM(BaseModel):
    """The user's pre-registered intent, rendered at the first share-tail
    moment of the design verb.

    Renders the prose so a stakeholder can read what's about to be tested
    without sharing the brief (which may still be drafting). Carries no
    metrics, no analysis, no decision rules — just intent.
    """

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1

    intent_text: str
    captured_at: str  # ISO-8601 UTC
    captured_by: str
    experiment_id: str


class DesignBriefVM(BaseModel):
    """The sealed brief, rendered after the brief seals (design verb's
    terminal share-tail moment).

    Carries: hypothesis prose, primary metric + decision rule, guardrails,
    cohort definitions, MDE + power, the integrity-lock hashes. Crucially
    *does not* carry any analysis output — by R11 the brief seals before
    any analysis exists.
    """

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1

    experiment_id: str
    hypothesis_text: str
    primary_metric_name: str
    primary_decision_rule: str  # rendered string
    mde_text: str  # e.g. "+2.0% relative"
    power_text: str  # e.g. "80% at α=0.05, n_required=24,572"
    guardrails_summary: list[str]  # one line per guardrail
    cohorts_summary: list[str]
    assignment_unit: Literal["user_id", "session_id", "device_id", "account_id"]
    expected_arm_ratio_text: str  # e.g. "50/50 control / treatment"
    # Integrity-lock display (first 12 chars for receipt strip)
    design_chain_hash_short: str
    metric_snapshot_count: int  # how many metric YAMLs were hashed
    sealed_at: str


class MidRunVM(BaseModel):
    """A mid-run readout fires ONLY on monitor halt — never on routine
    progress. The halt reason is the closed signal the orchestrator passes
    up; the user reads it and either resolves (override / abort) or extends
    monitoring.

    PEEK-PREVENTION INVARIANT (R10): this VM structurally lacks any field
    that could reveal experiment outcomes. No lift, no CI, no p-value, no
    per-arm count breakdown beyond the SRM ratio test that triggered the
    halt. The signal is qualitative: "the experiment hit a halting
    condition" with the *kind* of halt named.

    The closure test in tests/render/test_spine_vms.py:
      test_mid_run_vm_has_no_peek_revealing_fields
    iterates a forbidden-name set and asserts each is absent from
    model_fields. Adding lift / CI / p-value / per-arm magnitude to this
    VM requires a visible schema edit AND will fail the closure test
    until the test's forbidden set is also amended.
    """

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1

    experiment_id: str
    halt_reason: Literal[
        "srm_yellow",          # χ² between WARNING and BLOCK
        "srm_red",             # χ² past BLOCK threshold
        "guardrail_breach",    # a guardrail's 90% CI crosses harm threshold
        "exposure_stale",      # accrual stalled past the freshness window
    ]
    halt_summary_text: str  # one-line human description, NO outcome numbers
    triggered_at: str       # ISO-8601 UTC
    elapsed_text: str       # e.g. "ran for 4 days; halt fired at day 4 14:32 UTC"
    suggested_resolutions: list[str]  # closed-set free text per halt_reason
    # SRM-specific field: ONLY the chi-squared statistic and threshold
    # (this is metadata about the assignment, not metric outcome).
    srm_chi2: Optional[float] = None
    srm_threshold: Optional[float] = None

    # Notably absent (closure-tested):
    #   lift, lift_absolute, lift_relative,
    #   ci_lower_95, ci_upper_95, ci_lower_90, ci_upper_90, p_value,
    #   n_arm_control, n_arm_treatment,
    #   mean_arm_control, mean_arm_treatment,
    #   primary_metric_value, treatment_lift


# VerdictVM is effectively a re-export of ReportVM at the spine moment
# "verdict committed" — same shape, different framing. The renderer for
# the verdict readout fires distill() on the report.json (which produces
# the ReportVM) and wraps it as a verdict-stage share-tail.
VerdictVM = ReportVM


# Closure-test fixture exported for tests/render/test_spine_vms.py (T40).
_MID_RUN_FORBIDDEN_FIELDS: frozenset[str] = frozenset({
    "lift", "lift_absolute", "lift_relative",
    "ci_lower_95", "ci_upper_95", "ci_lower_90", "ci_upper_90",
    "p_value",
    "n_arm_control", "n_arm_treatment",
    "mean_arm_control", "mean_arm_treatment",
    "primary_metric_value", "treatment_lift",
    "primary_lift_magnitude",
    "effect_size", "cohens_d", "cohens_h",
    "relative_lift", "absolute_lift",
})
"""Field names that MUST NOT appear in MidRunVM.model_fields.

The closure test asserts: ``forbidden & set(MidRunVM.model_fields) == set()``.
This is the R10 peek-prevention discipline made executable.
"""
