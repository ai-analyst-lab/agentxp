"""Canonical schemas for report.md / report.json sidecar (Stage 8 readout output).

Models the JSON sidecar that the readout agent writes. Markdown renders from this JSON.

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §22, §23, §24, §10.7, §10.8.1,
§1.8.7, §1.8.10, §1.8.15, §1.8.17.

W_pre1.6 ships this module. The downstream consumers are:
  - readout agent (writes report.json + report.md from this schema)
  - validate_chain (returns ChainValidation defined here)
  - interpret/confidence.py (consumes ConfidenceLabel)

Verdict is owned by interpret/tree.py and re-exported here for the Report schema.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ──────────────────────────────────────────────────────────────────────────
# Verdict labels — 8 values per §1.8.17.
# Canonical home is agentxp/interpret/tree.py::Verdict (a Literal). Imported
# here so the report schema validates against the single source of truth rather
# than a divergent local copy. tree.py imports nothing from agentxp → no cycle.
# ──────────────────────────────────────────────────────────────────────────

from agentxp.interpret.tree import Verdict


# ──────────────────────────────────────────────────────────────────────────
# Confidence label — 7 values per §1.8.10 (D15 rename — was 5, expanded to 7)
# ──────────────────────────────────────────────────────────────────────────

class ConfidenceLabel(str, Enum):
    """Confidence framing for readout / interpreter (§1.8.10). Closed at 7 values."""
    HIGHLY_LIKELY_POSITIVE = "highly likely positive"
    VERY_LIKELY_POSITIVE = "very likely positive"
    LEANING_POSITIVE = "leaning positive"
    INCONCLUSIVE = "inconclusive"
    LEANING_NEGATIVE = "leaning negative"
    VERY_LIKELY_NEGATIVE = "very likely negative"
    HIGHLY_LIKELY_NEGATIVE = "highly likely negative"


# ──────────────────────────────────────────────────────────────────────────
# NoShipReasonCode — Stage 8 readout sign-off (per §1.8.15)
# ──────────────────────────────────────────────────────────────────────────
#
# Note: §1.8.15 originally homed this enum at `agentxp.schemas.readout`, but in
# the W_pre1 build the readout module collapses into `report.py` (the report
# IS the readout output). Kept here as a re-export point to preserve the
# `from agentxp.schemas.report import NoShipReasonCode` contract used by
# OverrideJustification below.

class NoShipReasonCode(str, Enum):
    """User's chosen NO-SHIP framing at Stage 8 sign-off (§1.8.15)."""
    GUARDRAIL_VIOLATION = "guardrail_violation"
    DIRECTIONAL_ONLY = "directional_only"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CONTRADICTORY_SEGMENTS = "contradictory_segments"


# ──────────────────────────────────────────────────────────────────────────
# Audit references — every claim in the readout points at one of these
# ──────────────────────────────────────────────────────────────────────────

class ConversationRef(BaseModel):
    """Pointer to a specific turn in conversation.jsonl.

    Used by validate_chain Invariant 2 (§10.7.2) to verify the bundle's
    `through_turn_id` resolves to a real turn.
    """
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    file: str = "conversation.jsonl"
    through_turn_id: str  # ULID
    turn_index: Optional[int] = None  # 0-indexed position in conversation.jsonl


class AuditPaths(BaseModel):
    """Audit-trail pointers backing a claim in the readout.

    A readout sentence cites one or more of these to ground itself in
    persisted state (per §22 / §24).
    """
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    state_yaml_pointer: Optional[str] = None  # e.g., "state.yaml#current_stage"
    conversation_refs: list[ConversationRef] = Field(default_factory=list)
    analysis_pointer: Optional[str] = None  # e.g., "analyses/2026-05-27T15:42.json#primary_metric.lift"
    queries: list[str] = Field(default_factory=list)  # query_id ULIDs
    bundles: list[str] = Field(default_factory=list)  # bundle path or hash


class UncertaintyNote(BaseModel):
    """One entry in "What I'm not sure about" section of the readout (§22)."""
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    topic: str
    detail: str
    audit_link: Optional[str] = None  # e.g., "queries/{ulid}.yaml" or "no audit link available"


# ──────────────────────────────────────────────────────────────────────────
# Override justification (per F.UX.11 / NDS-3-adjacent)
# ──────────────────────────────────────────────────────────────────────────

class OverrideJustification(BaseModel):
    """User-supplied reason for an override (NO-SHIP sign-off in Stage 8;
    free-text rationale for the Stage 3b override path).

    `reason_code` is a NoShipReasonCode for Stage 8 sign-off; a free-text str
    is permitted for the Stage 3b override path (where the rationale is the
    primary signal and the code may not map to the closed NO-SHIP set).
    """
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    reason_code: Union[NoShipReasonCode, str]
    rationale: str  # free-text, required
    authored_by: str  # user identifier
    authored_at: datetime

    @field_validator("authored_at")
    @classmethod
    def _enforce_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) != timezone.utc.utcoffset(v):
            raise ValueError("authored_at must be timezone-aware UTC")
        return v


