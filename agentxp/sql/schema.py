"""Canonical schemas for the AgentXP v0.1 SQL subsystem.

Single source-of-truth for every pydantic model and Literal referenced by the
5-layer SQL safety pipeline (§11), the 3 v0.1 warehouse adapters (§12), and the
per-query `queries/{ulid}.yaml` `QueryArtifact` (§13).

Source spec: experimentation-platform/OPENXP_V01_PLAN.md
  - §11      5-layer SQL safety pipeline + AST allowlist + DENY_FUNCTIONS
  - §12      The 3 v0.1 adapters: DuckDB, Snowflake, BigQuery
             (Postgres / MySQL / Redshift / Databricks deferred to v0.1.1 per D1)
  - §13      QueryArtifact spec — `experiments/{exp_id}/queries/{ulid}.yaml`
  - §1.7.1   PII flow map; `auth_kind` carries redaction context
  - §1.7.2   Time-zone policy — every datetime in this module is UTC-enforced
  - §1.7.3   Secrets policy — credentials live by *name reference*, never inline
  - §1.7.6   schema_version policy — `queries/{ulid}.yaml` is at v1
  - §1.8.6   Per-file schema_version constants
  - §1.8.7   Closed Literals — including `QueryArtifact.auth_kind` (7 values)
  - §1.8.14  Cohort and config field names
  - §10.5.5  Auth-expired recovery path
  - §10.6    `agentxp resume <exp_id>` orphan-query re-execution

Closure-tested by tests/coherence/test_canonical_names.py.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Re-export FactSourceBinding from the canonical location (data_plan.py) so the
# SQL subsystem can refer to it without circular layering. Per the §1.8.9
# canonical-module table, FactSourceBinding's home stays in data_plan; this is
# a flat re-export, not a redefinition.
from agentxp.schemas.data_plan import FactSourceBinding
from agentxp.schemas.state import _enforce_utc


# ──────────────────────────────────────────────────────────────────────────
# AdapterType — 3 values in v0.1 per D1 / H35 / Theme 7 cut (§12).
#
# Postgres / MySQL / Redshift / Databricks land in v0.1.1 (~2 weeks post-v0.1
# ship per `scope_decisions_round2.adapters` in BUILD_STATUS.yaml). The closed
# Literal here is the contract that prevents `agentxp connect <other>` from
# resolving in v0.1 — the wizard refuses with a named error.
# ──────────────────────────────────────────────────────────────────────────


AdapterType = Literal["duckdb", "snowflake", "bigquery"]
"""The 3 warehouse adapters shipping in v0.1 (§12).

Closure invariant: ``len(AdapterType.__args__) == 3``. Tested in
``tests/coherence/test_canonical_names.py``.
"""


# ──────────────────────────────────────────────────────────────────────────
# AuthKind — 7-value closed Literal per §1.8.7 (B9 redaction context).
#
# Every QueryArtifact carries this so the `log.jsonl` redactor and bundle
# scrubber know which credential surface was in play (different adapters
# use different secrets; the kind tells the redactor what to look for).
# ──────────────────────────────────────────────────────────────────────────


AuthKind = Literal[
    "pwd",              # username + password (Snowflake password auth)
    "externalbrowser",  # Snowflake SSO via browser callback
    "oauth",            # OAuth bearer token (Snowflake / Databricks)
    "keypair",          # Snowflake key-pair JWT
    "adc",              # BigQuery Application Default Credentials
    "sa",               # BigQuery service-account JSON
    "none",             # DuckDB file path / in-memory — no credential surface
]
"""Auth method used to dispatch the query (§1.7.3 + §1.8.7).

