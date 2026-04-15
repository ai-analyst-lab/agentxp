"""
Guardrail health check.

For each guardrail metric, run the appropriate hypothesis test (Welch's for
continuous, proportion Z-test for binary) and compare the observed treatment
effect against a non-inferiority margin (NIM). A guardrail is considered
violated when the lower confidence bound of the treatment effect breaches
the NIM in the "bad" direction.

Per-metric verdicts are aggregated worst-wins. Verdicts are PASS / WARNING /
BLOCK to match the rest of ``openxp.stats``.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from openxp.stats.ab_tests import proportion_test, welch_test


# Metric type hints accepted in the ``thresholds`` per-metric spec.
_CONTINUOUS = {"continuous", "mean", "numeric"}
_BINARY = {"binary", "proportion", "rate"}


def _worst_verdict(verdicts: list[str]) -> str:
    if "BLOCK" in verdicts:
        return "BLOCK"
    if "WARNING" in verdicts:
        return "WARNING"
    return "PASS"


def _resolve_direction(direction: str | None) -> str:
    """Direction = the BAD direction for the guardrail.

    "decrease" means decreases are bad (e.g., conversion rate).
    "increase" means increases are bad (e.g., page load time).
    """
    if direction is None:
        return "decrease"
    d = str(direction).lower()
    if d in ("decrease", "down", "lower", "less"):
        return "decrease"
    if d in ("increase", "up", "higher", "more"):
        return "increase"
    return "decrease"


def _evaluate_metric(
    control_values: pd.Series,
    treatment_values: pd.Series,
    metric_type: str,
    nim: float,
    direction: str,
    alpha: float,
) -> dict[str, Any]:
    """Run the right test and convert to a guardrail verdict."""
    if metric_type in _BINARY:
        c = control_values.dropna()
        t = treatment_values.dropna()
        c_success = int(c.sum())
        c_n = int(len(c))
        t_success = int(t.sum())
        t_n = int(len(t))
        test_result = proportion_test(c_success, c_n, t_success, t_n, alpha=alpha)
        baseline = test_result.get("rate_control", 0.0)
        diff = test_result.get("diff", 0.0)
        ci_lower = test_result.get("ci_lower", 0.0)
        ci_upper = test_result.get("ci_upper", 0.0)
    else:
        test_result = welch_test(control_values, treatment_values, alpha=alpha)
        baseline = test_result.get("mean_control", 0.0)
        diff = test_result.get("diff", 0.0)
        ci_lower = test_result.get("ci_lower", 0.0)
        ci_upper = test_result.get("ci_upper", 0.0)

    if test_result.get("error"):
        return {
            **test_result,
            "verdict": "WARNING",
            "nim": nim,
            "direction": direction,
            "guardrail_note": (
                "Insufficient data for guardrail test; flagging as WARNING."
            ),
        }

    # NIM is a RELATIVE margin (e.g., 0.02 = 2% of baseline). Convert to an
    # absolute tolerance in metric units.
    nim_abs = abs(nim) * abs(baseline) if baseline != 0 else abs(nim)

    if direction == "decrease":
        # Bad = negative diff. Violation when lower CI bound is below -nim_abs.
        worst_case = ci_lower
        margin = -nim_abs
        violated = worst_case < margin
        marginal = (not violated) and (diff < 0) and (test_result.get("p_value", 1.0) < 0.05)
    else:
        # Bad = positive diff. Violation when upper CI bound is above +nim_abs.
        worst_case = ci_upper
        margin = nim_abs
        violated = worst_case > margin
        marginal = (not violated) and (diff > 0) and (test_result.get("p_value", 1.0) < 0.05)

    if violated:
        verdict = "BLOCK"
        note = (
            f"Guardrail VIOLATED: worst-case effect {worst_case:+.4f} breaches "
            f"NIM {margin:+.4f}. Immediate escalation recommended."
        )
    elif marginal:
        verdict = "WARNING"
        note = (
            f"Guardrail marginal: statistically significant movement in the bad "
            f"direction but still within NIM {margin:+.4f}. Keep watching."
        )
    else:
        verdict = "PASS"
        note = (
            f"Guardrail holding: worst-case effect {worst_case:+.4f} within "
            f"NIM {margin:+.4f}."
        )

    return {
        **test_result,
        "verdict": verdict,
        "nim": nim,
        "nim_absolute": nim_abs,
        "direction": direction,
        "worst_case_effect": worst_case,
        "margin": margin,
        "guardrail_note": note,
    }


def guardrail_health(
    df: pd.DataFrame,
    treatment_col: str,
    guardrail_metrics: list[str],
    thresholds: dict[str, dict[str, Any]],
    alpha: float = 0.05,
    control_value: Any | None = None,
) -> dict:
    """Run a guardrail test per metric and aggregate worst-wins.

    Args:
        df: DataFrame with treatment column and guardrail metric columns.
        treatment_col: Column with variant assignment.
        guardrail_metrics: List of metric column names to check.
        thresholds: Per-metric spec. ``{metric: {"nim": float,
            "direction": "decrease"|"increase", "type": "continuous"|"binary"}}``.
            ``nim`` is a RELATIVE margin (e.g. 0.02 = 2% of baseline).
        alpha: Significance threshold for the underlying tests.
        control_value: Value in ``treatment_col`` representing control. If
            None, the lexicographically first value is used.

    Returns:
        dict with:
            - ``test``: ``"guardrail_health"``
            - ``per_metric``: dict of metric → result dict (includes verdict,
              ci, nim, direction, guardrail_note, underlying test output)
            - ``flagged_metrics``: list of metrics with verdict != PASS
            - ``verdict``: aggregate PASS / WARNING / BLOCK
            - ``interpretation``: plain-language summary
    """
    if treatment_col not in df.columns:
        return {
            "test": "guardrail_health",
            "error": f"treatment_col {treatment_col!r} not in DataFrame",
            "verdict": "BLOCK",
            "interpretation": (
                f"Cannot run guardrail health — {treatment_col!r} missing."
            ),
        }
    if not guardrail_metrics:
        return {
            "test": "guardrail_health",
            "per_metric": {},
            "flagged_metrics": [],
            "verdict": "PASS",
            "interpretation": "No guardrail metrics configured; nothing to check.",
        }

    variants = sorted(df[treatment_col].dropna().unique().tolist())
    if len(variants) < 2:
        return {
            "test": "guardrail_health",
            "error": "Need at least 2 variants to run guardrail tests.",
            "verdict": "BLOCK",
            "interpretation": "Only one variant observed — cannot compare.",
        }

    if control_value is None:
        control_value = variants[0]
    treatment_variants = [v for v in variants if v != control_value]
    if not treatment_variants:
        return {
            "test": "guardrail_health",
            "error": f"No treatment variant found (control={control_value!r}).",
            "verdict": "BLOCK",
            "interpretation": (
                "Only the control variant is present in data; cannot compare."
            ),
        }
    # Use the first non-control variant for the headline test.
    treatment_value = treatment_variants[0]

    control_df = df[df[treatment_col] == control_value]
    treatment_df = df[df[treatment_col] == treatment_value]

    per_metric: dict[str, Any] = {}
    flagged: list[str] = []
    for metric in guardrail_metrics:
        if metric not in df.columns:
            per_metric[metric] = {
                "verdict": "WARNING",
                "error": f"metric {metric!r} not in DataFrame",
                "guardrail_note": (
                    f"Cannot evaluate {metric!r} — column missing."
                ),
            }
            flagged.append(metric)
            continue

        spec = thresholds.get(metric, {})
        nim = float(spec.get("nim", 0.0))
        direction = _resolve_direction(spec.get("direction"))
        metric_type = str(spec.get("type", "continuous")).lower()

        result = _evaluate_metric(
            control_df[metric],
            treatment_df[metric],
            metric_type=metric_type,
            nim=nim,
            direction=direction,
            alpha=alpha,
        )
        per_metric[metric] = result
        if result["verdict"] != "PASS":
            flagged.append(metric)

    agg = _worst_verdict([r["verdict"] for r in per_metric.values()])
    if agg == "PASS":
        interp = (
            f"All {len(guardrail_metrics)} guardrail(s) holding within NIM. "
            "Safe to continue."
        )
    elif agg == "WARNING":
        interp = (
            f"{len(flagged)} guardrail(s) flagged as WARNING: {flagged}. "
            "Keep watching — no hard breach yet."
        )
    else:
        interp = (
            f"GUARDRAIL VIOLATION in {len(flagged)} metric(s): {flagged}. "
            "Recommend immediate escalation and possible emergency halt."
        )

    return {
        "test": "guardrail_health",
        "per_metric": per_metric,
        "flagged_metrics": flagged,
        "control_value": control_value,
        "treatment_value": treatment_value,
        "alpha": alpha,
        "verdict": agg,
        "interpretation": interp,
    }
