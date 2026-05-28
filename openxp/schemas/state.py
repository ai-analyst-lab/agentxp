"""Canonical schemas for OpenXP v0.1 state.yaml.

Single source-of-truth for every enum, Literal, and pydantic model referenced
in state.yaml v3. Closure-tested by tests/coherence/test_canonical_names.py.

Source spec: experimentation-platform/OPENXP_V01_PLAN.md
  - §1.8.1   PendingDecisionKind  (14 values, snake_case)
  - §1.8.2   GateKind              (documented superset of PendingDecisionKind)
  - §1.8.4   Stage                 (11 main + 1 substate = 12 values)
  - §1.8.6   schema_version        (state.yaml -> 3)
  - §1.8.7   Closed Literals       (Stage3bChoice = Literal["r","e","o"])
  - §1.8.14  Cohort                (timezone IANA, defaults "UTC")
  - §1.8.15  SrmOverrideReasonCode (LOCKED v2 values; NoShipReasonCode lives in
             openxp.schemas.readout per the spec — not redefined here)
  - §6       state.yaml v3 layout
  - §6.4     Why 14 PendingDecisionKind values (CONFIRM_HYPOTHESIS reserved
             but not emitted in v0.1)
  - §10.8.2  Stage 3b r/e/o flow
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ──────────────────────────────────────────────────────────────────────────
# PendingDecisionKind — 14 values, locked per W_pre0.2 / §6.4.
# All snake_case. CONFIRM_HYPOTHESIS is reserved-not-emitted in v0.1.
# ──────────────────────────────────────────────────────────────────────────


class PendingDecisionKind(str, Enum):
    """The 14 gate kinds that may set ``state.yaml.pending_decision.kind``.

    ``CONFIRM_HYPOTHESIS`` is reserved in v0.1: the enum value exists for
    forward compatibility but the orchestrator MUST NOT emit it.
    """

    # ── Stage-confirmation gates (9) — one per user-visible stage commit ──
    CONFIRM_SEMANTIC_MODEL = "confirm_semantic_model"   # Stage 0.5 → 0.75
    CONFIRM_METRIC = "confirm_metric"                   # Stage 0.75 → 1
    CONFIRM_HYPOTHESIS = "confirm_hypothesis"           # Stage 2 → 3 — RESERVED v0.1
    CONFIRM_BRIEF = "confirm_brief"                     # Stage 3 → 4
    CONFIRM_DATA_PLAN = "confirm_data_plan"             # Stage 4 (top-level)
    CONFIRM_COHORT = "confirm_cohort"                   # Stage 4 (cohort sub-gate)
    CONFIRM_ASSIGNMENT = "confirm_assignment"           # Stage 4 (assignment sub-gate)
    CONFIRM_QUERY = "confirm_query"                     # Stage 5 + Stage 6
    CONFIRM_READOUT = "confirm_readout"                 # Stage 8

    # ── Failure-resolution gates (3) ────────────────────────────────────
    BRIEF_CONTRADICTION = "brief_contradiction"         # Stage 3b — r/e/o flow
    SRM_OVERRIDE = "srm_override"                       # Stage 5 — χ² yellow halt
    CROSS_ADAPTER_RESOLUTION = "cross_adapter_resolution"  # any SQL stage

    # ── Data-quality gates (2) ──────────────────────────────────────────
    MIXED_TIMESTAMP_FORMATS = "mixed_timestamp_formats"        # F.PRACTICE.02
    REFERENCED_ARTIFACT_CHANGED = "referenced_artifact_changed"  # F.PRACTICE.01


V01_RESERVED_PENDING_DECISION_KINDS: frozenset[PendingDecisionKind] = frozenset(
    {PendingDecisionKind.CONFIRM_HYPOTHESIS}
)
"""PendingDecisionKind values present in the enum but NOT emitted in v0.1.

