"""Bundle schemas for lean-agentic specialist dispatch (R10).

Every specialist sub-agent is dispatched with a Pydantic-validated bundle.
The bundle's contents are determined by the role's BundleSchema in this
module, not by orchestrator whim — the assembler (T60) refuses to add
fields outside the schema. This is the mechanism that makes the blindness
rules (R5, R6, R10 in CLAUDE.md) structurally enforceable rather than
aspirational.

Every bundle has ``model_config = ConfigDict(extra="forbid")``. Adding a
peek-revealing or context-leaking field requires a visible schema edit
here, which is the audit point.

Roster:
  - UnderstanderBundle    drafts semantic models + metrics; blind to intent
  - DesignerBundle        drafts brief/hypothesis/data plan; sees no analysis
  - CriticBundle          judges artifacts; blind to producer reasoning
  - SqlSpecialistBundle   writes SQL; bounded context (not adversarially blind)
  - AnalystNarratorBundle describes stats; blind to hypothesis direction

The "blind to" property for each bundle is asserted by the closure test in
``tests/orchestrator/test_bundle_assembler.py`` (T61), which constructs each
bundle from a source dict containing the forbidden field and asserts
ValidationError is raised.

PENDING (filled by later tasks):
  Several referenced types are minimal placeholders here, to be superseded
  by richer schemas in their proper modules. Each placeholder carries a
  ``TODO(T##)`` tag pointing at the superseding task.

    BriefDraft, HypothesisDraft, DataPlanDraft  → T04 (experiment.py)
    SealedBrief, ExpectedShape                   → T02 (brief_seal.py)
    Judgment, Objection                          → T72 (agents/critic.md)
    SqlProposal, FailedSqlAttempt                → T73 (agents/sql_specialist.md)
    MetricProposal, SemanticModelProposal        → T70 (agents/understander.md)

  The placeholders carry the *fields* needed for bundle validation. The
  superseding task moves them to their canonical module and may add fields
  the bundle does not need; bundle schemas import from the canonical
  module once it exists.
"""
from __future__ import annotations

from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from agentxp.metrics.schema import MetricDefinition
from agentxp.schemas._types import AwareUtcDatetime, Sha256Hex
from agentxp.sql.safety import Purpose as _SafetyPurpose


# ─────────────────────────────────────────────────────────────────────────────
# Shared small types — used across multiple bundles.
# ─────────────────────────────────────────────────────────────────────────────


class ArtifactRef(BaseModel):
    """A reference to a committed artifact on disk.

    The ``sha256`` field pins the version the bundle was assembled against;
    if the artifact changes between bundle assembly and a downstream replay,
    the hash mismatch is detectable.
    """

    model_config = ConfigDict(extra="forbid")

    path: str = Field(description="Path relative to experiments/<id>/")
    sha256: Sha256Hex
    kind: Literal[
        "brief", "data_plan", "analysis", "interpretation", "report",
        "query", "monitor_snapshot", "readout", "semantic_model", "metric",
    ]