# ──────────────────────────────────────────────────────────────────────────
# ChainValidation — per §10.7.1 (validate_chain output shape)
# ──────────────────────────────────────────────────────────────────────────

class Violation(BaseModel):
    """One entry in ChainValidation.violations when an invariant breaks (§10.7.2)."""
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    invariant_id: Literal[1, 2, 3, 4, 5]
    description: str  # one-line human summary (templates in §10.7.2)
    offending_action_id: Optional[str] = None  # ULID into log.jsonl when applicable
    offending_path: Optional[str] = None  # bundle / query / decision path when applicable


class ChainValidation(BaseModel):
    """Result of validate_chain (§10.7.1).

    `ms` is total wall-time runtime; `perf_warning` is True when ms exceeds
    the soft cap (default 200ms per §10.7.3). The hard cap (2x soft = 400ms)
    raises PerfBudgetExceeded from the caller, not surfaced here.
    """
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    ok: bool
    invariants_checked: list[Literal[1, 2, 3, 4, 5]] = Field(default_factory=list)
    violations: list[Violation] = Field(default_factory=list)
    ms: float  # actual runtime for perf-budget tracking
    perf_warning: bool = False  # True when ms > soft cap (§10.7.3)


# ──────────────────────────────────────────────────────────────────────────
# Metric / Guardrail / Segment result rows (for report.json body)
# ──────────────────────────────────────────────────────────────────────────

class MetricResult(BaseModel):
    """One metric's result row in the readout (§22, §24)."""
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    name: str
    type: Literal["primary", "guardrail", "negative_control"]
    lift_absolute: float
    lift_relative: float
    ci_95_lower: float
    ci_95_upper: float
    ci_90_lower: float
    ci_90_upper: float
    p_value: float
    confidence_label: ConfidenceLabel
    audit_paths: AuditPaths


class SegmentResult(BaseModel):
    """Per-segment result with Holm-Bonferroni adjustment (§22, §24)."""
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    segment_name: str
    rationale: str
    primary: MetricResult
    holm_bonferroni_adjusted_alpha: float
    audit_paths: AuditPaths


class EdgeCaseFlag(BaseModel):
    """One row in the readout's edge-case-flags table (§22)."""
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    name: Literal[
        "underpowered",
        "srm_violation",
        "mixed_results",
        "guardrail_violation",
        "novelty_effect",
        "simpsons_paradox",  # row preserved in v0.1; status=clear, detail="not checked in v0.1"
    ]
    status: Literal["clear", "flagged", "blocking"]
    detail: str


class DiagnosticGate(BaseModel):
    """SRM + power diagnostics gating the 8-step decision tree (§22)."""
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    srm_passed: bool
    power_sufficient: bool
    audit_paths: AuditPaths


# ──────────────────────────────────────────────────────────────────────────
# Report — the report.json root (§24)
# ──────────────────────────────────────────────────────────────────────────

class Report(BaseModel):
    """report.json sidecar — what the readout agent writes at Stage 8 (§24).

    The .md file is a deterministic render of this JSON. Every claim in the
    markdown traces to an `AuditPaths` block here.
    """
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    experiment_id: str
    generated_at: datetime
    verdict: Verdict
    verdict_rationale: str  # one-sentence
    step_fired: Literal[1, 2, 3, 4, 5, 6, 7, 8]  # 8-step decision tree (§22)
    decision_rule_id: str  # e.g., "default.ship" or user-defined
    decision_rule_source: Literal["agentxp_default", "user_defined"]

    diagnostics: DiagnosticGate
    primary: MetricResult
    guardrails: list[MetricResult] = Field(default_factory=list)
    negative_controls: list[MetricResult] = Field(default_factory=list)
    segments: list[SegmentResult] = Field(default_factory=list)
    edge_case_flags: list[EdgeCaseFlag] = Field(default_factory=list)

    uncertainty_notes: list[UncertaintyNote] = Field(default_factory=list)
    override_justification: Optional[OverrideJustification] = None
    audit_paths: AuditPaths

    # Compressed history reference (per §10.8.1)
    prior_turns_compressed_ref: Optional[str] = None  # e.g., "bundles/readout.ctx.yaml#prior_turns_compressed"

    @field_validator("generated_at")
    @classmethod
    def _enforce_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) != timezone.utc.utcoffset(v):
            raise ValueError("generated_at must be timezone-aware UTC")
        return v


__all__ = [
    "Verdict",
    "ConfidenceLabel",
    "NoShipReasonCode",
    "ConversationRef",
    "AuditPaths",
    "UncertaintyNote",
    "OverrideJustification",
    "Violation",
    "ChainValidation",
    "MetricResult",
    "SegmentResult",
    "EdgeCaseFlag",
    "DiagnosticGate",
    "Report",
]
