"""Canonical schemas for the OpenXP v0.1 Stage-0 profiler output.

The profiler runs DuckDB ``SUMMARIZE`` plus two HG-D4 heuristics
(null-rate-on-identifier + mixed-timestamp-format detection) and writes its
output to ``experiments/{exp_id}/bundles/profiler.out.yaml``. Downstream
``semantic_modeler`` (Stage 0.5) and ``metric_drafter`` (Stage 0.75) consume
that bundle.

Source spec: experimentation-platform/OPENXP_V01_PLAN.md
  - §1.0 schema amendments (3): ``ProfileReportRow`` adds ``null_rate``,
         ``mixed_format_detected``, ``format_samples``, ``flagged_for_review``,
         ``flag_reason`` (HG-D4 fields).
  - §1.7.2  Time-zone policy — every datetime field is UTC-enforced.
  - §1.8.6  schema_version policy — ``bundles/profiler.out.yaml`` is at v1.
  - §5      Agent table — ``profiler`` is a NEW Stage-0 agent dispatched with
            purpose=``profile`` (smallest resource budget).
  - §10.5.5 mixed_timestamp_formats gate (data-quality gate, F.PRACTICE.02).
  - HG-D4   re-budget for null-rate + mixed-timestamp heuristics.

Closure-tested by tests/coherence/test_canonical_names.py.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from openxp.schemas.state import _enforce_utc


# ──────────────────────────────────────────────────────────────────────────
# DType — closed set of DuckDB SUMMARIZE column-type classes the profiler
# surfaces upward. The full DuckDB type system is much larger; the profiler
# coalesces into this small set so downstream agents can switch on it.
# ──────────────────────────────────────────────────────────────────────────


DType = Literal[
    "integer",
    "float",
    "boolean",
    "string",
    "timestamp",
    "date",
    "time",
    "interval",
    "json",
    "binary",
    "unknown",
]
"""Coalesced column-type class (one of 11 closed values).

The profiler maps DuckDB's native types into this set:
``BIGINT``/``INTEGER``/``SMALLINT`` → ``integer``; ``DOUBLE``/``DECIMAL`` →
``float``; ``VARCHAR``/``TEXT`` → ``string``; ``TIMESTAMP``/``TIMESTAMPTZ`` →
``timestamp``; etc. Unknown / extension types fall through to ``"unknown"``.
"""


# ──────────────────────────────────────────────────────────────────────────
# ColumnProfile — one row per column in the profiled table.
#
# Mirrors the public per-column shape consumed by ``semantic_modeler`` and
# ``metric_drafter``. HG-D4 fields live here so per-column flags survive into
# the gate metadata when ``mixed_timestamp_formats`` fires.
# ──────────────────────────────────────────────────────────────────────────


class ColumnProfile(BaseModel):
    """Per-column profile row (one entry of ``ProfileReport.columns``).

    Field semantics:
      - ``null_rate`` — fraction of rows where the column is NULL, in
        ``[0.0, 1.0]``. A ``null_rate`` above 0.5 on a column the
        semantic-modeler is about to nominate as an entity primary key trips
        the HG-D4 null-rate-on-identifier soft warning.
      - ``distinct_count`` — DuckDB ``approx_count_distinct`` is acceptable;
        the profiler picks the exact count for tables under 1M rows and
        falls back to approx_count_distinct otherwise.
      - ``sample_values`` — up to 10 representative samples for the user-
        review screen. Strings are truncated to 80 chars per entry.
      - ``mixed_format_detected`` + ``format_samples`` — HG-D4: True when the
        column dtype is ``string`` but the values appear to be heterogeneous
        timestamp / date / number formats. ``format_samples`` carries 2-5
        specific strings that triggered the detection (used verbatim in the
        gate prompt).
      - ``flagged_for_review`` — orchestrator-set; True when at least one
        heuristic on this column wants user attention.
      - ``flag_reason`` — single human-readable sentence; populated when
        ``flagged_for_review`` is True.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1)
    dtype: DType
    null_rate: float = Field(..., ge=0.0, le=1.0)
    distinct_count: Optional[int] = Field(default=None, ge=0)
    distinct_count_is_approx: bool = False

    # Min/max + quartiles surface from DuckDB SUMMARIZE for numeric / temporal
    # columns. Strings carry length stats instead (q25/q50/q75 unused).
    min_value: Optional[Any] = None
    max_value: Optional[Any] = None
    q25: Optional[float] = None
    q50: Optional[float] = None
    q75: Optional[float] = None
    mean: Optional[float] = None
    stddev: Optional[float] = None
    min_length: Optional[int] = Field(default=None, ge=0)
    max_length: Optional[int] = Field(default=None, ge=0)

    sample_values: list[str] = Field(default_factory=list, max_length=10)

    # ── HG-D4 heuristics (per-column) ────────────────────────────────────
    mixed_format_detected: bool = False
    format_samples: list[str] = Field(default_factory=list, max_length=5)

    flagged_for_review: bool = False
    flag_reason: Optional[str] = None


# ──────────────────────────────────────────────────────────────────────────
# ProfileReport — top-level Stage-0 profiler output (bundles/profiler.out.yaml).
# ──────────────────────────────────────────────────────────────────────────


class ProfileReport(BaseModel):
    """Stage-0 profiler output (``bundles/profiler.out.yaml``, schema_version 1).

    Aggregates per-column profiles (``columns``) with table-level metadata
    and the HG-D4 mixed-format detection summary (``mixed_format_detected``,
    ``format_samples``, ``flagged_for_review``, ``flag_reason``).

    The top-level ``mixed_format_detected`` is the OR over every
    ``ColumnProfile.mixed_format_detected``; ``format_samples`` is the union
    (deduped, capped at 10). When ``mixed_format_detected`` is True at the
    table level, the orchestrator fires
    ``gate.opened(kind="mixed_timestamp_formats")`` per §1.8.1 and pauses
    Stage 0 commit.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1

    # ── Identity ─────────────────────────────────────────────────────────
    source_ref: str = Field(
        ...,
        description=(
            "Where the profiled data came from — matches "
            "DataPlanV2.registered_as (e.g., 'openxp_data.checkout_events')."
        ),
    )
    profiled_at: datetime

    # ── Table-level stats ───────────────────────────────────────────────
    row_count: int = Field(..., ge=0)
    column_count: int = Field(..., ge=1)
    schema_sha256: str = Field(..., min_length=64, max_length=64)

    # ── Per-column profiles ─────────────────────────────────────────────
    columns: list[ColumnProfile] = Field(default_factory=list)

    # ── HG-D4 table-level flags (OR over per-column) ────────────────────
    mixed_format_detected: bool = False
    format_samples: list[str] = Field(default_factory=list, max_length=10)
    flagged_for_review: bool = False
    flag_reason: Optional[str] = None

    # ── Suggestions surfaced to downstream agents ───────────────────────
    # ``suggestions`` carries free-form hints (e.g., "session_id looks like an
    # entity primary key") consumed by the metric_drafter at Stage 0.75 per
    # the §3 stage table.
    suggestions: list[str] = Field(default_factory=list)

    # ── Free-form metadata bucket ───────────────────────────────────────
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("profiled_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return _enforce_utc(v)


# ──────────────────────────────────────────────────────────────────────────
# Public API.
# ──────────────────────────────────────────────────────────────────────────


__all__ = [
    "DType",
    "ColumnProfile",
    "ProfileReport",
]