class IntentText(BaseModel):
    """The user's plain-English statement of what they want to test."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=4000)
    captured_at: AwareUtcDatetime = Field(
        description=(
            "Timezone-aware UTC datetime. yaml.safe_load emits datetime "
            "directly, so callers no longer need to re-parse ISO strings "
            "(DIAGNOSTIC §B.2 #4)."
        )
    )


# ─────────────────────────────────────────────────────────────────────────────
# BundleBase — envelope for every specialist bundle (W1.5)
# ─────────────────────────────────────────────────────────────────────────────


class _PriorErrorEntry(BaseModel):
    """One prior validation failure surfaced to the specialist on retry.

    The orchestrator's ``complete_dispatch`` (W5.2) catches a
    ``ValidationError`` on the specialist's first output, packs the per-field
    error list into ``prior_error``, and re-dispatches the bundle so the
    specialist can repair the output in one retry (CLAUDE.md §10 failure
    category 2 — malformed specialist output). On second failure the
    orchestrator raises ``MalformedSpecialistOutput`` rather than looping.
    """

    model_config = ConfigDict(extra="forbid")

    loc: str = Field(description='Dotted field path, e.g. "primary_metric_candidate".')
    msg: str = Field(description="Validator message, verbatim from pydantic.")
    type: str = Field(description='Validator class, e.g. "string_too_short".')


class BundleBase(BaseModel):
    """Envelope shared by every specialist bundle.

    Adds ``prior_error`` as a metadata channel for retry-once-on-malformed
    (CLAUDE.md §10). The field is *envelope* metadata, not domain content —
    the recursive ``BLINDNESS_MANIFEST`` walker (W1.9) excludes the
    ``_ENVELOPE_FIELDS`` frozenset from its forbidden-field traversal so
    surfacing prior errors does not register as a blindness violation.

    Per-role bundles inherit from this and add their own fields. The
    bundle assembler (R10) keeps each subclass at ``extra="forbid"`` so the
    role's surface stays exactly what the schema declares.
    """

    model_config = ConfigDict(extra="forbid")

    prior_error: Optional[list[_PriorErrorEntry]] = Field(
        default=None,
        description=(
            "Per-field validation errors from the specialist's prior output. "
            "Populated by complete_dispatch on retry; None on first dispatch. "
            "Envelope-only — does not count toward R5/R6/R10 blindness."
        ),
    )


_ENVELOPE_FIELDS: frozenset[str] = frozenset({"prior_error"})
"""Field names that BundleBase contributes; excluded from BLINDNESS_MANIFEST.

Tests at ``tests/orchestrator/test_bundle_assembler.py`` and
``tests/schemas/test_blindness_closure.py`` consult this set when walking
bundle schemas for forbidden-field detection — envelope metadata is not
domain content and must not register as a blindness violation.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Placeholder types — superseded by later tasks (see module docstring).
# ─────────────────────────────────────────────────────────────────────────────


class BundleSemanticModel(BaseModel):
    """Semantic-model shape accepted by every specialist bundle.

    W1.7 partial close — replaces the pre-W1.7 ``_SemanticModelPlaceholder``
    stub (DIAGNOSTIC §B.2 #5). The stub had four strict fields and refused
    the eight-plus fields the on-disk ``semantic_models/*.yaml`` files
    carry, forcing the orchestrator to hand-flatten every entry before
    bundle assembly. This schema is permissive enough to admit the on-disk
    shape directly: ``yaml.safe_load(open(path))`` round-trips into the
    bundle without an adapter.

    **Why not import** ``agentxp.semantic.validators.SemanticModel`` per
    the original Round 1 plan: the canonical type at
    ``agentxp/semantic/validators.py:119`` declares a *different* on-disk
    contract (``entity``, ``fields[]``, ``fingerprint_sha256``) than the
    YAMLs the design verb consumes (``dimensions[]``, ``relationships[]``,
    ``outcome_columns[]``, ``primary_key`` as a list, etc.). Reconciling
    the two is an architectural decision that affects every existing
    experiment dir — deferred as **T70-RECONCILE**, documented in
    ``working/plans/SESSION_LOG.md`` for follow-up. For the bundle layer,
    a permissive schema that admits the on-disk shape closes the immediate
    R10 break without forcing that decision.
    """

    model_config = ConfigDict(extra="allow")

    name: str
    primary_key: list[str] | str = Field(
        description="Primary key column(s); list shape supported for compound keys.",
    )
    source_table: str
    outcome_columns: list[str] = Field(
        ...,  # W1.8 — required, no default. An entity must declare its outcomes
              # explicitly (empty list = "no outcomes") so the SQL safety
              # pipeline's Layer 3d (R11) cannot silently treat a missing field
              # as "no outcomes" when the YAML author simply forgot to add it.
        description=(
            "Names of outcome-bearing columns this entity carries. Layer 3d "
            "of the SQL safety pipeline (R11) consults this declaration when "
            "refusing design-mode queries that touch outcome surfaces. An "
            "empty list means the entity exposes no outcomes; ``None`` and "
            "a missing field are both rejected."
        ),
    )


