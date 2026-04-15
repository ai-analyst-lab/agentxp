"""Tests for the OpenXP metric definitions library (openxp.metrics)."""

from __future__ import annotations

from pathlib import Path

import pytest

from openxp.metrics import (
    MetricDefinition,
    MetricRegistry,
    MetricValidationError,
    load_all_metrics,
    load_metric,
    to_test_function,
    validate,
)
from openxp.stats.ab_tests import proportion_test, ratio_metric_test, welch_test

REPO_ROOT = Path(__file__).resolve().parents[1]
METRICS_DIR = REPO_ROOT / "metrics"

EXAMPLE_FILES = [
    "checkout_completion_rate.yaml",
    "session_revenue.yaml",
    "revenue_per_session.yaml",
    "d7_retention.yaml",
    "bounce_rate.yaml",
]


# ---------------------------------------------------------------------------
# YAML loading
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filename", EXAMPLE_FILES)
def test_load_each_example_yaml_parses(filename: str) -> None:
    md = load_metric(METRICS_DIR / filename)
    assert isinstance(md, MetricDefinition)
    assert md.name == filename.replace(".yaml", "")
    assert md.description
    assert md.numerator


def test_checkout_completion_rate_is_proportion() -> None:
    md = load_metric(METRICS_DIR / "checkout_completion_rate.yaml")
    assert md.type == "proportion"
    assert md.invert is False
    assert md.denominator is None


def test_session_revenue_is_mean_with_winsorization() -> None:
    md = load_metric(METRICS_DIR / "session_revenue.yaml")
    assert md.type == "mean"
    assert md.winsorize is True
    assert md.winsorize_bounds == (0.01, 0.99)


def test_revenue_per_session_is_ratio_with_denominator() -> None:
    md = load_metric(METRICS_DIR / "revenue_per_session.yaml")
    assert md.type == "ratio"
    assert md.denominator == "sessions"


def test_bounce_rate_is_inverted() -> None:
    md = load_metric(METRICS_DIR / "bounce_rate.yaml")
    assert md.type == "proportion"
    assert md.invert is True


# ---------------------------------------------------------------------------
# Registry behavior
# ---------------------------------------------------------------------------

def test_registry_register_get_list_roundtrip() -> None:
    registry = MetricRegistry(metrics_dir=None, autoload=False)
    md = MetricDefinition(
        name="dummy_rate",
        type="proportion",
        numerator="converted",
        description="test metric",
    )
    registry.register(md)
    assert "dummy_rate" in registry
    assert registry.get("dummy_rate") is md
    assert registry.list() == ["dummy_rate"]
    assert len(registry) == 1


def test_registry_get_missing_raises_keyerror() -> None:
    registry = MetricRegistry(metrics_dir=None, autoload=False)
    with pytest.raises(KeyError):
        registry.get("no_such_metric")


def test_registry_register_rejects_non_metric() -> None:
    registry = MetricRegistry(metrics_dir=None, autoload=False)
    with pytest.raises(TypeError):
        registry.register({"name": "nope"})  # type: ignore[arg-type]


def test_load_from_directory_scans_all_files() -> None:
    registry = MetricRegistry(metrics_dir=None, autoload=False)
    registry.load_from_directory(METRICS_DIR)
    names = registry.list()
    for filename in EXAMPLE_FILES:
        assert filename.replace(".yaml", "") in names
    assert len(names) >= len(EXAMPLE_FILES)


def test_load_all_metrics_convenience() -> None:
    registry = load_all_metrics(METRICS_DIR)
    assert isinstance(registry, MetricRegistry)
    assert "checkout_completion_rate" in registry


# ---------------------------------------------------------------------------
# to_test_function dispatch
# ---------------------------------------------------------------------------

def test_to_test_function_proportion_returns_proportion_test() -> None:
    md = load_metric(METRICS_DIR / "checkout_completion_rate.yaml")
    assert to_test_function(md) is proportion_test


def test_to_test_function_mean_returns_welch_test() -> None:
    md = load_metric(METRICS_DIR / "session_revenue.yaml")
    assert to_test_function(md) is welch_test


def test_to_test_function_ratio_returns_ratio_metric_test() -> None:
    md = load_metric(METRICS_DIR / "revenue_per_session.yaml")
    assert to_test_function(md) is ratio_metric_test


# ---------------------------------------------------------------------------
# Validation error paths
# ---------------------------------------------------------------------------

def _base_valid_dict() -> dict:
    return {
        "name": "test_metric",
        "type": "proportion",
        "numerator": "converted",
        "description": "A test metric.",
    }


def test_invalid_metric_type_raises() -> None:
    bad = _base_valid_dict()
    bad["type"] = "histogram"
    with pytest.raises(MetricValidationError, match="invalid metric type"):
        validate(bad)


def test_missing_required_field_raises_with_clear_message() -> None:
    bad = _base_valid_dict()
    del bad["numerator"]
    with pytest.raises(MetricValidationError, match="missing required field 'numerator'"):
        validate(bad)


def test_missing_description_raises() -> None:
    bad = _base_valid_dict()
    del bad["description"]
    with pytest.raises(MetricValidationError, match="missing required field 'description'"):
        validate(bad)


def test_ratio_without_denominator_raises() -> None:
    bad = _base_valid_dict()
    bad["type"] = "ratio"
    with pytest.raises(MetricValidationError, match="denominator"):
        validate(bad)


def test_winsorize_bounds_lower_must_be_less_than_upper() -> None:
    bad = _base_valid_dict()
    bad["winsorize_bounds"] = [0.9, 0.1]
    with pytest.raises(MetricValidationError, match="strictly less than"):
        validate(bad)


def test_winsorize_bounds_must_be_within_unit_interval() -> None:
    bad = _base_valid_dict()
    bad["winsorize_bounds"] = [-0.1, 0.99]
    with pytest.raises(MetricValidationError, match=r"\[0, 1\]"):
        validate(bad)

    bad2 = _base_valid_dict()
    bad2["winsorize_bounds"] = [0.01, 1.5]
    with pytest.raises(MetricValidationError, match=r"\[0, 1\]"):
        validate(bad2)


def test_baseline_range_must_be_ordered() -> None:
    bad = _base_valid_dict()
    bad["baseline_range"] = [0.9, 0.1]
    with pytest.raises(MetricValidationError, match="baseline_range"):
        validate(bad)


def test_validate_accepts_wrapped_yaml_form() -> None:
    wrapped = {"metric": _base_valid_dict()}
    md = validate(wrapped)
    assert md.name == "test_metric"


def test_validate_rejects_non_dict() -> None:
    with pytest.raises(MetricValidationError):
        validate("not a dict")  # type: ignore[arg-type]


def test_tags_must_be_list() -> None:
    bad = _base_valid_dict()
    bad["tags"] = "conversion,checkout"
    with pytest.raises(MetricValidationError, match="tags"):
        validate(bad)
