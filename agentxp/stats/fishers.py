"""
Fisher's exact test for small-sample proportion comparisons.

Used as a fallback from ``proportion_test`` when any cell count is small
(n < 30 or success count < 5). The orchestrator picks this automatically
when the large-sample z-test is unreliable.
"""

import math

from scipy import stats as sp_stats


def fishers_exact_test(
    c_success, c_n, t_success, t_n, alpha=0.05, alternative="two-sided"
):
    """Fisher's exact test on the 2x2 success/failure contingency table.

    Args:
        c_success: number of successes in control.
        c_n: total observations in control.
        t_success: number of successes in treatment.
        t_n: total observations in treatment.
        alpha: significance threshold (default 0.05).
        alternative: "two-sided", "less", or "greater" (passed to scipy).

    Returns:
        dict with: p_value, odds_ratio, ci_lower, ci_upper (log-odds Wald
        with Haldane-Anscombe correction), decision ("Reject"/"FailToReject"),
        rate_control, rate_treatment, interpretation.
    """
    # Input validation.
    if c_n <= 0 or t_n <= 0:
        raise ValueError(
            f"c_n and t_n must be > 0 (got c_n={c_n}, t_n={t_n})."
        )
    if c_success < 0 or t_success < 0:
        raise ValueError("success counts must be non-negative.")
    if c_success > c_n or t_success > t_n:
        raise ValueError("success counts cannot exceed totals.")
    if alternative not in ("two-sided", "less", "greater"):
        raise ValueError(
            f"alternative must be 'two-sided', 'less', or 'greater' (got {alternative!r})."
        )
    if not 0 < alpha < 1:
        raise ValueError(f"alpha must be in (0, 1), got {alpha}.")

    c_fail = c_n - c_success
    t_fail = t_n - t_success

    table = [[c_success, c_fail], [t_success, t_fail]]
    odds_ratio_scipy, p_value = sp_stats.fisher_exact(table, alternative=alternative)

    # Haldane-Anscombe corrected log-odds ratio + Wald CI for the OR.
    a = c_success + 0.5
    b = c_fail + 0.5
    c = t_success + 0.5
    d = t_fail + 0.5
    or_ha = (c * b) / (a * d)  # treatment-vs-control odds ratio, HA-corrected
    log_or = math.log(or_ha)
    se_log_or = math.sqrt(1 / a + 1 / b + 1 / c + 1 / d)
    z_crit = sp_stats.norm.ppf(1 - alpha / 2)
    ci_lower = math.exp(log_or - z_crit * se_log_or)
    ci_upper = math.exp(log_or + z_crit * se_log_or)

    rate_c = c_success / c_n
    rate_t = t_success / t_n
    decision = "Reject" if p_value < alpha else "FailToReject"

    if decision == "Reject":
        direction = "higher" if rate_t > rate_c else "lower"
        interp = (
            f"Fisher's exact test: treatment rate {rate_t:.4f} is significantly "
            f"{direction} than control {rate_c:.4f} "
            f"(p={p_value:.4f}, OR={or_ha:.3f}, "
            f"{int((1 - alpha) * 100)}% CI [{ci_lower:.3f}, {ci_upper:.3f}])."
        )
    else:
        interp = (
            f"Fisher's exact test: no significant difference between treatment "
            f"({rate_t:.4f}) and control ({rate_c:.4f}) "
            f"(p={p_value:.4f}, OR={or_ha:.3f}, "
            f"{int((1 - alpha) * 100)}% CI [{ci_lower:.3f}, {ci_upper:.3f}])."
        )

    return {
        "test": "fishers_exact",
        "p_value": float(p_value),
        "odds_ratio": float(or_ha),
        "odds_ratio_scipy": float(odds_ratio_scipy),
        "ci_lower": float(ci_lower),
        "ci_upper": float(ci_upper),
        "decision": decision,
        "significant": decision == "Reject",
        "rate_control": float(rate_c),
        "rate_treatment": float(rate_t),
        "n_control": int(c_n),
        "n_treatment": int(t_n),
        "alpha": alpha,
        "alternative": alternative,
        "interpretation": interp,
    }