class WarehouseProfile(BaseModel):
    """Output of the profiler tool, summarized for the understander.

    Cardinalities, null rates, type distributions, HG-D4 flags. Notably does
    not include any per-arm aggregation or outcome value — the profiler runs
    against raw warehouse shape, not against assignment outcomes.
    """

    model_config = ConfigDict(extra="forbid")

    tables: dict[str, dict[str, object]] = Field(
        description="Per-table column profile. Schema-level only; no outcome data."
    )
    flags: list[str] = Field(
        default_factory=list,
        description="HG-D4 heuristic flags (e.g. 'mixed_timestamp_in users.created_at').",
    )


class AssignmentSurface(BaseModel):
    """The available assignment surface for design-mode power calculations.

    Reports the *count* of available units in each cohort, the daily/weekly
    accrual rate, and the segmentation structure — never any outcome value
    or per-arm split. The design verb uses this to refuse to seal a brief
    whose required-n exceeds the surface (no --force).
    """

    model_config = ConfigDict(extra="forbid")

    units_available: int
    accrual_per_day: float
    segments: list[str] = Field(default_factory=list)
    assignment_unit: Literal["user_id", "session_id", "device_id", "account_id"]


class _BriefDraftPlaceholder(BaseModel):
    """Draft form of a brief, before sealing.

    TODO(T04): replace with the canonical BriefDraft schema in
    ``agentxp.schemas.experiment`` once that module is tweaked.
    """

    model_config = ConfigDict(extra="forbid")

    hypothesis: str
    primary_metric: str
    decision_rules: list[str]
    mde: float
    cohorts: list[str]


class DataPlanDraft(BaseModel):
    """Prose data plan produced by the designer (W1.6).

    Sibling artifact to ``BriefDraft`` — not a sub-field, per debate-summary
    §3 (the data plan is judged independently by the critic in
    ``brief_consistency`` mode, so it needs its own commit-worthy artifact).
    The warehouse-binding ``DataPlanV2`` in ``agentxp.schemas.data_plan`` is
    generated at *analyze* entry (see Skill Author round 2 §C), not at
    brief seal, so the two have separate lifecycles:

    * ``DataPlanDraft`` lives in the design verb. The designer drafts it,
      the critic judges it, the orchestrator commits it before brief seal.
    * ``DataPlanV2`` is the warehouse fingerprint + assignment binding
      produced at analyze open. The two are linked by the experiment id,
      not by inheritance.
    """

    model_config = ConfigDict(extra="forbid")

    source_summary: str = Field(
        min_length=1,
        description=(
            "Plain-English summary of the warehouse the brief assumes — e.g. "
            "'agentxp_demo.duckdb, registered_as=agentxp_demo, accrual "
            "≈9k users/day over a 15-day window'."
        ),
    )
    assignment_table: str = Field(
        min_length=1,
        description="Logical name of the assignment table (e.g. 'assignments').",
    )
    fact_sources: list[str] = Field(
        default_factory=list,
        description=(
            "Logical names of the fact tables the brief's primary metric and "
            "guardrails read from (e.g. ['orders', 'page_events']). The "
            "critic checks these against the brief's metric snapshot."
        ),
    )
    notes: str = Field(
        default="",
        description=(
            "Optional caveats: data quality notes, late-arriving rows, "
            "timestamp conventions, etc. Free-form prose; the critic "
            "judges for consistency, not completeness."
        ),
    )


class _SealedBriefPlaceholder(BaseModel):
    """Sealed brief carrying the three-part integrity lock.

    TODO(T02): replace with ``agentxp.schemas.brief_seal.SealedBrief`` once
    that module exists. The three-part lock is the gate that the analyze
    verb verifies before opening.
    """

    model_config = ConfigDict(extra="forbid")

    draft: _BriefDraftPlaceholder
    design_chain_hash: Sha256Hex
    metric_snapshot: dict[str, Sha256Hex]
    expected_shape: dict[str, object]
    sealed_at: str


class DecisionRule(BaseModel):
    """A pre-registered decision rule from the sealed brief.

    Used by the analyst-narrator. The narrator sees decision rules so it can
    cite them; it does *not* see the hypothesis prose (which would bias the
    narrative direction).
    """

    model_config = ConfigDict(extra="forbid")

    metric_name: str
    threshold: float
    direction: Literal["above", "below"]
    severity: Literal["primary", "guardrail", "secondary"]


