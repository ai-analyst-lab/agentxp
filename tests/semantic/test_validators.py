"""Tests for ``agentxp.semantic.validators``.

Covers happy-path validation, ``extra='forbid'`` rejection of unknown keys,
and the cross-field invariants for each YAML shape per §8.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentxp.semantic.validators import (
    AssignmentYAML,
    FactSource,
    MetricYAML,
    SemanticModel,
)


# ─────────────────────────────────────────────────────────────────────────
# Reusable fixtures
# ─────────────────────────────────────────────────────────────────────────


def _semantic_model_payload() -> dict:
    """T70-RECONCILE: payload matches the on-disk YAML format every
    experiment dir in the repo uses (dbt/Looker-shaped primary_key /
    source_table / dimensions / relationships / outcome_columns rather
    than the pre-T70 entity + fields[] + role taxonomy).
    """
    return {
        "schema_version": 1,
        "name": "user_events",
        "display_name": "User Events",
        "description": "User-level event facts.",
        "primary_key": "user_id",
        "source_table": "user_events",
        "dimensions": [
            {"name": "user_id", "type": "integer", "description": "Stable user id."},
            {"name": "event_ts", "type": "timestamp", "description": "Event timestamp."},
            {"name": "country", "type": "string",
             "description": "User country.",
             "enum": ["US", "GB", "DE"]},
        ],
        "relationships": [
            {"to": "session", "join_on": "session_id",
             "type": "many_to_one", "description": "Each event belongs to a session."},
        ],
        "outcome_columns": [],
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
    assert sm.primary_key == "user_id"
    assert len(sm.dimensions) == 3
    assert len(sm.relationships) == 1
    assert sm.outcome_columns == []


def test_semantic_model_rejects_unknown_field():
    payload = _semantic_model_payload()
    payload["unexpected_key"] = "boom"
    with pytest.raises(ValidationError, match="unexpected_key"):
        SemanticModel.model_validate(payload)


def test_semantic_model_warns_on_primary_key_not_in_dimensions():
    """Audit item #5 — was a hard raise, softened to UserWarning so the
    schema does not impose redundancy on YAML authors."""
    import warnings
    payload = _semantic_model_payload()
    payload["primary_key"] = "ghost_id"
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        SemanticModel.model_validate(payload)
    assert any("ghost_id" in str(w.message) for w in caught), (
        f"expected UserWarning naming ghost_id; got {[str(w.message) for w in caught]}"
    )


def test_semantic_model_accepts_compound_primary_key():
    payload = _semantic_model_payload()
    # Add session_id as a dimension and use the compound key shape.
    payload["dimensions"].append(
        {"name": "session_id", "type": "integer", "description": "Session id."}
    )
    payload["primary_key"] = ["user_id", "session_id"]
    sm = SemanticModel.model_validate(payload)
    assert sm.primary_key == ["user_id", "session_id"]


def test_semantic_model_outcome_columns_required():
    payload = _semantic_model_payload()
    del payload["outcome_columns"]
    with pytest.raises(ValidationError, match="outcome_columns"):
        SemanticModel.model_validate(payload)


def test_semantic_model_accepts_outcome_columns_declaration():
    payload = _semantic_model_payload()
    payload["outcome_columns"] = ["arm"]
    sm = SemanticModel.model_validate(payload)
    assert sm.outcome_columns == ["arm"]


def test_semantic_model_dimension_enum_optional():
    payload = _semantic_model_payload()
    # The country dimension already carries an enum; drop it and confirm OK.
    for d in payload["dimensions"]:
        d.pop("enum", None)
    sm = SemanticModel.model_validate(payload)
    assert all(d.enum is None for d in sm.dimensions)


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


def test_relationship_uses_join_on_not_on():
    """The pre-T70 spec used ``on:`` for the join column, but PyYAML 1.1
    parses bare ``on`` as the boolean True. ``join_on`` sidesteps the
    quirk."""
    payload = _semantic_model_payload()
    sm = SemanticModel.model_validate(payload)
    assert sm.relationships[0].join_on == "session_id"


def test_semantic_model_admits_every_on_disk_yaml():
    """Repo-wide invariant: every shipped semantic_models/*.yaml loads
    cleanly through the canonical schema."""
    import yaml as _yaml
    from pathlib import Path as _Path
    repo = _Path(__file__).resolve().parents[2]
    paths = sorted((repo / "semantic_models").glob("*.yaml"))
    paths = [p for p in paths if not p.stem.startswith("_")]
    assert paths, "no on-disk semantic models found"
    for p in paths:
        raw = _yaml.safe_load(p.read_text())
        # If T70 broke compatibility, this raises.
        SemanticModel.model_validate(raw)


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
