"""Smoke tests for openxp.schemas.results Pydantic models.

These models are loose shadows of the plain dicts returned by
``openxp.stats`` functions. They exist so external callers and type checkers
have something to reference. The tests below construct each model from a
representative dict and assert round-trip via ``.model_dump()``.
"""

from __future__ import annotations

from openxp.schemas.results import (
    BayesianResult,
    CorrectionResult,
    CUPEDResult,
    DiagnosisResult,
    DurationResult,
    EffectSizeResult,
    ExtensionResult,
    LiftResult,
    MDEResult,
    MonitorReportModel,
    PowerResult,
    SensitivityTable,
    SequentialResult,
    SRMResult,
    TestResult,
)


def _round_trip(model_cls, data):
    inst = model_cls(**data)
    dumped = inst.model_dump()
    # Every input key must still be there after dump.
    for k, v in data.items():
        assert k in dumped, f"{model_cls.__name__} dropped key {k!r} on round-trip"
        assert dumped[k] == v, f"{model_cls.__name__} mismatched value for {k!r}"
    return inst


def test_test_result_round_trip():
    _round_trip(
        TestResult,
        {
            "test": "welch_t_test",
            "effect": 0.035,
            "p_value": 0.012,
            "significant": True,
            "ci_lower": 0.008,
            "ci_upper": 0.062,
            "n_control": 5000,
            "n_treatment": 5000,
            "alpha": 0.05,
            "decision": "SHIP",
            "interpretation": "Treatment beats control by 3.5%.",
            "computation_trace": {"formula_ref": "welch", "inputs": {}, "intermediate_values": {}, "timestamp": "2026-04-14T00:00:00Z"},
        },
    )


def test_power_result_round_trip():
    _round_trip(
        PowerResult,
        {
            "n_per_group": 24572,
            "total_n": 49144,
            "baseline": 0.08,
            "mde": 0.10,
            "alpha": 0.05,
            "power": 0.80,
            "viability": "VIABLE",
            "interpretation": "Need 24,572 per group.",
        },
    )


def test_duration_result_round_trip():
    _round_trip(
        DurationResult,
        {
            "days": 14,
            "weeks": 2.0,
            "n_required": 49144,
            "daily_enrollment": 3500.0,
            "viable": "VIABLE",
            "interpretation": "14 days to reach full sample.",
        },
    )


def test_mde_result_round_trip():
    _round_trip(
        MDEResult,
        {
            "detectable_effect": 0.045,
            "n_per_group": 10000,
            "baseline": 0.08,
            "alpha": 0.05,
            "power": 0.80,
            "interpretation": "At current n, detectable effect is 4.5%.",
        },
    )


def test_sensitivity_table_round_trip():
    _round_trip(
        SensitivityTable,
        {
            "rows": [
                {"mde": 0.05, "daily_traffic": 3500, "days": 28},
                {"mde": 0.10, "daily_traffic": 3500, "days": 7},
            ],
            "interpretation": "Trade-off between MDE and duration.",
        },
    )


def test_srm_result_round_trip():
    _round_trip(
        SRMResult,
        {
            "verdict": "PASS",
            "chi2": 0.04,
            "p_value": 0.84,
            "expected": [5000.0, 5000.0],
            "observed": [5012.0, 4988.0],
            "threshold": 0.0005,
            "interpretation": "Randomization is healthy.",
        },
    )


def test_diagnosis_result_round_trip():
    _round_trip(
        DiagnosisResult,
        {
            "worst_segment": "platform=ios",
            "segment_results": [
                {"segment": "platform=ios", "p_value": 0.0001, "ratio_observed": 0.47},
                {"segment": "platform=web", "p_value": 0.6, "ratio_observed": 0.50},
            ],
            "interpretation": "iOS segment is broken.",
        },
    )


def test_effect_size_result_round_trip():
    _round_trip(
        EffectSizeResult,
        {
            "value": 0.21,
            "d": 0.21,
            "magnitude": "Small",
            "interpretation": "Small effect (Cohen's d = 0.21).",
        },
    )


def test_lift_result_round_trip():
    _round_trip(
        LiftResult,
        {
            "absolute": 0.035,
            "relative": 0.10,
            "control_mean": 0.350,
            "treatment_mean": 0.385,
            "interpretation": "10% relative lift.",
        },
    )


def test_correction_result_round_trip():
    _round_trip(
        CorrectionResult,
        {
            "adjusted_pvalues": [0.025, 0.048, 0.120],
            "rejected": [True, True, False],
            "method": "holm",
            "alpha": 0.05,
            "interpretation": "Two of three secondary metrics survive correction.",
        },
    )


def test_cuped_result_round_trip():
    _round_trip(
        CUPEDResult,
        {
            "theta": 0.82,
            "variance_reduction_pct": 0.35,
            "adjusted_effect": 0.034,
            "effect": 0.035,
            "p_value": 0.004,
            "ci_lower": 0.010,
            "ci_upper": 0.058,
            "interpretation": "CUPED cut variance by 35%.",
        },
    )


def test_sequential_result_round_trip():
    _round_trip(
        SequentialResult,
        {
            "statistic": 2.15,
            "always_valid_lower": 0.002,
            "always_valid_upper": 0.068,
            "decision": "CONTINUE",
            "interpretation": "Always-valid CI excludes zero — stop for efficacy.",
        },
    )


def test_bayesian_result_round_trip():
    _round_trip(
        BayesianResult,
        {
            "p_to_beat": 0.97,
            "credible_lower": 0.008,
            "credible_upper": 0.065,
            "expected_loss": 0.001,
            "decision": "SHIP",
            "interpretation": "97% probability treatment beats control.",
        },
    )


def test_extension_result_round_trip():
    _round_trip(
        ExtensionResult,
        {
            "additional_days": 7,
            "additional_n": 24500,
            "revised_mde": 0.04,
            "viable": True,
            "interpretation": "Extend 7 more days to reach power.",
        },
    )


def test_monitor_report_model_round_trip():
    _round_trip(
        MonitorReportModel,
        {
            "status": "GREEN",
            "checks": {
                "srm": {"status": "GREEN", "p_value": 0.84},
                "guardrails": {"status": "GREEN"},
                "sample_accumulation": {"status": "GREEN", "pct": 0.62},
            },
            "recommendations": ["Continue collecting."],
            "timestamp": "2026-04-14T00:00:00Z",
            "persistence_error": None,
            "interpretation": "Experiment is healthy.",
        },
    )


def test_models_allow_extra_keys():
    # Stats functions may return extra keys; models must not blow up.
    inst = TestResult(
        test="welch_t_test",
        p_value=0.01,
        some_future_key="future-value",
        extra_diagnostic={"nested": 1},
    )
    dumped = inst.model_dump()
    assert dumped["some_future_key"] == "future-value"
    assert dumped["extra_diagnostic"] == {"nested": 1}


def test_models_allow_empty_construction():
    # Every field is optional — default construction must succeed.
    for cls in [
        TestResult,
        PowerResult,
        DurationResult,
        MDEResult,
        SensitivityTable,
        SRMResult,
        DiagnosisResult,
        EffectSizeResult,
        LiftResult,
        CorrectionResult,
        CUPEDResult,
        SequentialResult,
        BayesianResult,
        ExtensionResult,
        MonitorReportModel,
    ]:
        inst = cls()
        assert inst.model_dump() is not None