class MetricResult(BaseModel):
    """A computed metric result with its computation trace.

    TODO(T70/T74): align with the output of ``agentxp.stats.*`` functions.
    The narrator only reads these; it does not compute.
    """

    model_config = ConfigDict(extra="forbid")

    metric_name: str
    point_estimate: float
    ci_low: float
    ci_high: float
    p_value: Optional[float] = None
    test_used: str
    computation_trace: dict[str, object]


class SrmResult(BaseModel):
    """SRM check output."""

    model_config = ConfigDict(extra="forbid")

    verdict: Literal["PASS", "WARNING", "BLOCK"]
    chi2: float
    p_value: float
    observed_counts: dict[str, int]
    expected_ratios: dict[str, float]


class GuardrailResult(BaseModel):
    """Guardrail metric check output."""

    model_config = ConfigDict(extra="forbid")

    metric_name: str
    verdict: Literal["PASS", "WARNING", "BLOCK"]
    nim_relative: float
    observed_lift: float


class ConfidenceLabelEntry(BaseModel):
    """A computed confidence label for one metric."""

    model_config = ConfigDict(extra="forbid")

    metric_name: str
    label: Literal[
        "highly likely positive",
        "very likely positive",
        "leaning positive",
        "inconclusive",
        "leaning negative",
        "very likely negative",
        "highly likely negative",
    ]


# Critic-specific types.


class ClaimedScope(BaseModel):
    """What the artifact under critique claims to do.

    The critic uses this to know what to judge against. It does not see how
    the producer arrived at the artifact — only what the artifact says of
    itself.
    """

    model_config = ConfigDict(extra="forbid")

    claim: str
    cites: list[ArtifactRef] = Field(default_factory=list)


class _ObjectionPlaceholder(BaseModel):
    """A single critic objection.

    TODO(T72): align with the canonical Objection schema once the critic
    prompt is written.
    """

    model_config = ConfigDict(extra="forbid")

    file_path: str
    location: Optional[str] = None
    what: str
    why: str
    rule_violated: Optional[str] = None  # e.g. "R1", "R7"


class _JudgmentPlaceholder(BaseModel):
    """Critic's verdict on the artifact.

    TODO(T72): align with canonical Judgment schema.
    """

    model_config = ConfigDict(extra="forbid")

    passed: bool
    reasons: list[_ObjectionPlaceholder] = Field(default_factory=list)
    severity: Literal["block", "warn"] = "block"


# SQL-specialist types.


class WarehouseSchema(BaseModel):
    """Read-only snapshot of the warehouse schema available to SQL writers.

    Contains table names, column names, types, foreign-key relationships —
    enough to write a join. Does not contain row counts (those are in
    WarehouseProfile, with HG-D4 flags); the SQL specialist does not need
    cardinalities to write a query.
    """

    model_config = ConfigDict(extra="forbid")

    tables: dict[str, dict[str, str]] = Field(
        description="Table name -> column name -> SQL type string."
    )
    foreign_keys: list[dict[str, str]] = Field(default_factory=list)


class SqlIntent(BaseModel):
    """Natural-language description of what the SQL should accomplish."""

    model_config = ConfigDict(extra="forbid")

    # W2.3 — single source of truth: agentxp.sql.safety.Purpose.
    # Pre-W2.3 this Literal declared its own values (srm_check, metric_compute,
    # guardrail_check, shape_probe, monitor_snapshot) that did NOT overlap
    # with the safety pipeline's _ROW_LIMIT_BY_PURPOSE keys (profile, preview,
    # srm_check, metric_compute, user_paste). probe_data() with
    # purpose="shape_probe" raised ResourceBoundsViolation
    # (DIAGNOSTIC §B.3 #7). Importing the canonical Literal closes the drift.
    purpose: _SafetyPurpose
    description: str