Carried on every ``QueryArtifact`` so the audit redactor knows which secret
patterns to scrub from error messages and result-summary blocks. ``"none"``
covers DuckDB local-file / in-memory connections where no credential exists.
"""


# ──────────────────────────────────────────────────────────────────────────
# PurposeKey — 5 values per §1.8.7 / §11 resource-bounds matrix.
#
# Each call-site declares a purpose, and the §11 layer-4 resource enforcer
# picks the matching `ResourceBounds` row. Closure-tested: must be exactly 5.
# ──────────────────────────────────────────────────────────────────────────


PurposeKey = Literal[
    "profile",         # Stage 0 DuckDB SUMMARIZE-style profiling (smallest budget)
    "preview",         # Stage 0.5 / 0.75 / 4 sample-row preview for the user-review screen
    "srm_check",       # Stage 5 monitor χ² sample-ratio-mismatch query
    "metric_compute",  # Stage 6 analyzer primary + guardrail + segment compute
    "user_paste",      # User-pasted SQL into the editor — tightest deny-list, smallest budget
]
"""The 5 SQL dispatch purposes (§11 layer-4, §1.8.7).

Closure invariant: ``len(PurposeKey.__args__) == 5``. The audit emitter mirrors
this onto ``bundle.purpose`` and ``query.proposed`` event metadata.
"""


# ──────────────────────────────────────────────────────────────────────────
# Dispatch outcome — closed enum for `QueryArtifact.outcome`.
#
# Per §13: "Every dispatched SQL — accepted, edited, rejected, blocked, or
# errored — produces a YAML artifact." Plus `executed` once the warehouse
# returns a result.
# ──────────────────────────────────────────────────────────────────────────


class QueryOutcome(str, Enum):
    """Terminal state for a dispatched ``QueryArtifact`` (§13).

    - ``proposed``  — `query.proposed` emitted, awaiting user review
    - ``accepted``  — user accepted without edits
    - ``edited``    — user edited before accepting
    - ``rejected``  — user rejected at the review screen
    - ``blocked``   — safety pipeline blocked (Layer 2/3/4 reject)
    - ``executed``  — warehouse returned a result
    - ``errored``   — warehouse returned an error
    - ``cached``    — served from `validated_queries/` cache
    """

    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    EDITED = "edited"
    REJECTED = "rejected"
    BLOCKED = "blocked"
    EXECUTED = "executed"
    ERRORED = "errored"
    CACHED = "cached"


# ──────────────────────────────────────────────────────────────────────────
# ConnectionConfig — adapter + auth method + profile name pointer.
#
# Per §1.7.3: this struct NEVER carries credential values. Only the *name*
# of the credential profile (e.g., "prod", "dev") which the credential
# loader resolves to `~/.agentxp/credentials/{adapter}/{profile}.yaml` at
# dispatch time (chmod-600 enforced on read).
# ──────────────────────────────────────────────────────────────────────────


class ConnectionConfig(BaseModel):
    """Adapter + auth-method + profile-name pointer (§1.7.3 + §12).

    Carried on ``QueryArtifact.target`` and stored in
    ``bundles/{sql_query_writer}.ctx.yaml``. The orchestrator NEVER copies
    credential values into this struct — only the profile name reference. The
    credential loader resolves the name to
    ``~/.agentxp/credentials/{adapter}/{profile_name}.yaml`` at dispatch time
    and refuses to read files that are not chmod 600.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    adapter: AdapterType
    auth_kind: AuthKind
    profile_name: str = Field(
        ...,
        min_length=1,
        description=(
            "Name of the credential profile under "
            "~/.agentxp/credentials/{adapter}/. Never the credential value."
        ),
    )
    # Optional adapter-specific routing hints (Snowflake warehouse / role,
    # BigQuery project / location). These are NOT credentials; they live in
    # the same profile YAML but are safe to log and bundle.
    warehouse: Optional[str] = None
    database: Optional[str] = None
    schema_name: Optional[str] = None
    role: Optional[str] = None
    project_id: Optional[str] = None
    location: Optional[str] = None


# ──────────────────────────────────────────────────────────────────────────
# ResourceBounds — per-purpose limits enforced at Layer 4 (§11).
#
# One row per PurposeKey. The §11 enforcer picks the row matching
# `dispatch.purpose` and injects `LIMIT`, timeout, and bytes-scanned caps
# before sending to the adapter.
# ──────────────────────────────────────────────────────────────────────────


