"""Pydantic validators for semantic_models, metrics, fact_sources, and
assignments YAML files. Used by semantic_modeler (W_pre3.1) and
metric_drafter (W_pre3.2) on commit; also by the orchestrator on load.

All models set ``extra="forbid"`` so unknown fields fail fast — a malformed
YAML cannot silently pollute downstream stages (fingerprint, bundle, design,
analysis).

Source spec:
  - experimentation-platform/OPENXP_V01_PLAN.md §8 (YAML shapes —
    semantic_models, fact_sources, metrics, assignments)
  - §1.8.6 (schema_version policy)
  - §1.8.14 (Cohort field names — applies to assignments)
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ─────────────────────────────────────────────────────────────────────────
# Closed-set Literals (§8)
# ─────────────────────────────────────────────────────────────────────────

FieldRole = Literal[
    "identifier",
    "event_time",
    "assignment",
    "outcome",
    "dimension",
    "measure",
    "metadata",
]

FieldType = Literal[
    "string",
    "integer",
    "float",
    "bool",
    "timestamp",
    "date",
]

MetricType = Literal[
    "ratio",
    "count",
    "sum",
    "avg",
    "p50",
    "p75",
    "p90",
    "p95",
    "p99",
]

MetricDirection = Literal["higher_is_better", "lower_is_better", "neither"]

AdapterType = Literal["duckdb", "snowflake", "bigquery", "databricks"]

AggregationGrain = Literal["hour", "day", "week"]

EntityType = str
"""Entity vocabularies are domain-specific (user, session, account, product,
order, ticket, lead, ...). Closing this to a fixed set is brittle; the
semantic_modeler agent picks the right name from the data and the user
overrides when needed.
"""

AssignmentType = Literal["inline", "external"]


# ─────────────────────────────────────────────────────────────────────────
# semantic_models/{entity}.yaml — schema_version: 1
#
# T70-RECONCILE — rewritten to match the on-disk format used by every
# experiment dir in the repo. The pre-T70 schema (entity + typed
# fields[] + role taxonomy) was drafted from OPENXP_V01_PLAN.md §8 but
# never adopted by the design-verb runtime code; the on-disk YAMLs use
# a dbt/Looker-shaped layout instead (display_name + primary_key +
# source_table + dimensions[] + relationships[] + outcome_columns[]).
# Choosing on-disk as canonical preserves every existing experiment;
# the typed role taxonomy is recoverable later by adding optional
# per-dimension `role:` declarations.
# ─────────────────────────────────────────────────────────────────────────


class Dimension(BaseModel):
    """A single dimension column on a semantic model.

    Fields mirror the dbt-style on-disk shape: ``name`` + ``type`` +
    ``description``, plus an optional ``enum`` listing the closed value
    set (used by ``page_event.event_name`` and similar).
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1)
    type: Literal["string", "integer", "float", "bool", "timestamp", "date"]
    description: Optional[str] = None
    enum: Optional[list[str]] = Field(
        default=None,
        description="Closed set of accepted values (e.g. event_name = product_view | click_buy_now | ...).",
    )


class Relationship(BaseModel):
    """A foreign-key edge from this semantic model to another.

    ``join_on`` is the local column joining the related entity. Pre-T70 the
    on-disk YAMLs used ``on:`` for this slot, but PyYAML parses bare ``on``
    as the boolean ``True`` (YAML 1.1 reserved word) which corrupts the
    dict. Renaming to ``join_on:`` sidesteps the parser quirk; the YAMLs
    were migrated in the same change that introduced this schema.
    """

    model_config = ConfigDict(extra="forbid")

    to: str = Field(..., min_length=1, description="Target entity name.")
    join_on: str = Field(
        ..., min_length=1,
        description="Local column the join is on.",
    )
    type: Literal["one_to_one", "one_to_many", "many_to_one", "many_to_many"]
    description: Optional[str] = None


