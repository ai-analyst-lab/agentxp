"""Pydantic result models for AgentXP stats functions.

Stats functions in ``agentxp.stats`` return plain dicts for maximum portability
and serialization ease. These Pydantic shadows exist so external callers, type
checkers, and D.9 computation-trace validators have a typed contract to
reference when persisting or validating results (PRD §5.3, §5.15).

Every model is loose-by-design:

- All fields are optional. Real return dicts may omit keys depending on the
  function's code path (e.g. ``ratio_metric_test`` returns different keys than
  ``welch_test`` even though both feed ``TestResult``).
- ``model_config = ConfigDict(extra="allow")`` so any additional keys
  (e.g. ``computation_trace``, function-specific diagnostics) round-trip
  through ``.model_dump()`` without raising.

The models do NOT replace the dicts at runtime — stats functions continue to
return plain dicts. These classes are for callers who want typed validation
on the boundary (writing ``analysis_results.json``, loading a persisted run,
type-checking orchestrator code).
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class _Result(BaseModel):
    """Base class: every result carries a plain-language interpretation and may
    carry an audit trail plus an opaque ``error`` marker for failed runs.
    """

    model_config = ConfigDict(extra="allow")

    interpretation: Optional[str] = None
    computation_trace: Optional[dict[str, Any]] = None
    error: Optional[Any] = None


class TestResult(_Result):
    """Common shape for welch_test / proportion_test / ratio_metric_test /
    fishers_exact_test / cuped_welch_test / guardrail_test.
    """

    # Tell pytest this is not a test class (it starts with "Test").
    __test__ = False

    test: Optional[str] = None
    effect: Optional[float] = None
    p_value: Optional[float] = None
    significant: Optional[bool] = None
    ci_lower: Optional[float] = None
    ci_upper: Optional[float] = None
    n_control: Optional[int] = None
    n_treatment: Optional[int] = None
    alpha: Optional[float] = None
    decision: Optional[str] = None


class PowerResult(_Result):
    """Shape for power_proportion / power_mean / power_ratio."""

    n_per_group: Optional[int] = None
    sample_size_per_group: Optional[int] = None
    total_n: Optional[int] = None
    total_sample_size: Optional[int] = None
    baseline: Optional[float] = None
    mde: Optional[float] = None
    alpha: Optional[float] = None
    power: Optional[float] = None
    viability: Optional[str] = None


class DurationResult(_Result):
    """Shape for duration_estimate."""

    days: Optional[int] = None
    weeks: Optional[float] = None
    n_required: Optional[int] = None
    daily_enrollment: Optional[float] = None
    viable: Optional[str] = None


class MDEResult(_Result):
    """Shape for detectable_effect."""

    detectable_effect: Optional[float] = None
    n_per_group: Optional[int] = None
    baseline: Optional[float] = None
    alpha: Optional[float] = None
    power: Optional[float] = None


class SensitivityTable(_Result):
    """Shape for power_sensitivity_table — rows = list of per-scenario dicts."""

    rows: list[dict[str, Any]] = Field(default_factory=list)


class SRMResult(_Result):
    """Shape for srm_check / denominator_srm."""

    verdict: Optional[str] = None
    chi2: Optional[float] = None
    chi2_stat: Optional[float] = None
    p_value: Optional[float] = None
    expected: Optional[list[float]] = None
    observed: Optional[list[float]] = None
    expected_counts: Optional[list[float]] = None
    observed_counts: Optional[list[float]] = None
    threshold: Optional[float] = None


class DiagnosisResult(_Result):
    """Shape for srm_diagnose — segment-level breakdown of an SRM block."""

    worst_segment: Optional[str] = None
    segment_results: list[dict[str, Any]] = Field(default_factory=list)


class EffectSizeResult(_Result):
    """Shape for cohens_d / cohens_h."""

    value: Optional[float] = None
    d: Optional[float] = None
    h: Optional[float] = None
    magnitude: Optional[str] = None


class LiftResult(_Result):
    """Shape for relative_lift."""

    absolute: Optional[float] = None
    relative: Optional[float] = None
    control_mean: Optional[float] = None
    treatment_mean: Optional[float] = None


class CorrectionResult(_Result):
    """Shape for adjust_pvalues."""

    adjusted_pvalues: Optional[list[float]] = None
    rejected: Optional[list[bool]] = None
    method: Optional[str] = None
    alpha: Optional[float] = None


class CUPEDResult(_Result):
    """Shape for cuped_welch_test / variance_reduction."""

    theta: Optional[float] = None
    variance_reduction_pct: Optional[float] = None
    adjusted_effect: Optional[float] = None
    effect: Optional[float] = None
    p_value: Optional[float] = None
    ci_lower: Optional[float] = None
    ci_upper: Optional[float] = None


class SequentialResult(_Result):
    """Shape for msprt_test / always_valid_ci / sequential_proportion_test /
    group_sequential_boundaries.
    """

    statistic: Optional[float] = None
    always_valid_lower: Optional[float] = None
    always_valid_upper: Optional[float] = None
    ci_lower: Optional[float] = None
    ci_upper: Optional[float] = None
    decision: Optional[str] = None
    boundary: Optional[float] = None


class BayesianResult(_Result):
    """Shape for beta_binomial_test / normal_normal_test."""

    p_to_beat: Optional[float] = None
    probability_to_beat: Optional[float] = None
    credible_lower: Optional[float] = None
    credible_upper: Optional[float] = None
    expected_loss: Optional[float] = None
    expected_loss_ship: Optional[float] = None
    expected_loss_abort: Optional[float] = None
    decision: Optional[str] = None


class ExtensionResult(_Result):
    """Shape for extension_estimate."""

    additional_days: Optional[int] = None
    additional_n: Optional[int] = None
    revised_mde: Optional[float] = None
    viable: Optional[bool] = None


class MonitorReportModel(_Result):
    """Pydantic shadow of the monitoring.MonitorReport dataclass.

    This is the JSON-contract surface for ``run_monitor`` output so external
    consumers (dashboards, history files, agents) can validate on the boundary
    without importing the dataclass.
    """

    status: Optional[str] = None
    checks: dict[str, Any] = Field(default_factory=dict)
    recommendations: list[str] = Field(default_factory=list)
    timestamp: Optional[str] = None
    persistence_error: Optional[str] = None


__all__ = [
    "TestResult",
    "PowerResult",
    "DurationResult",
    "MDEResult",
    "SensitivityTable",
    "SRMResult",
    "DiagnosisResult",
    "EffectSizeResult",
    "LiftResult",
    "CorrectionResult",
    "CUPEDResult",
    "SequentialResult",
    "BayesianResult",
    "ExtensionResult",
    "MonitorReportModel",
]