class ResourceBounds(BaseModel):
    """Layer-4 resource limits for a single dispatch purpose (§11).

    ``timeout_s`` and ``bytes_scanned_cap`` are advisory at the v0.1 adapter
    layer (BigQuery enforces bytes-scanned natively via ``maximumBytesBilled``;
    DuckDB has no native cap and falls through). ``row_limit_default`` is the
    ``LIMIT N`` value injected by the AST rewriter when the user-supplied SQL
    has no terminal LIMIT.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    purpose: PurposeKey
    row_limit_default: int = Field(..., ge=1)
    timeout_s: int = Field(..., ge=1)
    bytes_scanned_cap: Optional[int] = Field(
        default=None,
        ge=0,
        description=(
            "Max bytes the warehouse may scan. None = no cap. BigQuery enforces "
            "natively; other adapters log a warning when exceeded post-hoc."
        ),
    )
    require_explain: bool = Field(
        default=False,
        description=(
            "When True, run adapter EXPLAIN before dispatch and surface the "
            "estimated cost in the user-review screen. True for "
            "metric_compute / srm_check; False for profile / preview."
        ),
    )


# ──────────────────────────────────────────────────────────────────────────
# RoutingConfig — where the query goes.
#
# Pairs a ConnectionConfig with the FactSourceBinding(s) that resolve
# semantic-model entities to warehouse-qualified identifiers. The §11
# cross-adapter check (Layer 3a) uses this to assert single-adapter dispatch.
# ──────────────────────────────────────────────────────────────────────────


class RoutingConfig(BaseModel):
    """How a query reaches the warehouse (§11 Layer 3a + §12).

    Pairs a ``ConnectionConfig`` with the fact-source bindings active for
    this dispatch. The Layer-3a single-adapter check asserts that every
    referenced fact_source in this list resolves to the same adapter as the
    connection — otherwise the orchestrator emits
    ``gate.opened(kind="cross_adapter_resolution")`` and pauses.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    connection: ConnectionConfig
    fact_source_bindings: list[FactSourceBinding] = Field(default_factory=list)
    assignment_inline: bool = Field(
        default=False,
        description=(
            "True when assignment lives as a column on the fact source "
            "(matches DataPlanV2.assignment_binding.inline)."
        ),
    )


# ──────────────────────────────────────────────────────────────────────────
# QueryArtifact sub-models — the persisted YAML rows under `queries/{ulid}.yaml`.
# ──────────────────────────────────────────────────────────────────────────


class QueryDialectInfo(BaseModel):
    """Per-adapter SQL renderings (§13).

    ``canonical`` is the sqlglot-IR-rendered form (the audit anchor — what
    the safety pipeline saw). ``rendered`` is the adapter-dialect form
    actually shipped to the warehouse.
    """

    model_config = ConfigDict(extra="forbid")

    canonical_text: str
    canonical_dialect: Literal["sqlglot"] = "sqlglot"
    rendered_text: str
    rendered_dialect: AdapterType


class SafetyLayerResult(BaseModel):
    """One row of the 5-layer safety pipeline (§11) per QueryArtifact."""

    model_config = ConfigDict(extra="forbid")

    layer: Literal[
        "parse",
        "read_only",
        "cross_adapter",
        "semantic",
        "deny_list",
        "resource",
        "sandbox",
    ]
    passed: bool
    reason: Optional[str] = None  # set when passed=False


class ExplainEstimate(BaseModel):
    """Adapter EXPLAIN output (§11 Layer-4 input to the user-review screen)."""

    model_config = ConfigDict(extra="forbid")

    bytes_scanned_estimate: Optional[int] = Field(default=None, ge=0)
    rows_estimate: Optional[int] = Field(default=None, ge=0)
    cost_usd_estimate: Optional[float] = Field(default=None, ge=0.0)
    raw_plan: Optional[str] = None  # opaque adapter-native plan text


class QueryExecution(BaseModel):
    """Warehouse round-trip timing + status (§1.7.2 UTC; §13)."""

    model_config = ConfigDict(extra="forbid")

    started_at: datetime
    ended_at: Optional[datetime] = None
    wall_clock_ms: Optional[int] = Field(default=None, ge=0)
    rows_returned: Optional[int] = Field(default=None, ge=0)
    bytes_scanned: Optional[int] = Field(default=None, ge=0)
    error_class: Optional[str] = None  # canonical name, e.g. "AuthExpiredError"
    error_message: Optional[str] = None  # PII-redacted

    @field_validator("started_at", "ended_at")
    @classmethod
    def _utc(cls, v: Optional[datetime]) -> Optional[datetime]:
        return None if v is None else _enforce_utc(v)


