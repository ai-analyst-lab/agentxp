"""
Tests for openxp.monitoring — srm_trend, guardrail_health, sample_accumulation,
and the run_monitor orchestrator.

Data is synthesized in-test so these tests do not depend on any sample-data
CSVs. The numpy seed is pinned per-test for reproducibility.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from openxp.monitoring import (
    MonitorReport,
    guardrail_health,
    run_monitor,
    sample_accumulation,
    srm_trend,
)
from openxp.storage import ExperimentStore


# --------------------------------------------------------------------- helpers


def _make_clean_srm_df(
    days: int = 14, per_day: int = 1000, seed: int = 0
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for d in range(days):
        ts = start + timedelta(days=d)
        variants = rng.choice(
            ["control", "treatment"], size=per_day, p=[0.5, 0.5]
        )
        for v in variants:
            rows.append({"timestamp": ts, "variant": v})
    return pd.DataFrame(rows)


def _make_drift_srm_df(
    days: int = 14, per_day: int = 1000, break_day: int = 7, seed: int = 1
) -> pd.DataFrame:
    """Early days 50/50, after break_day treatment drops to ~30%."""
    rng = np.random.default_rng(seed)
    rows = []
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for d in range(days):
        ts = start + timedelta(days=d)
        if d < break_day:
            p = [0.5, 0.5]
        else:
            p = [0.7, 0.3]
        variants = rng.choice(["control", "treatment"], size=per_day, p=p)
        for v in variants:
            rows.append({"timestamp": ts, "variant": v})
    return pd.DataFrame(rows)


def _make_guardrail_df(
    n_per_arm: int = 800, treatment_effect: float = 0.0, seed: int = 2
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    control_latency = rng.normal(loc=500.0, scale=50.0, size=n_per_arm)
    treatment_latency = rng.normal(
        loc=500.0 + treatment_effect, scale=50.0, size=n_per_arm
    )
    control_conv = rng.binomial(1, 0.20, size=n_per_arm)
    treatment_conv = rng.binomial(1, 0.20, size=n_per_arm)
    rows = []
    for v, lat, conv in zip(
        ["control"] * n_per_arm, control_latency, control_conv
    ):
        rows.append({"variant": v, "latency_ms": lat, "converted": conv})
    for v, lat, conv in zip(
        ["treatment"] * n_per_arm, treatment_latency, treatment_conv
    ):
        rows.append({"variant": v, "latency_ms": lat, "converted": conv})
    return pd.DataFrame(rows)


# ====================================================================== tests

# ------------------- srm_trend --------------------------------------------- #


def test_srm_trend_clean_data_returns_pass():
    # Clean 50/50 data — no window should BLOCK (p below 0.0005). Occasional
    # WARNING is possible from random noise across 14 windows, so we assert
    # no BLOCK and no persistent violations rather than strict PASS.
    df = _make_clean_srm_df(days=14, per_day=2000, seed=7)
    result = srm_trend(
        df,
        treatment_col="variant",
        timestamp_col="timestamp",
        window="1d",
        threshold=0.0005,
    )
    assert result["test"] == "srm_trend"
    assert result["verdict"] != "BLOCK"
    assert result["n_windows"] == 14
    # Consecutive tail-violations should be small for clean data.
    assert result["consecutive_violations"] <= 2


def test_srm_trend_mid_experiment_bug_detected():
    df = _make_drift_srm_df(days=14, break_day=7)
    result = srm_trend(
        df,
        treatment_col="variant",
        timestamp_col="timestamp",
        window="1d",
        threshold=0.0005,
    )
    assert result["verdict"] == "BLOCK"
    assert result["first_violation_timestamp"] is not None
    # Consecutive violations should cover all post-break days (up to 7).
    assert result["consecutive_violations"] >= 5
    # Should be flagged as worsening since early half is clean.
    assert result["trend_direction"] in ("worsening", "stable")


def test_srm_trend_missing_treatment_column_returns_block():
    df = pd.DataFrame(
        {"variant": ["control", "treatment"], "timestamp": [1, 2]}
    )
    result = srm_trend(
        df, treatment_col="missing", timestamp_col="timestamp"
    )
    assert result["verdict"] == "BLOCK"
    assert "error" in result


def test_srm_trend_missing_timestamp_column_returns_block():
    df = pd.DataFrame({"variant": ["control", "treatment"]})
    result = srm_trend(
        df, treatment_col="variant", timestamp_col="ts"
    )
    assert result["verdict"] == "BLOCK"
    assert "error" in result


def test_srm_trend_empty_df_returns_block():
    df = pd.DataFrame(columns=["variant", "timestamp"])
    result = srm_trend(
        df, treatment_col="variant", timestamp_col="timestamp"
    )
    assert result["verdict"] == "BLOCK"


# ------------------- guardrail_health -------------------------------------- #


def test_guardrail_health_clean_metric_returns_pass():
    df = _make_guardrail_df(treatment_effect=0.0)
    result = guardrail_health(
        df,
        treatment_col="variant",
        guardrail_metrics=["latency_ms"],
        thresholds={
            "latency_ms": {
                "nim": 0.02,
                "direction": "increase",
                "type": "continuous",
            }
        },
    )
    assert result["verdict"] == "PASS"
    assert result["per_metric"]["latency_ms"]["verdict"] == "PASS"
    assert result["flagged_metrics"] == []


def test_guardrail_health_degraded_metric_blocks():
    # Huge positive shift in latency — >> 2% of baseline (500ms).
    df = _make_guardrail_df(treatment_effect=80.0, n_per_arm=1500)
    result = guardrail_health(
        df,
        treatment_col="variant",
        guardrail_metrics=["latency_ms"],
        thresholds={
            "latency_ms": {
                "nim": 0.02,  # 2% = 10ms tolerance
                "direction": "increase",
                "type": "continuous",
            }
        },
    )
    assert result["verdict"] == "BLOCK"
    assert "latency_ms" in result["flagged_metrics"]


def test_guardrail_health_binary_metric_supported():
    df = _make_guardrail_df(n_per_arm=1000)
    # NIM of 50% of baseline (=10 percentage points tolerance on a 20%
    # baseline) easily covers the ~3pp noise band from 1000/arm, so the
    # guardrail should hold for a genuinely null difference.
    result = guardrail_health(
        df,
        treatment_col="variant",
        guardrail_metrics=["converted"],
        thresholds={
            "converted": {
                "nim": 0.50,
                "direction": "decrease",
                "type": "binary",
            }
        },
    )
    assert result["verdict"] == "PASS"
    assert result["per_metric"]["converted"]["verdict"] == "PASS"


def test_guardrail_health_missing_column_warns():
    df = _make_guardrail_df()
    result = guardrail_health(
        df,
        treatment_col="variant",
        guardrail_metrics=["nonexistent"],
        thresholds={"nonexistent": {"nim": 0.05, "direction": "decrease"}},
    )
    assert result["verdict"] == "WARNING"
    assert "nonexistent" in result["flagged_metrics"]


def test_guardrail_health_no_metrics_passes_noop():
    df = _make_guardrail_df()
    result = guardrail_health(
        df,
        treatment_col="variant",
        guardrail_metrics=[],
        thresholds={},
    )
    assert result["verdict"] == "PASS"
    assert result["per_metric"] == {}


# ------------------- sample_accumulation ----------------------------------- #


def test_sample_accumulation_on_pace_green():
    result = sample_accumulation(
        current_n=5000,
        required_n=10000,
        daily_traffic=500,
        days_elapsed=10,
        planned_duration_days=20,
    )
    assert result["verdict"] == "PASS"
    assert result["traffic_light"] == "GREEN"
    assert result["on_pace"] is True
    assert result["projected_completion"] is not None


def test_sample_accumulation_slow_yellow():
    # 50% of planned pace — expected 0.75, actual 0.5 → ratio ~0.67 → YELLOW
    result = sample_accumulation(
        current_n=5000,
        required_n=10000,
        daily_traffic=333,
        days_elapsed=15,
        planned_duration_days=20,
    )
    assert result["verdict"] == "WARNING"
    assert result["traffic_light"] == "YELLOW"
    assert result["on_pace"] is False


def test_sample_accumulation_stalled_red():
    result = sample_accumulation(
        current_n=1000,
        required_n=10000,
        daily_traffic=0,
        days_elapsed=5,
        planned_duration_days=20,
    )
    assert result["verdict"] == "BLOCK"
    assert result["traffic_light"] == "RED"
    assert result["on_pace"] is False


def test_sample_accumulation_severely_behind_red():
    # Expected ~0.90, actual 0.20 → ratio ~0.22 → RED
    result = sample_accumulation(
        current_n=2000,
        required_n=10000,
        daily_traffic=111,
        days_elapsed=18,
        planned_duration_days=20,
    )
    assert result["verdict"] == "BLOCK"
    assert result["traffic_light"] == "RED"


def test_sample_accumulation_complete_returns_green():
    result = sample_accumulation(
        current_n=10500,
        required_n=10000,
        daily_traffic=500,
        days_elapsed=20,
        planned_duration_days=20,
    )
    assert result["verdict"] == "PASS"
    assert result["traffic_light"] == "GREEN"
    assert result["fraction_complete"] >= 1.0


def test_sample_accumulation_invalid_required_n_blocks():
    result = sample_accumulation(
        current_n=0, required_n=0, daily_traffic=10, days_elapsed=1
    )
    assert result["verdict"] == "BLOCK"


# ------------------- run_monitor ------------------------------------------- #


def _monitor_context(df, required_n=2000, daily_traffic=200, days_elapsed=10):
    return {
        "df": df,
        "treatment_col": "variant",
        "timestamp_col": None,
        "guardrail_metrics": ["latency_ms"],
        "thresholds": {
            "latency_ms": {
                "nim": 0.02,
                "direction": "increase",
                "type": "continuous",
            }
        },
        "required_n": required_n,
        "daily_traffic": daily_traffic,
        "days_elapsed": days_elapsed,
        "planned_duration_days": 20,
        "srm_threshold": 0.0005,
        "current_n": len(df),
    }


def test_run_monitor_aggregates_three_checks_green():
    # Clean SRM df + latency guardrail column. Asserts run_monitor populates
    # all three checks and does not escalate to RED on clean data.
    srm_df = _make_clean_srm_df(days=14, per_day=2000, seed=11)
    rng = np.random.default_rng(42)
    srm_df["latency_ms"] = rng.normal(500, 50, len(srm_df))
    ctx = _monitor_context(
        srm_df,
        required_n=len(srm_df),
        daily_traffic=2000,
        days_elapsed=14,
    )
    ctx["timestamp_col"] = "timestamp"
    report = run_monitor("exp-green", ctx)
    assert isinstance(report, MonitorReport)
    assert report.status != "RED"
    assert set(report.checks.keys()) == {
        "srm_trend",
        "guardrail_health",
        "sample_accumulation",
    }
    assert report.checks["srm_trend"]["verdict"] != "BLOCK"
    assert report.checks["guardrail_health"]["verdict"] == "PASS"
    assert report.checks["sample_accumulation"]["verdict"] == "PASS"
    assert report.experiment_id == "exp-green"
    assert len(report.recommendations) >= 1


def test_run_monitor_worst_of_three_wins_red():
    # Clean SRM + clean guardrail, but sample RED (stalled).
    df = _make_guardrail_df(n_per_arm=500)
    ctx = _monitor_context(df, required_n=10000, daily_traffic=0, days_elapsed=5)
    report = run_monitor("exp-stalled", ctx)
    assert report.status == "RED"
    assert report.checks["sample_accumulation"]["verdict"] == "BLOCK"
    assert any("SAMPLE" in r for r in report.recommendations)


def test_run_monitor_persists_via_store(tmp_path):
    store = ExperimentStore(root=tmp_path)
    store.save_experiment(
        "exp-persist",
        {
            "experiment": {
                "id": "exp-persist",
                "name": "Persist test",
                "status": "COLLECTING",
            }
        },
    )
    df = _make_guardrail_df(n_per_arm=500)
    ctx = _monitor_context(df)
    report = run_monitor("exp-persist", ctx, store=store)
    assert isinstance(report, MonitorReport)

    # Confirm at least one analysis file was written.
    analyses = list((tmp_path / "exp-persist" / "analyses").glob("*.json"))
    assert len(analyses) == 1


def test_run_monitor_context_as_callable():
    df = _make_guardrail_df(n_per_arm=500)

    def loader():
        return _monitor_context(df)

    report = run_monitor("exp-callable", loader)
    assert isinstance(report, MonitorReport)
    assert report.status in {"GREEN", "YELLOW", "RED"}


def test_monitor_report_to_dict_roundtrip():
    report = MonitorReport(
        status="YELLOW",
        checks={"a": {"verdict": "WARNING"}},
        recommendations=["do the thing"],
        interpretation="half-bad",
        experiment_id="x",
    )
    payload = report.to_dict()
    assert payload["status"] == "YELLOW"
    assert payload["checks"]["a"]["verdict"] == "WARNING"
    assert payload["recommendations"] == ["do the thing"]
    assert payload["report_type"] == "monitor"
    assert payload["experiment_id"] == "x"
