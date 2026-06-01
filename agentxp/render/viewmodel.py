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