class QueryResultSummary(BaseModel):
    """Aggregate counts + SRM χ² inputs only — never raw warehouse rows (§1.7.1)."""

    model_config = ConfigDict(extra="forbid")

    rows: Optional[int] = Field(default=None, ge=0)
    result_parquet_path: Optional[str] = None  # relative to experiment dir
    result_parquet_sha256: Optional[str] = Field(default=None, min_length=64, max_length=64)
    # SRM-specific (set only when purpose == "srm_check")
    srm_chi_squared: Optional[float] = None
    srm_p_value: Optional[float] = None
    srm_variant_counts: dict[str, int] = Field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────
# QueryArtifact — top-level row at `experiments/{exp_id}/queries/{ulid}.yaml`.
# ──────────────────────────────────────────────────────────────────────────


class QueryArtifact(BaseModel):
    """One row of the per-query audit trail (§13, schema_version 1).

    Persisted to ``experiments/{exp_id}/queries/{ulid}.yaml``. Produced for
    every SQL attempt — accepted, edited, rejected, blocked, or errored. No
    silent drops; this is the audit anchor for ``validate_chain`` Invariant 3
    (§10.7).
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1

    # Identity + provenance.
    query_id: str = Field(..., description="ULID; matches the filename stem")
    action_id: str = Field(
        ...,
        description="9-field action receipt id from log.jsonl (§9 audit receipt)",
    )
    parent_action_id: Optional[str] = Field(
        default=None,
        description="Set on retry / resume re-execution (§10.5.5, §10.6)",
    )
    experiment_id: str
    agent_name: str = Field(
        ...,
        description=(
            "One of the §1.8.8 canonical agent names — typically "
            "sql_query_writer, sql_corrector, monitor, or analyzer."
        ),
    )
    stage: str = Field(
        ...,
        description="The §1.8.4 Stage value active when this query was proposed",
    )
    purpose: PurposeKey

    # Lifecycle.
    proposed_at: datetime
    outcome: QueryOutcome
    outcome_reason: Optional[str] = None  # set on blocked/rejected/errored

    # Auth context for redaction (§1.7.1 / §1.8.7 / B9).
    auth_kind: AuthKind

    # Where the query goes.
    routing: RoutingConfig
    bounds: ResourceBounds

    # The SQL itself (canonical + rendered).
    sql: QueryDialectInfo

    # 5-layer safety pipeline trace.
    safety_trace: list[SafetyLayerResult] = Field(default_factory=list)

    # EXPLAIN preview shown to the user (when require_explain=True).
    explain: Optional[ExplainEstimate] = None

    # User-review screen result (set when outcome in {accepted, edited, rejected}).
    user_review_choice: Optional[Literal["accept", "edit", "reject"]] = None
    user_review_at: Optional[datetime] = None
    edited_text: Optional[str] = None  # set when outcome == "edited"

    # Warehouse execution (set on executed / errored / cached).
    execution: Optional[QueryExecution] = None

    # Aggregate result summary (NEVER raw rows — §1.7.1).
    result_summary: Optional[QueryResultSummary] = None

    # Free-form metadata bucket; closure-tested to ensure no PII keys land here.
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("proposed_at", "user_review_at")
    @classmethod
    def _utc(cls, v: Optional[datetime]) -> Optional[datetime]:
        return None if v is None else _enforce_utc(v)


# ──────────────────────────────────────────────────────────────────────────
# Public API.
# ──────────────────────────────────────────────────────────────────────────


__all__ = [
    # Literals / enums
    "AdapterType",
    "AuthKind",
    "PurposeKey",
    "QueryOutcome",
    # Connection / routing
    "ConnectionConfig",
    "ResourceBounds",
    "RoutingConfig",
    # QueryArtifact sub-models
    "QueryDialectInfo",
    "SafetyLayerResult",
    "ExplainEstimate",
    "QueryExecution",
    "QueryResultSummary",
    # Top-level
    "QueryArtifact",
    # Re-export
    "FactSourceBinding",
]