See §6.4. Closure tests assert: (a) the value exists, (b) no v0.1 code path sets
``pending_decision.kind`` to a value in this set.
"""


# ──────────────────────────────────────────────────────────────────────────
# GateKind — documented superset of PendingDecisionKind.
#
# Flat Literal of all 16 string values so closure-test introspection via
# ``__args__`` works uniformly. Equivalent to:
#     Union[PendingDecisionKind, Literal["sql_review", "edit_override"]]
# but the flat form is what the closure test expects.
# ──────────────────────────────────────────────────────────────────────────


GateKindExtra = Literal["sql_review", "edit_override"]
"""The two non-pending UX gates that fire within a single user turn (§1.8.2)."""


GateKind = Literal[
    # 14 PendingDecisionKind values (mirrored as string literals so the
    # closure test's ``__args__`` walker sees them flat)
    "confirm_semantic_model",
    "confirm_metric",
    "confirm_hypothesis",
    "confirm_brief",
    "confirm_data_plan",
    "confirm_cohort",
    "confirm_assignment",
    "confirm_query",
    "confirm_readout",
    "brief_contradiction",
    "srm_override",
    "cross_adapter_resolution",
    "mixed_timestamp_formats",
    "referenced_artifact_changed",
    # 2 non-pending UX gates
    "sql_review",
    "edit_override",
]
"""All 16 valid values for ``GateOpenedPayload.kind`` (§1.8.2, §9).

Closure invariant: every ``PendingDecisionKind`` value is also a valid
``GateKind`` value; ``"sql_review"`` and ``"edit_override"`` are valid here but
invalid as ``PendingDecisionKind``.
"""


# ──────────────────────────────────────────────────────────────────────────
# Stage — 12 values (11 main + 1 substate).
# ──────────────────────────────────────────────────────────────────────────


class Stage(str, Enum):
    """The 11-stage user journey + the Stage 3b substate (§1.8.4)."""

    DATA_LOADED = "data_loaded"                          # Stage 0
    SEMANTIC_MODELS_DRAFTED = "semantic_models_drafted"  # Stage 0.5
    METRICS_BOOTSTRAPPED = "metrics_bootstrapped"        # Stage 0.75
    INTENT_CAPTURED = "intent_captured"                  # Stage 1
    HYPOTHESIS_DRAFTED = "hypothesis_drafted"            # Stage 2
    BRIEF_DRAFTED = "brief_drafted"                      # Stage 3
    BRIEF_CONTRADICTED = "brief_contradicted"            # Stage 3b substate
    DATA_PLAN_CONFIRMED = "data_plan_confirmed"          # Stage 4
    MONITOR = "monitor"                                  # Stage 5
    ANALYZE = "analyze"                                  # Stage 6
    INTERPRET = "interpret"                              # Stage 7
    READOUT = "readout"                                  # Stage 8


# Lowercase aliases so attribute access matches the canonical snake_case
# strings used by the closure test (which checks e.g. ``Stage.data_loaded`` and
# ``PendingDecisionKind.confirm_hypothesis``, not the SCREAMING_SNAKE name).
for _member in list(Stage):
    setattr(Stage, _member.value, _member)
for _member in list(PendingDecisionKind):
    setattr(PendingDecisionKind, _member.value, _member)
del _member


# ──────────────────────────────────────────────────────────────────────────
# Closed Literals (§1.8.7).
# ──────────────────────────────────────────────────────────────────────────


Stage3bChoice = Literal["r", "e", "o"]
"""User choice at Stage 3b brief-contradiction gate (M103 / §10.8.2).

