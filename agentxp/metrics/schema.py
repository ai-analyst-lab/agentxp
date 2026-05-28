"""
Metric definition schema for AgentXP.

A MetricDefinition describes a reusable metric (e.g. checkout_completion_rate)
independent of any single experiment. Experiments reference metrics by name;
the registry resolves each name to a MetricDefinition, which in turn maps to
the correct statistical test function in agentxp.stats.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Optional

from agentxp.stats.ab_tests import proportion_test, ratio_metric_test, welch_test

MetricType = Literal["proportion", "mean", "ratio"]

VALID_TYPES: tuple[str, ...] = ("proportion", "mean", "ratio")

REQUIRED_FIELDS: tuple[str, ...] = ("name", "type", "numerator", "description")


@dataclass
class MetricDefinition:
    """Reusable metric definition loaded from a YAML file.

    Fields:
        name: Unique metric identifier (e.g. "checkout_completion_rate").
        type: One of "proportion", "mean", "ratio".
        numerator: Column/expression that produces the numerator series.
        denominator: Required for "ratio"; ignored otherwise.
        unit: Experimental unit (e.g. "user_id", "session_id").
        description: Human-readable description.
        baseline_range: Tuple (low, high) of expected baseline values.
        winsorize: Whether to winsorize before testing.
        winsorize_bounds: (lower_quantile, upper_quantile); both in [0, 1].
        invert: If True, lower values are better (e.g. bounce_rate).
        tags: Free-form tags for organization.
    """

    name: str
    type: MetricType
    numerator: str
    description: str
    unit: str = ""
    denominator: Optional[str] = None
    baseline_range: tuple[float, float] = (0.0, 1.0)
    winsorize: bool = False
    winsorize_bounds: tuple[float, float] = (0.01, 0.99)
    invert: bool = False
    tags: list[str] = field(default_factory=list)


class MetricValidationError(ValueError):
    """Raised when a metric dict fails validation."""


def _coerce_bounds(value: Any, field_name: str) -> tuple[float, float]:
    if value is None:
        raise MetricValidationError(f"'{field_name}' is required")
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise MetricValidationError(
            f"'{field_name}' must be a 2-element sequence [low, high], got {value!r}"
        )
    try:
        low = float(value[0])
        high = float(value[1])
    except (TypeError, ValueError) as e:
        raise MetricValidationError(
            f"'{field_name}' values must be numeric, got {value!r}"
        ) from e
    return (low, high)


def validate(md: dict) -> MetricDefinition:
    """Validate a dict (from YAML) and return a MetricDefinition.

    Accepts either a flat dict or a dict wrapped with a top-level 'metric' key
    (to match the YAML layout in OPENXP_PRD §5.7).

    Raises:
        MetricValidationError on any validation problem, with a clear message
        indicating the offending field.
    """
    if not isinstance(md, dict):
        raise MetricValidationError(f"metric definition must be a dict, got {type(md).__name__}")

    # Support YAML files that wrap the definition in a top-level `metric:` key.
    if "metric" in md and isinstance(md["metric"], dict) and "name" not in md:
        md = md["metric"]

    for required in REQUIRED_FIELDS:
        if required not in md or md[required] in (None, ""):
            raise MetricValidationError(
                f"missing required field '{required}' in metric definition"
            )

    metric_type = md["type"]
    if metric_type not in VALID_TYPES:
        raise MetricValidationError(
            f"invalid metric type '{metric_type}'; must be one of {VALID_TYPES}"
        )

    denominator = md.get("denominator")
    if metric_type == "ratio" and not denominator:
        raise MetricValidationError(
            "metric type 'ratio' requires a 'denominator' field"
        )

    baseline_range = _coerce_bounds(md.get("baseline_range", [0.0, 1.0]), "baseline_range")
    if baseline_range[0] > baseline_range[1]:
        raise MetricValidationError(
            f"baseline_range lower ({baseline_range[0]}) must be <= upper ({baseline_range[1]})"
        )

    winsorize_flag = bool(md.get("winsorize", False))
    winsorize_bounds = _coerce_bounds(
        md.get("winsorize_bounds", [0.01, 0.99]), "winsorize_bounds"
    )
    lo, hi = winsorize_bounds
    if not (0.0 <= lo <= 1.0) or not (0.0 <= hi <= 1.0):
        raise MetricValidationError(
            f"winsorize_bounds must lie in [0, 1], got ({lo}, {hi})"
        )
    if lo >= hi:
        raise MetricValidationError(
            f"winsorize_bounds lower ({lo}) must be strictly less than upper ({hi})"
        )

    tags = md.get("tags", []) or []
    if not isinstance(tags, list):
        raise MetricValidationError(f"'tags' must be a list, got {type(tags).__name__}")

    return MetricDefinition(
        name=str(md["name"]),
        type=metric_type,  # type: ignore[arg-type]
        numerator=str(md["numerator"]),
        description=str(md["description"]),
        unit=str(md.get("unit", "")),
        denominator=str(denominator) if denominator else None,
        baseline_range=baseline_range,
        winsorize=winsorize_flag,
        winsorize_bounds=winsorize_bounds,
        invert=bool(md.get("invert", False)),
        tags=[str(t) for t in tags],
    )


def to_test_function(md: MetricDefinition) -> Callable:
    """Return the stats function appropriate for this metric's type.

    - proportion -> agentxp.stats.proportion_test
    - mean       -> agentxp.stats.welch_test
    - ratio      -> agentxp.stats.ratio_metric_test
    """
    if md.type == "proportion":
        return proportion_test
    if md.type == "mean":
        return welch_test
    if md.type == "ratio":
        return ratio_metric_test
    raise MetricValidationError(f"unknown metric type '{md.type}'")
