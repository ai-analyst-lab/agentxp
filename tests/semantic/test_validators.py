"""Tests for ``openxp.semantic.validators``.

Covers happy-path validation, ``extra='forbid'`` rejection of unknown keys,
and the cross-field invariants for each YAML shape per §8.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from openxp.semantic.validators import (
    AssignmentYAML,
    FactSource,
    MetricYAML,
    SemanticModel,
)


# ─────────────────────────────────────────────────────────────────────────
# Reusable fixtures
# ─────────────────────────────────────────────────────────────────────────


def _semantic_model_payload() -> dict:
    return {
        "schema_version": 1,
        "name": "user_events",
        "description": "User-level event facts.",
        "entity": {
            "primary": "user_id",
            "related": [{"name": "session_id", "type": "session"}],
        },
        "fields": [
            {"name": "user_id", "type": "string", "nullable": False, "role": "identifier"},
            {"name": "event_ts", "type": "timestamp", "nullable": False, "role": "event_time"},
            {"name": "country", "type": "string", "nullable": True, "role": "dimension",
             "levels": ["US", "GB", "DE"]},
        ],
    }


def _fact_source_payload() -> dict:
    return {
        "schema_version": 1,
        "name": "user_events",
        "semantic_model": "user_events",
        "source": {
            "resolved_to": "analytics.events.user_events",
            "adapter": "duckdb",
        },
        "time_column": "event_ts",
        "default_aggregation_grain": "day",
    }


def _ratio_metric_payload() -> dict:
    return {
        "schema_version": 2,
        "name": "checkout_conversion",
        "display_name": "Checkout Conversion",
        "description": "Checkouts / sessions.",
        "type": "ratio",
        "fact_source": "user_events",
        "numerator": {"expression": "SUM(checkout)"},
        "denominator": {"expression": "COUNT(DISTINCT session_id)"},
        "requires": [{"field": "checkout"}, {"field": "session_id"}],
        "guardrail": False,
        "direction": "higher_is_better",
        "mde_default_pct": 2.0,
    }


def _p95_metric_payload() -> dict:
    return {
        "schema_version": 2,
        "name": "page_load_p95",
        "display_name": "Page Load p95",
        "description": "95th percentile page load latency.",
        "type": "p95",
        "fact_source": "page_loads",
        "aggregation": {"expression": "PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY load_ms)"},
        "requires": [{"field": "load_ms"}],
        "guardrail": True,
        "direction": "lower_is_better",
        "mde_default_pct": 5.0,
    }


def _assignment_payload() -> dict:
    return {
        "schema_version": 1,
        "name": "checkout_redesign",
        "description": "Variant assignment for checkout redesign experiment.",
        "type": "inline",
        "variant_column": "variant",
        "fact_source": "user_events",
        "randomization_unit": "user_id",
        "exposed_filter": "event_name = 'checkout_view'",
    }


# ─────────────────────────────────────────────────────────────────────────
# SemanticModel
# ─────────────────────────────────────────────────────────────────────────


def test_semantic_model_happy_path():
    sm = SemanticModel.model_validate(_semantic_model_payload())
    assert sm.name == "user_events"
    assert sm.entity.primary == "user_id"
    assert len(sm.fields) == 3


def test_semantic_model_rejects_unknown_field():
    payload = _semantic_model_payload()
    payload["unexpected_key"] = "boom"
    with pytest.raises(ValidationError, match="unexpected_key"):
        SemanticModel.model_validate(payload)


def test_semantic_model_rejects_primary_not_in_fields():
    payload = _semantic_model_payload()
    payload["entity"]["primary"] = "ghost_id"
    with pytest.raises(ValidationError, match="ghost_id"):
        SemanticModel.model_validate(payload)


def test_semantic_model_rejects_primary_with_non_identifier_role():
    payload = _semantic_model_payload()
    # Point primary at the event_time field instead of the identifier.
    payload["entity"]["primary"] = "event_ts"
    with pytest.raises(ValidationError, match="identifier"):
        SemanticModel.model_validate(payload)


def test_semantic_model_rejects_multiple_event_time_fields():
    payload = _semantic_model_payload()
    payload["fields"].append(
        {"name": "ingested_ts", "type": "timestamp", "nullable": False, "role": "event_time"}
    )
    with pytest.raises(ValidationError, match="event_time"):
        SemanticModel.model_validate(payload)


def test_semantic_model_rejects_levels_on_non_dimension_field():
    payload = _semantic_model_payload()
    # Add levels to the identifier field — should be rejected.
    payload["fields"][0]["levels"] = ["a", "b"]
    with pytest.raises(ValidationError, match="dimension"):
        SemanticModel.model_validate(payload)


def test_semantic_model_rejects_uppercase_name():
    payload = _semantic_model_payload()
    payload["name"] = "UserEvents"
    with pytest.raises(ValidationError):
        SemanticModel.model_validate(payload)


def test_semantic_model_rejects_hyphen_in_name():
    payload = _semantic_model_payload()
    payload["name"] = "user-events"
    with pytest.raises(ValidationError):
        SemanticModel.model_validate(payload)


def test_semantic_model_rejects_wrong_schema_version():
    payload = _semantic_model_payload()
    payload["schema_version"] = 2
    with pytest.raises(ValidationError):
        SemanticModel.model_validate(payload)


# ─────────────────────────────────────────────────────────────────────────
# FactSource
# ─────────────────────────────────────────────────────────────────────────


def test_fact_source_happy_path():
    fs = FactSource.model_validate(_fact_source_payload())
    assert fs.source.adapter == "duckdb"
    assert fs.default_aggregation_grain == "day"


def test_fact_source_rejects_unknown_adapter():
    payload = _fact_source_payload()
    payload["source"]["adapter"] = "redshift"
    with pytest.raises(ValidationError):
        FactSource.model_validate(payload)


def test_fact_source_rejects_unknown_field():
    payload = _fact_source_payload()
    payload["random_key"] = 1
    with pytest.raises(ValidationError):
        FactSource.model_validate(payload)


# ─────────────────────────────────────────────────────────────────────────
# MetricYAML
# ─────────────────────────────────────────────────────────────────────────


def test_metric_ratio_happy_path():
    m = MetricYAML.model_validate(_ratio_metric_payload())
    assert m.type == "ratio"
    assert m.numerator is not None
    assert m.denominator is not None
    assert m.aggregation is None


def test_metric_ratio_rejects_missing_denominator():
    payload = _ratio_metric_payload()
    payload.pop("denominator")
    with pytest.raises(ValidationError, match="denominator"):
        MetricYAML.model_validate(payload)


def test_metric_ratio_rejects_with_aggregation():
    payload = _ratio_metric_payload()
    payload["aggregation"] = {"expression": "SUM(x)"}
    with pytest.raises(ValidationError, match="aggregation"):
        MetricYAML.model_validate(payload)


def test_metric_p95_happy_path():
    m = MetricYAML.model_validate(_p95_metric_payload())
    assert m.type == "p95"
    assert m.aggregation is not None
    assert m.numerator is None and m.denominator is None


def test_metric_non_ratio_rejects_numerator():
    payload = _p95_metric_payload()
    payload["numerator"] = {"expression": "SUM(x)"}
    with pytest.raises(ValidationError, match="numerator"):
        MetricYAML.model_validate(payload)


def test_metric_non_ratio_rejects_missing_aggregation():
    payload = _p95_metric_payload()
    payload.pop("aggregation")
    with pytest.raises(ValidationError, match="aggregation"):
        MetricYAML.model_validate(payload)


def test_metric_rejects_wrong_schema_version():
    payload = _ratio_metric_payload()
    payload["schema_version"] = 1
    with pytest.raises(ValidationError):
        MetricYAML.model_validate(payload)


def test_metric_rejects_bad_direction():
    payload = _ratio_metric_payload()
    payload["direction"] = "sideways"
    with pytest.raises(ValidationError):
        MetricYAML.model_validate(payload)


def test_metric_rejects_negative_mde():
    payload = _ratio_metric_payload()
    payload["mde_default_pct"] = -1.0
    with pytest.raises(ValidationError):
        MetricYAML.model_validate(payload)


# ─────────────────────────────────────────────────────────────────────────
# AssignmentYAML
# ─────────────────────────────────────────────────────────────────────────


def test_assignment_happy_path():
    a = AssignmentYAML.model_validate(_assignment_payload())
    assert a.type == "inline"
    assert a.randomization_unit == "user_id"


def test_assignment_rejects_unknown_type():
    payload = _assignment_payload()
    payload["type"] = "weird"
    with pytest.raises(ValidationError):
        AssignmentYAML.model_validate(payload)


def test_assignment_rejects_unknown_field():
    payload = _assignment_payload()
    payload["bogus"] = 1
    with pytest.raises(ValidationError):
        AssignmentYAML.model_validate(payload)