- ``r`` — revert (drop the contradicting edit)
- ``e`` — edit (re-open the brief drafter)
- ``o`` — override (proceed with rationale)
"""


class SrmOverrideReasonCode(str, Enum):
    """Why the user overrode an SRM yellow halt (§1.8.15 LOCKED v2).

    Per the spec, this enum's canonical home is ``openxp.schemas.gate`` — but
    that module does not exist yet at W_pre1.1 build time. Re-exported here so
    the closure test for §1.8.15 (which currently parametrizes against
    ``openxp.schemas.gate``) can be retargeted to ``openxp.schemas.state`` if
    needed for the W_pre1 unblock. ``openxp.schemas.gate`` should re-export from
    here when it lands.
    """

    KNOWN_IMBALANCE = "known_imbalance"                  # external cause acknowledged
    MANUAL_CONTINUATION = "manual_continuation"          # proceed without resolving
    INVESTIGATION_COMPLETE = "investigation_complete"    # investigated; safe to continue


# ──────────────────────────────────────────────────────────────────────────
# UTC validator — shared across every datetime field in this module.
# ──────────────────────────────────────────────────────────────────────────


def _enforce_utc(v: datetime) -> datetime:
    """Reject naive datetimes and non-UTC tzinfo (§1.7.2 time-zone policy).

    Accepts any tzinfo whose UTC offset is zero — this includes ``timezone.utc``,
    ``ZoneInfo("UTC")``, and ``ZoneInfo("Etc/UTC")``. Cohort timezones are
    represented separately as IANA strings in ``Cohort.timezone``; all wall-clock
    timestamps in state.yaml MUST be UTC-encoded (ISO 8601 with ``Z`` suffix).
    """
    if v.tzinfo is None:
        raise ValueError("datetime must be timezone-aware; got a naive datetime")
    offset = v.tzinfo.utcoffset(v)
    if offset is None or offset.total_seconds() != 0:
        raise ValueError(
            f"datetime must be UTC (offset 0); got tzinfo={v.tzinfo!r} "
            f"with offset={offset}"
        )
    return v


# ──────────────────────────────────────────────────────────────────────────
# Pending decision — set on state.yaml when an experiment is paused.
# ──────────────────────────────────────────────────────────────────────────


class PendingDecision(BaseModel):
    """The single in-flight gate, persisted on ``state.yaml.pending_decision``."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    kind: PendingDecisionKind
    opened_at: datetime
    prompt_to_user: str
    options: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("opened_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return _enforce_utc(v)

    @field_validator("kind")
    @classmethod
    def _refuse_reserved(cls, v: PendingDecisionKind) -> PendingDecisionKind:
        if v in V01_RESERVED_PENDING_DECISION_KINDS:
            raise ValueError(
                f"PendingDecisionKind.{v.name} ({v.value!r}) is reserved in v0.1 "
                "and MUST NOT be emitted. See OPENXP_V01_PLAN.md §6.4."
            )
        return v


# ──────────────────────────────────────────────────────────────────────────
# Lock metadata — B4 stale-lock detection.
# ──────────────────────────────────────────────────────────────────────────


class LockMetadata(BaseModel):
    """Contents of ``experiments/{exp_id}/.state.lock`` (and ``.project.lock``).

    ``os.kill(pid, 0)`` against ``pid`` detects whether the holding process is
    still alive; if not, the lock is stale-reclaimed and an audit event with
    ``metadata.subtype="lock.stale_reclaimed"`` is emitted (§6, §10.5).
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    pid: int
    started_at: datetime
    hostname: Optional[str] = None  # for cross-machine debugging

    @field_validator("started_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return _enforce_utc(v)


# ──────────────────────────────────────────────────────────────────────────
# state.yaml v3 sub-models (§6).
# ──────────────────────────────────────────────────────────────────────────


class StageHistoryEntry(BaseModel):
    """One row of ``state.yaml.stage_history`` (§6)."""

    model_config = ConfigDict(extra="forbid")

    stage: Stage
    committed_at: datetime

    @field_validator("committed_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return _enforce_utc(v)


class SessionMetadata(BaseModel):
    """``state.yaml.session`` — last-action provenance for resume (§6, §10.6)."""

    model_config = ConfigDict(extra="forbid")

    started_at: datetime
    last_action_id: Optional[str] = None  # ULID of last orchestrator action
    last_hook_emitted: Optional[str] = None  # canonical event name (e.g. "stage.committed")
    last_hook_metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("started_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return _enforce_utc(v)


class Hypothesis(BaseModel):
    """``state.yaml.hypothesis`` — Stage 2 commit artifact, mirrored into state."""

    model_config = ConfigDict(extra="forbid")

    primary_metric: str
    predicted_direction: Literal["higher_is_better", "lower_is_better"]
    predicted_magnitude_pct: float
    guardrails: list[str] = Field(default_factory=list)
    segments_to_examine: list[str] = Field(default_factory=list)


class Cohort(BaseModel):
    """Time-anchored cohort window (§1.7.2, §1.8.14).

    ``timezone`` is an IANA name (e.g. ``"America/Los_Angeles"``, ``"UTC"``).
    ``start`` and ``end`` are UTC-encoded (Z suffix); ``timezone`` records the
    intended interpretation for the user-facing window edges.
    """

    model_config = ConfigDict(extra="forbid")

    timezone: str = "UTC"
    start: datetime
    end: Optional[datetime] = None

    @field_validator("timezone")
    @classmethod
    def _validate_iana(cls, v: str) -> str:
        try:
            from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        except ImportError as e:  # pragma: no cover
            raise ValueError(f"zoneinfo unavailable: {e}")
        try:
            ZoneInfo(v)
        except ZoneInfoNotFoundError as e:
            raise ValueError(f"timezone must be a valid IANA name: {v!r} ({e})")
        except Exception as e:
            raise ValueError(f"timezone must be a valid IANA name: {v!r} ({e})")
        return v

    @field_validator("start", "end")
    @classmethod
    def _utc(cls, v: Optional[datetime]) -> Optional[datetime]:
        return None if v is None else _enforce_utc(v)


class Segment(BaseModel):
    """One pre-registered analysis segment (§6)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    levels: list[Union[str, int, bool]] = Field(default_factory=list)


class SegmentRegistry(BaseModel):
    """``state.yaml.segments`` — pre-registered segments only (no post-hoc) (§6)."""

    model_config = ConfigDict(extra="forbid")

    pre_registered: list[Segment] = Field(default_factory=list)


class Multiplicity(BaseModel):
    """Holm-Bonferroni family-wise alpha correction (§1.8.14, §6).

    ``k_secondary`` was dropped per M60 (was always 0). ``cohorts`` block on
    multiplicity also dropped per M60.
    """

    model_config = ConfigDict(extra="forbid")

    method: Literal["holm_bonferroni"] = "holm_bonferroni"
    alpha_family: float = 0.05
    k_prereg: int = 0


class ArtifactRef(BaseModel):
    """One sha256-pinned artifact reference (§6, ``completed_stages.*.artifacts``)."""

    model_config = ConfigDict(extra="forbid")

    path: str
    sha256: str


class CompletedStage(BaseModel):
    """``state.yaml.completed_stages[stage]`` — bundles + artifacts at commit."""

    model_config = ConfigDict(extra="forbid")

    bundles: list[ArtifactRef] = Field(default_factory=list)
    artifacts: list[ArtifactRef] = Field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────
# state.yaml v3 root.
# ──────────────────────────────────────────────────────────────────────────


class StateYaml(BaseModel):
    """``experiments/{exp_id}/state.yaml`` — orchestrator-owned state (§6).

    schema_version is locked at ``3`` for v0.1 (§1.8.6). Loading a file with a
    ``schema_version`` higher than ``3`` MUST raise — see §6.5 for the
    forward-compat policy.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[3] = 3
    experiment_id: str

    session: Optional[SessionMetadata] = None

    current_stage: Stage
    last_committed_stage: Optional[Stage] = None
    stage_history: list[StageHistoryEntry] = Field(default_factory=list)

    # ── Stage-2 / Stage-3 content mirrored into state for fast read paths ──
    intent: Optional[str] = None
    hypothesis: Optional[Hypothesis] = None

    # ── References to project-level + per-experiment artifacts ──
    data_plan_ref: Optional[str] = None
    semantic_models_refs: list[str] = Field(default_factory=list)
    metrics_refs: list[str] = Field(default_factory=list)
    fact_sources_refs: list[str] = Field(default_factory=list)
    assignments_refs: list[str] = Field(default_factory=list)

    # ── Design ──
    cohorts: Optional[Cohort] = None
    segments: Optional[SegmentRegistry] = None
    multiplicity: Optional[Multiplicity] = None

    # ── Gating + locking ──
    pending_decision: Optional[PendingDecision] = None
    lock: Optional[LockMetadata] = None

    # ── Bundle + artifact pins per committed stage ──
    completed_stages: dict[str, CompletedStage] = Field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────
# Public API.
# ──────────────────────────────────────────────────────────────────────────


__all__ = [
    # enums
    "PendingDecisionKind",
    "Stage",
    "SrmOverrideReasonCode",
    # literal aliases
    "GateKind",
    "GateKindExtra",
    "Stage3bChoice",
    # constants
    "V01_RESERVED_PENDING_DECISION_KINDS",
    # models
    "PendingDecision",
    "LockMetadata",
    "StageHistoryEntry",
    "SessionMetadata",
    "Hypothesis",
    "Cohort",
    "Segment",
    "SegmentRegistry",
    "Multiplicity",
    "ArtifactRef",
    "CompletedStage",
    "StateYaml",
]