class SemanticModel(BaseModel):
    """Validates ``semantic_models/{entity}.yaml`` per §8 (T70-rewritten).

    Structural invariants:
      1. ``schema_version == 1`` per §1.8.6.
      2. ``primary_key`` names columns; the shape is a single name string
         or a list of names for compound keys (assignment, page_event).
      3. ``outcome_columns`` is required (W1.8); an empty list explicitly
         declares "this entity has no outcome surface" so SQL safety
         Layer 3d (R11) does not silently treat a missing field as "no
         outcomes".
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    name: str = Field(..., min_length=1, pattern=r"^[a-z][a-z0-9_]*$")
    display_name: Optional[str] = None
    description: Optional[str] = None
    primary_key: str | list[str] = Field(
        ...,
        description="Single column name or list[str] for compound keys.",
    )
    source_table: str = Field(..., min_length=1)
    dimensions: list[Dimension] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)
    outcome_columns: list[str] = Field(
        ...,
        description=(
            "Names of outcome-bearing columns this entity carries (W1.8 — "
            "required, no default). Layer 3d of the SQL safety pipeline "
            "(R11) consults this declaration when refusing design-mode "
            "queries that touch outcome surfaces. An empty list means "
            "the entity exposes no outcomes; ``None`` is rejected."
        ),
    )
    fingerprint_sha256: Optional[str] = Field(
        default=None, min_length=64, max_length=64
    )

    @model_validator(mode="after")
    def _warn_on_primary_key_not_in_dimensions(self):
        """Soft check — warn if primary_key columns are not declared as dimensions.

        Audit item #5: was previously a hard raise, which forced YAML
        authors to redundantly list every primary-key column in
        ``dimensions[]`` even when the column was already named by
        ``primary_key``. That's a real opinion the schema shouldn't
        impose. Emits a ``UserWarning`` so the missing declaration is
        visible at load time but does not block the model from
        constructing.
        """
        import warnings

        pk_names = (
            [self.primary_key] if isinstance(self.primary_key, str)
            else list(self.primary_key)
        )
        dim_names = {d.name for d in self.dimensions}
        missing = [n for n in pk_names if n not in dim_names]
        if missing:
            warnings.warn(
                f"SemanticModel {self.name!r}: primary_key column(s) "
                f"{missing!r} are not declared in dimensions[]. "
                f"This is allowed but unusual — consider adding the "
                f"dimensions so downstream tools can introspect them.",
                UserWarning,
                stacklevel=2,
            )
        return self


# ─────────────────────────────────────────────────────────────────────────
# fact_sources/{name}.yaml — schema_version: 1
# ─────────────────────────────────────────────────────────────────────────


class FactSourceLocation(BaseModel):
    """Physical-table location pointer used by adapters (§8)."""

    model_config = ConfigDict(extra="forbid")

    resolved_to: str = Field(..., min_length=1)
    adapter: AdapterType
    profile_name: Optional[str] = None


class FactSource(BaseModel):
    """Validates ``fact_sources/{name}.yaml`` per §8.

    Binds a semantic model to a physical table and declares the time column
    plus the default aggregation grain used by the bundle/design stages.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    name: str = Field(..., min_length=1, pattern=r"^[a-z][a-z0-9_]*$")
    semantic_model: str = Field(..., min_length=1)
    source: FactSourceLocation
    time_column: str = Field(..., min_length=1)
    default_aggregation_grain: AggregationGrain = "day"


# ─────────────────────────────────────────────────────────────────────────
# metrics/{name}.yaml — schema_version: 2
# ─────────────────────────────────────────────────────────────────────────


class MetricExpression(BaseModel):
    """SQL-fragment expression block; rendered into the bundle by the
    metric compiler.
    """

    model_config = ConfigDict(extra="forbid")

    expression: str = Field(..., min_length=1)


class MetricRequires(BaseModel):
    """A required field reference (validated against the semantic model on
    bundle build).
    """

    model_config = ConfigDict(extra="forbid")

    field: str = Field(..., min_length=1)


class MetricYAML(BaseModel):
    """Validates ``metrics/{name}.yaml`` per §8 (schema_version 2).

    Cross-field rule: ratio metrics require both ``numerator`` and
    ``denominator`` and forbid ``aggregation``; all other types require
    ``aggregation`` and forbid ``numerator``/``denominator``.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[2] = 2
    name: str = Field(..., min_length=1, pattern=r"^[a-z][a-z0-9_]*$")
    display_name: str
    description: str
    type: MetricType
    fact_source: str
    numerator: Optional[MetricExpression] = None
    denominator: Optional[MetricExpression] = None
    aggregation: Optional[MetricExpression] = None
    requires: list[MetricRequires] = Field(default_factory=list)
    guardrail: bool = False
    direction: MetricDirection
    mde_default_pct: float = Field(..., ge=0.0)

    @model_validator(mode="after")
    def _expressions_match_type(self):
        if self.type == "ratio":
            if self.numerator is None or self.denominator is None:
                raise ValueError(
                    "ratio metrics require both numerator and denominator"
                )
            if self.aggregation is not None:
                raise ValueError("ratio metrics must not have aggregation")
        else:
            if self.aggregation is None:
                raise ValueError(
                    f"metric type {self.type!r} requires aggregation"
                )
            if self.numerator is not None or self.denominator is not None:
                raise ValueError(
                    f"metric type {self.type!r} must not have numerator/denominator"
                )
        return self


# ─────────────────────────────────────────────────────────────────────────
# assignments/{name}.yaml — schema_version: 1
# ─────────────────────────────────────────────────────────────────────────


class AssignmentYAML(BaseModel):
    """Validates ``assignments/{name}.yaml`` per §8 / §1.8.14.

    Declares the variant column, fact source, randomization unit, and
    optional exposure filter for an experiment's assignment table.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    name: str = Field(..., min_length=1, pattern=r"^[a-z][a-z0-9_]*$")
    description: str
    type: AssignmentType
    variant_column: str = Field(..., min_length=1)
    fact_source: str = Field(..., min_length=1)
    randomization_unit: str = Field(..., min_length=1)
    exposed_filter: Optional[str] = None


__all__ = [
    "AdapterType",
    "AggregationGrain",
    "AssignmentType",
    "AssignmentYAML",
    "Entity",
    "EntityType",
    "FactSource",
    "FactSourceLocation",
    "FieldRole",
    "FieldType",
    "MetricDirection",
    "MetricExpression",
    "MetricRequires",
    "MetricType",
    "MetricYAML",
    "RelatedEntity",
    "SemanticField",
    "SemanticModel",
]