class _FailedSqlAttemptPlaceholder(BaseModel):
    """A prior SQL attempt that failed validation or execution.

    TODO(T73): align with canonical schema once the sql_specialist agent is
    written.
    """

    model_config = ConfigDict(extra="forbid")

    sql: str
    error: str
    layer: Literal[
        "sqlglot_parse", "read_only", "cross_adapter",
        "semantic_deny", "resource_bounds", "execution",
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Bundle schemas — the 5 specialist contracts.
# ─────────────────────────────────────────────────────────────────────────────


class UnderstanderBundle(BundleBase):
    """Bundle for the Understander specialist.

    The understander drafts semantic models and metrics from a dataset's
    natural structure. It must not know what experiment will use these —
    knowing the intent would bias toward metric-fishing (drafting metrics
    that flatter a specific hypothesis).

    R5 (producer blindness): this bundle structurally lacks any
    intent/hypothesis field. The schema is the wall.
    """

    model_config = ConfigDict(extra="forbid")

    warehouse_profile: WarehouseProfile
    existing_semantic_models: list[ArtifactRef] = Field(default_factory=list)
    existing_metrics: list[ArtifactRef] = Field(default_factory=list)
    task: Literal["draft_semantic_models", "draft_metrics"]

    # Closure-test asserts the following field names are NOT in
    # UnderstanderBundle.model_fields:
    #   "intent", "hypothesis", "brief", "experiment_intent", "experiment_id"


class DesignerBundle(BundleBase):
    """Bundle for the Designer specialist.

    The designer drafts hypotheses, briefs, and data plans during the
    ``design`` verb. It sees intent (because the user wrote it), semantic
    models, metrics, and the assignment surface — but no analysis output,
    because (R11) the design verb cannot reach outcome data architecturally.
    """

    model_config = ConfigDict(extra="forbid")

    intent: IntentText
    semantic_models: list[BundleSemanticModel]
    metrics: list[MetricDefinition]
    assignment_surface: AssignmentSurface
    prior_drafts: list[ArtifactRef] = Field(default_factory=list)
    task: Literal["draft_hypothesis", "draft_brief", "draft_data_plan"]

    # Closure-test asserts the following field names are NOT in
    # DesignerBundle.model_fields:
    #   "analysis", "metric_result", "srm_result", "guardrail_result",
    #   "interpretation", "verdict", "lift", "ci_low", "ci_high", "p_value"


class CriticBundle(BundleBase):
    """Bundle for the Critic specialist.

    The critic judges an artifact blind. It sees the artifact and what the
    artifact claims to test (ClaimedScope), and the artifacts the artifact
    explicitly cites (cited_inputs). It does NOT see the producer's
    reasoning, the conversation history, prior critic passes on the same
    artifact, or any artifact the artifact does not cite.

    The ``judging_mode`` discriminates what kind of judgment to render:
    brief_consistency, analysis_vs_brief, verdict_vs_analysis, or
    readout_faithfulness. One critic prompt, four firing-points.
    """

    model_config = ConfigDict(extra="forbid")

    artifact: ArtifactRef
    artifact_payload: dict[str, object] = Field(
        description="The deserialized content of the artifact under critique."
    )
    claimed_scope: ClaimedScope
    cited_inputs: list[ArtifactRef] = Field(default_factory=list)
    judging_mode: Literal[
        "brief_consistency",
        "analysis_vs_brief",
        "verdict_vs_analysis",
        "readout_faithfulness",
    ]

    # Closure-test asserts the following field names are NOT in
    # CriticBundle.model_fields:
    #   "producer_reasoning", "drafter_chain_of_thought", "conversation",
    #   "conversation_history", "prior_judgments", "user_intent_prose"


class SqlSpecialistBundle(BundleBase):
    """Bundle for the SQL Specialist.

    The SQL specialist writes and corrects queries. Bounded context (not
    adversarially blind): it sees the warehouse schema, the semantic models
    that name what tables mean, the verb (design or analyze, which controls
    what the safety pipeline allows), and the intent of the query. In
    correction mode it also sees the prior failed attempt.

    R11 enforcement: when ``verb == "design"`` the safety pipeline rejects
    any reference to outcome-bearing columns. The bundle does not enforce
    this directly — the safety pipeline (T20) does — but the bundle's verb
    field is what the pipeline consumes.
    """

    model_config = ConfigDict(extra="forbid")

    intent: SqlIntent
    warehouse_schema: WarehouseSchema
    semantic_models: list[BundleSemanticModel]
    verb: Literal["design", "analyze"]
    brief_ref: Optional[ArtifactRef] = Field(
        default=None,
        description="REQUIRED when verb='analyze'; pins which sealed brief authorizes this query.",
    )
    prior_attempt: Optional[_FailedSqlAttemptPlaceholder] = None


class AnalystNarratorBundle(BundleBase):
    """Bundle for the Analyst-Narrator.

    The narrator writes prose about statistical results that the orchestrator
    already computed via the stats whitelist. It quotes numbers with the
    precision they were computed at; it does not round or approximate. It
    cites every claim with an AuditPaths reference.

    R5/R8 blindness: the bundle structurally lacks the hypothesis prose, the
    designer's narrative, and the conversation history. The narrator
    describes what the numbers say, not what the experiment hoped they would
    say. Confidence labels are passed in pre-computed (the narrator never
    chooses a label).
    """

    model_config = ConfigDict(extra="forbid")

    metric_results: list[MetricResult]
    brief_decision_rules: list[DecisionRule]
    srm_result: SrmResult
    guardrail_results: list[GuardrailResult] = Field(default_factory=list)
    confidence_labels: list[ConfidenceLabelEntry] = Field(default_factory=list)

    # Closure-test asserts the following field names are NOT in
    # AnalystNarratorBundle.model_fields:
    #   "hypothesis", "hypothesis_prose", "intent", "designer_narrative",
    #   "conversation", "expected_direction", "hoped_outcome"


# ─────────────────────────────────────────────────────────────────────────────
# Bundle registry — maps role name to schema. Used by the bundle assembler.
# ─────────────────────────────────────────────────────────────────────────────


BUNDLE_SCHEMAS: dict[str, type[BaseModel]] = {
    "understander": UnderstanderBundle,
    "designer": DesignerBundle,
    "critic": CriticBundle,
    "sql_specialist": SqlSpecialistBundle,
    "analyst_narrator": AnalystNarratorBundle,
}
"""Specialist role name -> bundle schema.

The assembler (T60) looks up the schema by role name and constructs an
instance — Pydantic's ``extra="forbid"`` rejects any source field that is
not declared in the schema. Adding a new role requires registering it here.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Blindness manifest — declarative source of truth for the closure test.
# ─────────────────────────────────────────────────────────────────────────────


BLINDNESS_MANIFEST: dict[str, list[str]] = {
    "understander": [
        "intent", "hypothesis", "brief", "experiment_intent", "experiment_id",
    ],
    "designer": [
        "analysis", "metric_result", "srm_result", "guardrail_result",
        "interpretation", "verdict", "lift", "ci_low", "ci_high", "p_value",
    ],
    "critic": [
        "producer_reasoning", "drafter_chain_of_thought", "conversation",
        "conversation_history", "prior_judgments", "user_intent_prose",
    ],
    "sql_specialist": [
        # Not adversarially blind; bounded context only.
    ],
    "analyst_narrator": [
        "hypothesis", "hypothesis_prose", "intent", "designer_narrative",
        "conversation", "expected_direction", "hoped_outcome",
    ],
}
"""For each role, the set of field names that must NOT appear in the bundle.

The closure test in tests/orchestrator/test_bundle_assembler.py (T61)
iterates this manifest and asserts:

  for role, forbidden in BLINDNESS_MANIFEST.items():
      schema = BUNDLE_SCHEMAS[role]
      for field_name in forbidden:
          assert field_name not in schema.model_fields, (
              f"{role} bundle must not have field {field_name!r} — see "
              f"CLAUDE.md R5/R6/R10 and rebuild/SPECIALISTS.md"
          )

Changes to this manifest are an audit point: removing a forbidden field
either widens the bundle's permitted context (which requires justification
in the commit message) or the field is being intentionally renamed.
"""


__all__ = [
    # Bundles
    "UnderstanderBundle",
    "DesignerBundle",
    "CriticBundle",
    "SqlSpecialistBundle",
    "AnalystNarratorBundle",
    # Registry
    "BUNDLE_SCHEMAS",
    "BLINDNESS_MANIFEST",
    # Shared types
    "ArtifactRef",
    "IntentText",
    "WarehouseProfile",
    "AssignmentSurface",
    "WarehouseSchema",
    "SqlIntent",
    "ClaimedScope",
    "DecisionRule",
    "MetricResult",
    "SrmResult",
    "GuardrailResult",
    "ConfidenceLabelEntry",
]
