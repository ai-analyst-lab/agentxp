"""Canonical schema for ``data_plan.yaml`` v2.

Captures the user's data-source binding for one experiment. Owned by the Stage
4 commit (``data_plan_confirmed``); also serialized as the nested
``state.yaml.data_plan`` block.

Source spec:
  - experimentation-platform/OPENXP_V01_PLAN.md §7      — DataPlanV2 layout
  - experimentation-platform/OPENXP_V01_PLAN.md §1.7.1  — PII flow surfaces
  - experimentation-platform/OPENXP_V01_PLAN.md §1.7.2  — UTC enforcement
  - experimentation-platform/OPENXP_V01_PLAN.md §1.8.6  — schema_version policy
  - experimentation-platform/OPENXP_V01_PLAN.md §10.5.5 — auth_expired flow
                                                          (status transitions
                                                          on auth events)

Build task: sys-w_pre1-02 (BUILD_STATUS.yaml W_pre1.2). The locked SourceType
enum carries 8 values (file + 7 warehouse adapters) — broader than §7's
3-value summary; the wider enum is the canonical surface for the connection
adapter layer (W_pre1.7). DuckDB is treated as a separate ``source_type``
rather than collapsed under ``warehouse`` so the data-plan can distinguish
"local embedded engine" from "remote warehouse profile" without consulting
the adapter table.
"""
from __future__ import annotations

import os
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from agentxp.schemas._types import Sha256Hex


# ──────────────────────────────────────────────────────────────────────────
# Shared UTC validator. Mirror of ``agentxp.schemas.state._enforce_utc`` —
# duplicated rather than imported to keep this module self-contained for
# the closure-test harness (per W_pre0.2 conventions).
# ──────────────────────────────────────────────────────────────────────────


