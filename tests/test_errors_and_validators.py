"""Tests for openxp.errors and openxp.validators (W11).

Covers:
  - OpenXPError envelope: __str__, to_dict, severity validation, subclasses
  - Error code registry: all declared codes have message/hint templates
  - Experiment validator: happy path, missing fields, bad types,
    cross-field rules (allocation sum, primary_metric in metrics list,
    lifecycle_state validity)
  - Metric validator: happy path + wrapping of MetricValidationError
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from openxp.errors import (
    DataError,
    LifecycleError,
    OpenXPError,
    StatsError,
    StorageError,
    ValidationError,
    codes,
)
from openxp.validators import (
    ValidationReport,
    validate_experiment_yaml,
    validate_metric_yaml,
)


# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent


def _valid_experiment() -> dict:
    """A fully-populated experiment dict that should validate cleanly."""
    return {
        "id": "checkout-redesign-2026q1",
        "name": "Checkout redesign — Q1 2026",
        "lifecycle_state": "DESIGNING",
        "hypothesis": {
            "action": "Simplify checkout to one page",
            "metric": "checkout_rate",
            "direction": "increase",
            "magnitude": "5% relative lift",
            "mechanism": "Fewer form fields reduces abandonment",
        },
        "metrics": {
            "primary": {
                "name": "checkout_rate",
                "type": "proportion",
                "definition": "orders / sessions",
                "mde": 0.05,
                "baseline": 0.12,
            },
            "secondary": [
                {"name": "add_to_cart_rate", "type": "proportion", "definition": "atc/sessions"}
            ],
            "guardrail": [
                {
                    "name": "p95_latency_ms",
                    "type": "continuous",
                    "threshold": 2500,
                    "direction": "do_not_increase",
                    "definition": "p95 server latency",
                }
            ],
        },
        "primary_metric": "checkout_rate",
        "success_criteria": "Primary metric significant positive, no guardrail violations",
        "power": {
            "alpha": 0.05,
            "power": 0.80,
            "baseline": 0.12,
            "mde": 0.05,
            "duration": 14,
        },
        "variants": [
            {"name": "control", "allocation": 0.5, "is_control": True},
            {"name": "treatment", "allocation": 0.5, "is_control": False},
        ],
    }


def _valid_metric() -> dict:
    return {
        "name": "checkout_rate",
        "type": "proportion",
        "numerator": "orders",
        "description": "Fraction of sessions that complete checkout.",
        "unit": "user_id",
        "baseline_range": [0.05, 0.20],
    }


# ---------------------------------------------------------------------
# OpenXPError envelope
# ---------------------------------------------------------------------

def test_openxp_error_basic_fields():
    err = OpenXPError(
        code=codes.E_SRM_DETECTED,
        message="SRM detected (p=0.0001)",
        hint="Investigate bot filtering.",
        severity="error",
        details={"p_value": 0.0001},
    )
    assert err.code == codes.E_SRM_DETECTED
    assert "SRM detected" in err.message
    assert err.severity == "error"
    assert err.details == {"p_value": 0.0001}


def test_openxp_error_str_format_includes_code_and_hint():
    err = OpenXPError(
        code="E_TEST",
        message="something broke",
        hint="do the thing",
    )
    s = str(err)
    assert s.startswith("[E_TEST]")
    assert "something broke" in s
    assert "hint: do the thing" in s


def test_openxp_error_to_dict_is_json_serializable():
    import json

    err = ValidationError(
        code=codes.E_MISSING_FIELD,
        message="missing 'id'",
        hint="add an id",
        details={"field": "id"},
    )
    d = err.to_dict()
    assert d["type"] == "ValidationError"
    assert d["code"] == codes.E_MISSING_FIELD
    assert d["severity"] == "error"
    # Round-trips cleanly through json.
    blob = json.dumps(d)
    assert codes.E_MISSING_FIELD in blob


def test_openxp_error_rejects_invalid_severity():
    with pytest.raises(ValueError):
        OpenXPError(code="E_TEST", message="x", hint="y", severity="catastrophic")  # type: ignore[arg-type]


def test_openxp_error_rejects_empty_code_or_message():
    with pytest.raises(ValueError):
        OpenXPError(code="", message="msg")
    with pytest.raises(ValueError):
        OpenXPError(code="E_TEST", message="")


def test_error_subclasses_are_openxp_errors():
    for cls in (ValidationError, DataError, StatsError, StorageError, LifecycleError):
        err = cls(code="E_TEST", message="m", hint="h")
        assert isinstance(err, OpenXPError)
        assert isinstance(err, Exception)
        # Subclasses must remain distinct so callers can except on one.
        assert cls.__name__ != "OpenXPError"


def test_error_codes_all_have_message_and_hint_templates():
    for code in codes.ALL_CODES:
        assert code in codes.MESSAGES, f"{code} missing from MESSAGES"
        assert code in codes.HINTS, f"{code} missing from HINTS"
        assert codes.MESSAGES[code]
        assert codes.HINTS[code]


def test_error_codes_message_and_hint_helpers_format_placeholders():
    msg = codes.message_for(codes.E_MISSING_FIELD, field="hypothesis")
    hint = codes.hint_for(codes.E_MISSING_FIELD, field="hypothesis")
    assert "hypothesis" in msg
    assert "hypothesis" in hint


# ---------------------------------------------------------------------
# Experiment validator — happy path
# ---------------------------------------------------------------------

def test_valid_experiment_returns_ok():
    report = validate_experiment_yaml(_valid_experiment())
    assert isinstance(report, ValidationReport)
    assert report.ok, f"expected ok=True, got findings: {report.all_messages()}"
    assert report.findings == []


def test_template_experiment_yaml_file_loads_without_crash():
    template = REPO_ROOT / "templates" / "experiment.yaml"
    assert template.exists(), f"template not found at {template}"
    # Validator must not crash on the skeleton; the skeleton is not
    # expected to pass (empty strings everywhere), so we only assert
    # that the result is a ValidationReport and findings are all
    # structured ValidationErrors.
    report = validate_experiment_yaml(template)
    assert isinstance(report, ValidationReport)
    for f in report.findings:
        assert isinstance(f, ValidationError)
        assert f.code.startswith("E_")
        assert f.hint  # every finding carries a hint


def test_valid_experiment_from_yaml_string_round_trip():
    yaml_text = yaml.safe_dump({"experiment": _valid_experiment()})
    report = validate_experiment_yaml(yaml_text)
    assert report.ok, report.all_messages()


# ---------------------------------------------------------------------
# Experiment validator — missing fields
# ---------------------------------------------------------------------

def test_missing_id_emits_missing_field_finding():
    cfg = _valid_experiment()
    del cfg["id"]
    report = validate_experiment_yaml(cfg)
    assert not report.ok
    codes_seen = {f.code for f in report.findings}
    assert codes.E_MISSING_FIELD in codes_seen
    assert any("id" in (f.details.get("field") or "") for f in report.findings)


def test_missing_hypothesis_emits_missing_field_finding():
    cfg = _valid_experiment()
    del cfg["hypothesis"]
    report = validate_experiment_yaml(cfg)
    assert not report.ok
    assert any(
        f.code == codes.E_MISSING_FIELD and f.details.get("field") == "hypothesis"
        for f in report.findings
    )


def test_validator_collects_multiple_findings_not_first():
    cfg = _valid_experiment()
    del cfg["id"]
    del cfg["name"]
    del cfg["hypothesis"]
    report = validate_experiment_yaml(cfg)
    assert not report.ok
    fields_missing = {f.details.get("field") for f in report.findings}
    assert {"id", "name", "hypothesis"}.issubset(fields_missing)


# ---------------------------------------------------------------------
# Experiment validator — bad types and semantic checks
# ---------------------------------------------------------------------

def test_bad_allocation_sum_emits_schema_invalid():
    cfg = _valid_experiment()
    cfg["variants"] = [
        {"name": "control", "allocation": 0.4, "is_control": True},
        {"name": "treatment", "allocation": 0.4, "is_control": False},
    ]
    report = validate_experiment_yaml(cfg)
    assert not report.ok
    assert any(f.code == codes.E_SCHEMA_INVALID for f in report.findings)
    assert any("sum" in f.message.lower() for f in report.findings)


def test_allocation_sum_within_tolerance_ok():
    cfg = _valid_experiment()
    cfg["variants"] = [
        {"name": "control", "allocation": 0.5005, "is_control": True},
        {"name": "treatment", "allocation": 0.4995, "is_control": False},
    ]
    report = validate_experiment_yaml(cfg)
    assert report.ok, report.all_messages()


def test_single_variant_fails():
    cfg = _valid_experiment()
    cfg["variants"] = [{"name": "control", "allocation": 1.0, "is_control": True}]
    report = validate_experiment_yaml(cfg)
    assert not report.ok
    assert any(
        f.code == codes.E_SCHEMA_INVALID and "2 variants" in f.message
        for f in report.findings
    )


def test_invalid_lifecycle_state_emits_lifecycle_skip():
    cfg = _valid_experiment()
    cfg["lifecycle_state"] = "HALLUCINATING"
    report = validate_experiment_yaml(cfg)
    assert not report.ok
    assert any(f.code == codes.E_LIFECYCLE_SKIP for f in report.findings)


def test_primary_metric_not_in_metrics_list_fails():
    cfg = _valid_experiment()
    cfg["primary_metric"] = "nonexistent_metric"
    report = validate_experiment_yaml(cfg)
    assert not report.ok
    assert any(
        f.code == codes.E_SCHEMA_INVALID and "primary_metric" in f.message
        for f in report.findings
    )


def test_bad_mde_out_of_range_fails():
    cfg = _valid_experiment()
    cfg["power"]["mde"] = 1.5  # > 1
    report = validate_experiment_yaml(cfg)
    assert not report.ok
    assert any(
        f.code == codes.E_SCHEMA_INVALID and "mde" in f.message for f in report.findings
    )


def test_bad_alpha_out_of_range_fails():
    cfg = _valid_experiment()
    cfg["power"]["alpha"] = 0.9
    report = validate_experiment_yaml(cfg)
    assert not report.ok
    assert any(
        f.code == codes.E_SCHEMA_INVALID and "alpha" in f.message for f in report.findings
    )


def test_bad_power_out_of_range_fails():
    cfg = _valid_experiment()
    cfg["power"]["power"] = 0.2
    report = validate_experiment_yaml(cfg)
    assert not report.ok
    assert any(
        f.code == codes.E_SCHEMA_INVALID and "power" in f.message for f in report.findings
    )


def test_bad_type_on_id_emits_bad_type():
    cfg = _valid_experiment()
    cfg["id"] = 12345
    report = validate_experiment_yaml(cfg)
    assert not report.ok
    assert any(f.code == codes.E_BAD_TYPE for f in report.findings)


def test_missing_power_block_emits_missing_field():
    cfg = _valid_experiment()
    del cfg["power"]
    report = validate_experiment_yaml(cfg)
    assert not report.ok
    assert any(
        f.code == codes.E_MISSING_FIELD and f.details.get("field") == "power"
        for f in report.findings
    )


def test_validator_accepts_path(tmp_path: Path):
    cfg = _valid_experiment()
    p = tmp_path / "experiment.yaml"
    p.write_text(yaml.safe_dump({"experiment": cfg}), encoding="utf-8")
    report = validate_experiment_yaml(p)
    assert report.ok, report.all_messages()


def test_validator_reports_every_finding_has_hint():
    cfg = _valid_experiment()
    del cfg["id"]
    cfg["variants"] = [{"name": "control", "allocation": 0.4, "is_control": True}]
    cfg["lifecycle_state"] = "WEIRD"
    report = validate_experiment_yaml(cfg)
    assert not report.ok
    for f in report.findings:
        assert f.hint, f"finding {f.code} missing hint"
        assert f.code.startswith("E_")


# ---------------------------------------------------------------------
# Metric validator
# ---------------------------------------------------------------------

def test_valid_metric_yaml_returns_ok():
    report = validate_metric_yaml(_valid_metric())
    assert isinstance(report, ValidationReport)
    assert report.ok, report.all_messages()


def test_invalid_metric_yaml_wraps_schema_invalid():
    bad = copy.deepcopy(_valid_metric())
    del bad["numerator"]
    report = validate_metric_yaml(bad)
    assert not report.ok
    assert len(report.findings) == 1
    assert report.findings[0].code == codes.E_SCHEMA_INVALID
    assert "numerator" in report.findings[0].details.get("underlying", "")


def test_metric_validator_accepts_path(tmp_path: Path):
    p = tmp_path / "metric.yaml"
    p.write_text(yaml.safe_dump(_valid_metric()), encoding="utf-8")
    report = validate_metric_yaml(p)
    assert report.ok, report.all_messages()


def test_metric_validator_handles_bad_yaml_string():
    report = validate_metric_yaml("::: not valid yaml :::")
    # Either parsed as a degenerate dict or raised a schema error; either way,
    # not ok and exactly one structured finding.
    assert not report.ok
    assert all(isinstance(f, ValidationError) for f in report.findings)
