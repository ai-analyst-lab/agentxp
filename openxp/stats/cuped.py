"""
CUPED variance reduction for experiment analysis.

CUPED (Controlled-experiment Using Pre-Experiment Data; Deng et al. 2013,
Microsoft ExP) reduces the variance of a treatment effect estimate by using
a pre-experiment covariate that is correlated with the outcome.

For pre-experiment covariate X and post-experiment outcome Y, compute
    theta = Cov(Y, X) / Var(X)
and define the adjusted outcome
    Y* = Y - theta * (X - E[X]).
The treatment effect on Y* is unbiased and has variance reduced by a factor
of (1 - rho^2), where rho = corr(Y, X). The theoretical variance reduction
percentage is therefore rho^2.

Public API:
    - cuped_adjust(y_pre, y_post, treatment=None) -> dict
    - cuped_welch_test(control_pre, control_post, treatment_pre,
                       treatment_post, alpha=0.05) -> dict
    - variance_reduction(y_pre, y_post) -> dict
"""

from __future__ import annotations

import math

import numpy as np

from openxp.stats.ab_tests import welch_test


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _as_float_array(values, name: str) -> np.ndarray:
    """Coerce input to a 1-D float ndarray with a clear error on failure."""
    try:
        arr = np.asarray(values, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric array-like: {exc}") from exc
    if arr.ndim != 1:
        raise ValueError(f"{name} must be 1-dimensional, got shape {arr.shape}")
    return arr


def _check_no_nan(arr: np.ndarray, name: str) -> None:
    if np.isnan(arr).any():
        raise ValueError(
            f"{name} contains NaN values. CUPED requires complete pre/post "
            "pairs; drop or impute missing values before calling."
        )


def _check_aligned(a: np.ndarray, b: np.ndarray, name_a: str, name_b: str) -> None:
    if len(a) != len(b):
        raise ValueError(
            f"{name_a} and {name_b} must have the same length "
            f"(got {len(a)} and {len(b)})."
        )


def _compute_theta(y_pre: np.ndarray, y_post: np.ndarray) -> float:
    """theta = Cov(Y_post, Y_pre) / Var(Y_pre), using sample (ddof=1)."""
    var_pre = float(np.var(y_pre, ddof=1))
    if var_pre == 0.0:
        return 0.0
    cov = float(np.cov(y_post, y_pre, ddof=1)[0, 1])
    return cov / var_pre


# ---------------------------------------------------------------------------
# variance_reduction
# ---------------------------------------------------------------------------


def variance_reduction(y_pre, y_post) -> dict:
    """Standalone helper: expected CUPED variance reduction.

    Args:
        y_pre: pre-experiment covariate values (array-like).
        y_post: post-experiment outcome values (array-like).

    Returns:
        dict with: correlation, variance_reduction_pct (= rho^2 * 100),
        n, interpretation.
    """
    y_pre_arr = _as_float_array(y_pre, "y_pre")
    y_post_arr = _as_float_array(y_post, "y_post")
    _check_aligned(y_pre_arr, y_post_arr, "y_pre", "y_post")
    _check_no_nan(y_pre_arr, "y_pre")
    _check_no_nan(y_post_arr, "y_post")

    n = len(y_pre_arr)
    if n < 2:
        return {
            "test": "cuped_variance_reduction",
            "error": "Need at least 2 observations",
            "correlation": 0.0,
            "variance_reduction_pct": 0.0,
            "n": n,
            "interpretation": "Insufficient data to estimate variance reduction.",
        }

    if np.array_equal(y_pre_arr, y_post_arr):
        raise ValueError(
            "y_pre and y_post are identical; CUPED requires distinct "
            "pre-experiment and post-experiment measurements."
        )

    var_pre = float(np.var(y_pre_arr, ddof=1))
    var_post = float(np.var(y_post_arr, ddof=1))
    if var_pre == 0.0 or var_post == 0.0:
        rho = 0.0
    else:
        rho = float(np.corrcoef(y_pre_arr, y_post_arr)[0, 1])

    reduction_pct = float(rho * rho * 100.0)

    if abs(rho) < 0.1:
        strength = "weak"
        advice = "CUPED will provide little benefit; consider a better covariate."
    elif abs(rho) < 0.3:
        strength = "modest"
        advice = "CUPED offers a small but real variance reduction."
    elif abs(rho) < 0.6:
        strength = "moderate"
        advice = "CUPED is worthwhile on this metric."
    else:
        strength = "strong"
        advice = "CUPED will substantially tighten confidence intervals."

    interp = (
        f"Pre/post correlation rho = {rho:.3f} ({strength}). "
        f"Expected variance reduction = {reduction_pct:.1f}%. {advice}"
    )

    return {
        "test": "cuped_variance_reduction",
        "correlation": rho,
        "variance_reduction_pct": reduction_pct,
        "n": n,
        "interpretation": interp,
    }


# ---------------------------------------------------------------------------
# cuped_adjust
# ---------------------------------------------------------------------------


def cuped_adjust(y_pre, y_post, treatment=None) -> dict:
    """Compute CUPED-adjusted outcomes.

    Adjusted outcome: Y* = Y_post - theta * (Y_pre - mean(Y_pre))
    where theta = Cov(Y_post, Y_pre) / Var(Y_pre).

    Args:
        y_pre: pre-experiment covariate values (array-like).
        y_post: post-experiment outcome values (array-like).
        treatment: optional array-like of 0/1 treatment indicators, same
            length as y_pre/y_post. If provided, returns adjusted outcomes
            split by group as well.

    Returns:
        dict with: theta, mean_pre, variance_reduction_pct, correlation,
        y_adjusted (ndarray, full length), control_adjusted (if treatment),
        treatment_adjusted (if treatment), n, interpretation.
    """
    y_pre_arr = _as_float_array(y_pre, "y_pre")
    y_post_arr = _as_float_array(y_post, "y_post")
    _check_aligned(y_pre_arr, y_post_arr, "y_pre", "y_post")
    _check_no_nan(y_pre_arr, "y_pre")
    _check_no_nan(y_post_arr, "y_post")

    n = len(y_pre_arr)
    if n < 2:
        raise ValueError("Need at least 2 observations to compute CUPED adjustment.")

    if np.array_equal(y_pre_arr, y_post_arr):
        raise ValueError(
            "y_pre and y_post are identical; CUPED requires distinct "
            "pre-experiment and post-experiment measurements."
        )

    theta = _compute_theta(y_pre_arr, y_post_arr)
    mean_pre = float(y_pre_arr.mean())
    y_adjusted = y_post_arr - theta * (y_pre_arr - mean_pre)

    var_pre = float(np.var(y_pre_arr, ddof=1))
    var_post = float(np.var(y_post_arr, ddof=1))
    if var_pre == 0.0 or var_post == 0.0:
        rho = 0.0
    else:
        rho = float(np.corrcoef(y_pre_arr, y_post_arr)[0, 1])
    reduction_pct = float(rho * rho * 100.0)

    result = {
        "test": "cuped_adjust",
        "theta": theta,
        "mean_pre": mean_pre,
        "correlation": rho,
        "variance_reduction_pct": reduction_pct,
        "y_adjusted": y_adjusted,
        "n": n,
    }

    if treatment is not None:
        t_arr = _as_float_array(treatment, "treatment")
        _check_aligned(t_arr, y_pre_arr, "treatment", "y_pre")
        # Accept 0/1 or bool
        mask_t = t_arr.astype(bool)
        mask_c = ~mask_t
        result["control_adjusted"] = y_adjusted[mask_c]
        result["treatment_adjusted"] = y_adjusted[mask_t]
        result["n_control"] = int(mask_c.sum())
        result["n_treatment"] = int(mask_t.sum())
        interp = (
            f"CUPED theta = {theta:.4f} (from pooled pre/post, rho = {rho:.3f}). "
            f"Expected variance reduction = {reduction_pct:.1f}%. "
            f"Returned adjusted outcomes for {int(mask_c.sum())} control and "
            f"{int(mask_t.sum())} treatment observations."
        )
    else:
        interp = (
            f"CUPED theta = {theta:.4f} (rho = {rho:.3f}). "
            f"Expected variance reduction = {reduction_pct:.1f}%. "
            f"Adjusted outcome Y* = Y_post - theta * (Y_pre - {mean_pre:.4f})."
        )

    result["interpretation"] = interp
    return result


# ---------------------------------------------------------------------------
# cuped_welch_test
# ---------------------------------------------------------------------------


def cuped_welch_test(
    control_pre,
    control_post,
    treatment_pre,
    treatment_post,
    alpha: float = 0.05,
) -> dict:
    """End-to-end CUPED-adjusted Welch's t-test.

    Computes theta on the pooled pre/post data across both groups, adjusts
    each group's outcome, and runs Welch's t-test on the adjusted outcomes.
    Reports variance reduction versus the unadjusted analysis.

    Args:
        control_pre: pre-experiment covariate for control (array-like).
        control_post: post-experiment outcome for control (array-like).
        treatment_pre: pre-experiment covariate for treatment (array-like).
        treatment_post: post-experiment outcome for treatment (array-like).
        alpha: significance threshold (default 0.05).

    Returns:
        dict with: test, theta, mean_pre, variance_reduction_pct (realized,
        from sample variances of adjusted vs raw), expected_variance_reduction_pct
        (rho^2), correlation, adjusted Welch result fields (t_stat, p_value,
        diff, ci_lower, ci_upper, significant, etc.), unadjusted_p_value,
        unadjusted_ci_lower, unadjusted_ci_upper, interpretation.
    """
    c_pre = _as_float_array(control_pre, "control_pre")
    c_post = _as_float_array(control_post, "control_post")
    t_pre = _as_float_array(treatment_pre, "treatment_pre")
    t_post = _as_float_array(treatment_post, "treatment_post")

    _check_aligned(c_pre, c_post, "control_pre", "control_post")
    _check_aligned(t_pre, t_post, "treatment_pre", "treatment_post")
    for arr, name in [
        (c_pre, "control_pre"),
        (c_post, "control_post"),
        (t_pre, "treatment_pre"),
        (t_post, "treatment_post"),
    ]:
        _check_no_nan(arr, name)

    if len(c_pre) < 2 or len(t_pre) < 2:
        return {
            "test": "cuped_welch_test",
            "error": "Need at least 2 observations per group",
            "significant": False,
            "interpretation": "Insufficient data for CUPED Welch test.",
        }

    pooled_pre = np.concatenate([c_pre, t_pre])
    pooled_post = np.concatenate([c_post, t_post])

    if np.array_equal(pooled_pre, pooled_post):
        raise ValueError(
            "Pre-experiment and post-experiment values are identical across "
            "all observations; CUPED requires distinct measurements."
        )

    theta = _compute_theta(pooled_pre, pooled_post)
    mean_pre = float(pooled_pre.mean())

    c_adj = c_post - theta * (c_pre - mean_pre)
    t_adj = t_post - theta * (t_pre - mean_pre)

    # Unadjusted Welch for comparison
    unadj = welch_test(c_post, t_post, alpha=alpha)
    # Adjusted Welch
    adj = welch_test(c_adj, t_adj, alpha=alpha)

    # Expected variance reduction from pooled correlation
    var_pre = float(np.var(pooled_pre, ddof=1))
    var_post = float(np.var(pooled_post, ddof=1))
    if var_pre == 0.0 or var_post == 0.0:
        rho = 0.0
    else:
        rho = float(np.corrcoef(pooled_pre, pooled_post)[0, 1])
    expected_reduction_pct = float(rho * rho * 100.0)

    # Realized within-group variance reduction (adjusted vs raw), averaged
    def _pooled_within_var(a: np.ndarray, b: np.ndarray) -> float:
        n_a, n_b = len(a), len(b)
        if n_a < 2 or n_b < 2:
            return float("nan")
        va = float(np.var(a, ddof=1))
        vb = float(np.var(b, ddof=1))
        return ((n_a - 1) * va + (n_b - 1) * vb) / (n_a + n_b - 2)

    raw_var = _pooled_within_var(c_post, t_post)
    adj_var = _pooled_within_var(c_adj, t_adj)
    if raw_var and not math.isnan(raw_var) and raw_var > 0:
        realized_reduction_pct = float((1.0 - adj_var / raw_var) * 100.0)
    else:
        realized_reduction_pct = 0.0

    direction = "narrower" if (adj.get("ci_upper", 0) - adj.get("ci_lower", 0)) < (
        unadj.get("ci_upper", 0) - unadj.get("ci_lower", 0)
    ) else "no narrower than"

    if adj.get("significant"):
        verdict = (
            f"Significant adjusted effect: diff = {adj['diff']:+.4f}, "
            f"p = {adj['p_value']:.4f}."
        )
    else:
        verdict = (
            f"No significant adjusted effect: diff = {adj['diff']:+.4f}, "
            f"p = {adj['p_value']:.4f}."
        )

    interp = (
        f"CUPED theta = {theta:.4f} (pooled rho = {rho:.3f}, "
        f"expected variance reduction = {expected_reduction_pct:.1f}%). "
        f"Realized within-group variance reduction = {realized_reduction_pct:.1f}%. "
        f"Adjusted CI is {direction} the unadjusted CI "
        f"(unadj p = {unadj.get('p_value', float('nan')):.4f}). {verdict}"
    )

    return {
        "test": "cuped_welch_test",
        "theta": theta,
        "mean_pre": mean_pre,
        "correlation": rho,
        "variance_reduction_pct": realized_reduction_pct,
        "expected_variance_reduction_pct": expected_reduction_pct,
        # Adjusted Welch result fields
        "t_stat": adj.get("t_stat"),
        "p_value": adj.get("p_value"),
        "significant": adj.get("significant", False),
        "mean_control": adj.get("mean_control"),
        "mean_treatment": adj.get("mean_treatment"),
        "diff": adj.get("diff"),
        "relative_lift_pct": adj.get("relative_lift_pct"),
        "ci_lower": adj.get("ci_lower"),
        "ci_upper": adj.get("ci_upper"),
        "effect_size": adj.get("effect_size"),
        "effect_label": adj.get("effect_label"),
        "n_control": adj.get("n_control"),
        "n_treatment": adj.get("n_treatment"),
        "alpha": alpha,
        # Unadjusted comparison
        "unadjusted_p_value": unadj.get("p_value"),
        "unadjusted_ci_lower": unadj.get("ci_lower"),
        "unadjusted_ci_upper": unadj.get("ci_upper"),
        "unadjusted_diff": unadj.get("diff"),
        "interpretation": interp,
    }