def _enforce_utc(v: datetime) -> datetime:
    """Reject naive datetimes and non-UTC tzinfo (§1.7.2 time-zone policy).

    Accepts any tzinfo whose UTC offset is zero (``timezone.utc``,
    ``ZoneInfo("UTC")``, ``ZoneInfo("Etc/UTC")``). All persisted timestamps
    in AgentXP are UTC ISO-8601 with a ``Z`` suffix; cohort-local windows are
    represented separately as IANA names on ``Cohort.timezone`` in
    ``state.py``.
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
# SourceType — locked 8-value enum (file + 7 warehouse adapters).
#
# §7's summary lists 3 categorical values ("file", "duckdb", "warehouse");
# the build task expands "warehouse" into the 6 concrete adapter names so
# adapter-aware code paths (W_pre1.7 connection layer, §10.5.5 auth flows)
# can pattern-match on a single field rather than joining against a
# separate adapter table.
# ──────────────────────────────────────────────────────────────────────────


class SourceType(str, Enum):
    """The 8 source types DataPlanV2.source_type may take.

    ``FILE`` covers any local file-based source loaded via DuckDB's
    auto-detection (parquet, CSV, JSON). ``DUCKDB`` is a persisted DuckDB
    database file. The remaining six are remote warehouse adapters whose
    credentials live in ``~/.agentxp/credentials/{type}/{profile}.yaml`` per
    §1.7.3.
    """

    FILE = "file"
    DUCKDB = "duckdb"
    SNOWFLAKE = "snowflake"
    BIGQUERY = "bigquery"
    POSTGRES = "postgres"
    MYSQL = "mysql"
    REDSHIFT = "redshift"
    DATABRICKS = "databricks"


# Lowercase aliases so attribute access matches the canonical snake_case
# strings (parity with ``state.Stage`` / ``state.PendingDecisionKind``).
for _member in list(SourceType):
    setattr(SourceType, _member.value, _member)
del _member


_WAREHOUSE_SOURCE_TYPES: frozenset[SourceType] = frozenset(
    {
        SourceType.SNOWFLAKE,
        SourceType.BIGQUERY,
        SourceType.POSTGRES,
        SourceType.MYSQL,
        SourceType.REDSHIFT,
        SourceType.DATABRICKS,
    }
)
"""SourceType values that require ``warehouse_profile`` to be set."""


# ──────────────────────────────────────────────────────────────────────────
# Sub-models.
# ──────────────────────────────────────────────────────────────────────────


class DataFingerprint(BaseModel):
    """Hash + provenance for the actual data the experiment reads.

    The fingerprint is computed once on first profile and re-checked on
    every subsequent load; a mismatch fires the
    ``referenced_artifact_changed`` gate per §10.5.9.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    rows: int = Field(..., ge=0)
    cols: int = Field(..., ge=1)
    schema_sha256: Sha256Hex
    profiled_at: datetime

    @field_validator("profiled_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return _enforce_utc(v)


class FactSourceBinding(BaseModel):
    """One fact-source binding (per-experiment override of a project-level
    ``fact_sources/{name}.yaml``).

    The shape mirrors Eppo's fact-source pattern: the experiment names a
    project-level fact_source by ``fact_source`` and the binding records
    where that source resolves at run time (warehouse-qualified identifier
    + adapter + connection profile).
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    fact_source: str
    resolved_to: str
    adapter: Optional[str] = None
    profile_name: Optional[str] = None


class AssignmentBinding(BaseModel):
    """Where assignment data lives — separate from fact data per Track 2.

    ``inline=True`` means assignment lives as a column on the fact source
    (the ``variant_column`` field); ``inline=False`` means assignment is a
    standalone ``assignments/{name}.yaml`` joined by entity at query time.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    assignment: str
    inline: bool = False
    variant_column: Optional[str] = None


class OptionalUsefulEvent(BaseModel):
    """An event the data-archaeology agent thinks would be useful but the
    user did not volunteer in the brief.

    Capped at 1 in v0.1 to keep the surfacing UX simple; the cap is enforced
    by a ``DataPlanV2.optional_useful_events`` field validator. Lift to N
    in v0.2 once the bundle store can present a multi-event prompt.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    event_name: str
    rationale: str
    surfaced_at: datetime

    @field_validator("surfaced_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return _enforce_utc(v)


# ──────────────────────────────────────────────────────────────────────────
# DataPlanV2 root.
# ──────────────────────────────────────────────────────────────────────────


class DataPlanV2(BaseModel):
    """``data_plan.yaml`` v2 root schema (§7).

    schema_version is locked at ``2`` for v0.1 (§1.8.6). The bump from v1
    added the ``status`` Literal (HG-E3 / F.GAP.13) and per-source typing.
    Loading a file with ``schema_version > 2`` raises at parse time per the
    §6.5 forward-compat policy.

    ``status`` transitions (§10.5.5 auth_expired path keeps status pinned
    at ``executed`` until the user resumes — the orchestrator does not
    downgrade status on transient auth failure):
        - ``draft``     after Stage 0 partial source registration
        - ``confirmed`` after Stage 4 ``confirm_data_plan`` gate resolves
        - ``executed``  after the first non-trivial dispatched query
                        completes against this plan
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[2] = 2
    experiment_id: str
    created_at: datetime
    updated_at: datetime
    status: Literal["draft", "confirmed", "executed"] = "draft"

    # ── Source binding ────────────────────────────────────────────────
    source_type: SourceType
    source_path: Optional[str] = None         # SourceType.FILE / DUCKDB
    warehouse_profile: Optional[str] = None   # 6 warehouse SourceType values
    registered_as: str

    # ── Profiling + bindings ──────────────────────────────────────────
    fingerprint: Optional[DataFingerprint] = None  # populated post-profile
    fact_source_bindings: list[FactSourceBinding] = Field(default_factory=list)
    assignment_binding: Optional[AssignmentBinding] = None

    # ── Stage 4 readiness flags ───────────────────────────────────────
    ready_for_analysis: bool = False
    pruned: bool = False

    # ── Data-archaeology surfacing (v0.1: capped at 1) ────────────────
    optional_useful_events: list[OptionalUsefulEvent] = Field(
        default_factory=list, max_length=1
    )

    # ── Validators ────────────────────────────────────────────────────

    @field_validator("created_at", "updated_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return _enforce_utc(v)

    @field_validator("optional_useful_events")
    @classmethod
    def _v01_max_one(cls, v: list[OptionalUsefulEvent]) -> list[OptionalUsefulEvent]:
        if len(v) > 1:
            raise ValueError(
                f"v0.1 caps optional_useful_events at 1 (got {len(v)}). "
                "Lift to N in v0.2; see OPENXP_V01_PLAN.md §7."
            )
        return v


# ──────────────────────────────────────────────────────────────────────────
# YAML I/O helpers.
#
# safe_load + safe_dump keep us out of arbitrary-object territory; the
# atomic write pattern (tmp + os.replace) mirrors the state_store and
# audit/storage writers (B4, M111).
# ──────────────────────────────────────────────────────────────────────────


def load_data_plan(path: Path) -> DataPlanV2:
    """Load + validate a ``data_plan.yaml`` file.

    Raises:
        FileNotFoundError: if ``path`` does not exist.
        yaml.YAMLError:    on malformed YAML (caller routes to §10.5.4).
        pydantic.ValidationError: on schema_version mismatch, unknown
                                   ``source_type``, non-UTC timestamps, or
                                   any other invariant violation.
    """
    text = Path(path).read_text(encoding="utf-8")
    raw: Any = yaml.safe_load(text)
    if raw is None:
        raise ValueError(f"data_plan file is empty: {path}")
    if not isinstance(raw, dict):
        raise ValueError(
            f"data_plan file must be a YAML mapping at the top level: {path}"
        )
    return DataPlanV2.model_validate(raw)


def save_data_plan(plan: DataPlanV2, path: Path) -> None:
    """Serialize + atomic-write a ``DataPlanV2`` to disk.

    Uses ``mode="json"`` so datetimes serialize as ISO-8601 strings (with
    the Z suffix preserved by ``_enforce_utc`` on the round trip). Writes
    to ``path.tmp`` then ``os.replace`` for atomicity (B4).
    """
    target = Path(path)
    data = plan.model_dump(mode="json")
    text = yaml.safe_dump(data, sort_keys=False, default_flow_style=False)

    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, target)


# ──────────────────────────────────────────────────────────────────────────
# Public API.
# ──────────────────────────────────────────────────────────────────────────


__all__ = [
    # enums
    "SourceType",
    # constants
    "_WAREHOUSE_SOURCE_TYPES",
    # sub-models
    "DataFingerprint",
    "FactSourceBinding",
    "AssignmentBinding",
    "OptionalUsefulEvent",
    # root
    "DataPlanV2",
    # I/O
    "load_data_plan",
    "save_data_plan",
]
