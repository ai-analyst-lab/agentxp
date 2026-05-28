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
    "json",
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

AdapterType = Literal["duckdb", "snowflake", "bigquery"]

AggregationGrain = Literal["hour", "day", "week"]

EntityType = Literal["user", "session", "account", "event", "other"]

AssignmentType = Literal["inline", "external"]


# ─────────────────────────────────────────────────────────────────────────
# semantic_models/{entity}.yaml — schema_version: 1
# ─────────────────────────────────────────────────────────────────────────


class SemanticField(BaseModel):
    """A single column in a semantic model. ``levels`` is only meaningful
    for ``role='dimension'`` and is rejected on other roles.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1)
    type: FieldType
    nullable: bool
    role: FieldRole
    levels: Optional[list[str]] = None  # only valid for role="dimension"

    @field_validator("levels")
    @classmethod
    def _levels_only_for_dimension(cls, v, info):
        if v is not None and info.data.get("role") != "dimension":
            raise ValueError("levels is only valid for role='dimension'")
        return v


class RelatedEntity(BaseModel):
    """A non-primary entity referenced by the semantic model (e.g., the
    session attached to a user-event fact).
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1)
    type: EntityType


class Entity(BaseModel):
    """Entity block: primary identifier column + zero or more related entities."""

    model_config = ConfigDict(extra="forbid")

    primary: str = Field(..., min_length=1)
    related: list[RelatedEntity] = Field(default_factory=list)


class SemanticModel(BaseModel):
    """Validates ``semantic_models/{entity}.yaml`` per §8.

    Enforces three structural invariants beyond shape:
      1. ``schema_version == 1`` per §1.8.6.
      2. At most one field has ``role='event_time'``.
      3. ``entity.primary`` names a field whose role is ``identifier``.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    name: str = Field(..., min_length=1, pattern=r"^[a-z][a-z0-9_]*$")
    description: str
    entity: Entity
    fields: list[SemanticField] = Field(..., min_length=1)
    fingerprint_sha256: Optional[str] = Field(
        default=None, min_length=64, max_length=64
    )

    @field_validator("fields")
    @classmethod
    def _at_most_one_event_time(cls, v):
        event_times = [f for f in v if f.role == "event_time"]
        if len(event_times) > 1:
            raise ValueError(
                f"at most one field can have role='event_time'; got {len(event_times)}"
            )
        return v

    @model_validator(mode="after")
    def _primary_key_is_an_identifier(self):
        pk = self.entity.primary
        pk_fields = [f for f in self.fields if f.name == pk]
        if not pk_fields:
            raise ValueError(f"entity.primary={pk!r} not found in fields[]")
        if pk_fields[0].role != "identifier":
            raise ValueError(
                f"primary key field {pk!r} must have role='identifier'"
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
