"""
Power analysis for ratio metrics via the delta method.

Sample size calculations for experiments where the outcome is a ratio of
two random variables (e.g., revenue per session, click-through rate on a
per-request basis). Uses the same variance approximation as
``ratio_metric_test`` so design-phase and analysis-phase math stay in sync.
"""

import math

from scipy import stats as sp_stats


def power_ratio(
    baseline_num_mean,
    baseline_den_mean,
    baseline_num_std,
    baseline_den_std,
    correlation_num_den,
    mde_relative,
    alpha=0.05,
    power=0.80,
):
    """Sample size for a two-sample ratio metric test using the delta method.

    The variance of a ratio R = N/D is approximated by

        Var(R) ≈ (1/D_mean²) · (Var(N) + R²·Var(D) - 2·R·Cov(N, D))

    where Cov(N, D) = correlation · std(N) · std(D). Sample size per group
    is then solved from the standard two-sample z-test formula using the
    approximated per-unit variance as SE²·n.

    Args:
        baseline_num_mean: mean of the numerator per unit (e.g., $/session).
        baseline_den_mean: mean of the denominator per unit (e.g., sessions/user).
        baseline_num_std: standard deviation of the numerator per unit.
        baseline_den_std: standard deviation of the denominator per unit.
        correlation_num_den: Pearson correlation between per-unit numerator
            and denominator (in [-1, 1]). Use 0 if independence is assumed;
            this is conservative (inflates variance in the common case where
            numerator and denominator are positively correlated).
        mde_relative: minimum detectable effect as relative change on the
            baseline ratio (e.g., 0.05 for 5% relative lift).
        alpha: significance level (default 0.05).
        power: statistical power (default 0.80).

    Returns:
        dict with: n_per_group, total_n, baseline_ratio, mde_absolute,
        viability ("VIABLE"/"LARGE"/"INFEASIBLE"), interpretation.
    """
    # Input validation — fail loudly, no silent coercion.
    if baseline_den_mean <= 0:
        raise ValueError(
            f"baseline_den_mean must be > 0 (got {baseline_den_mean}); "
            "ratio metrics require a positive denominator."
        )
    if baseline_num_std < 0 or baseline_den_std < 0:
        raise ValueError(
            "baseline_num_std and baseline_den_std must be non-negative."
        )
    if not -1.0 <= correlation_num_den <= 1.0:
        raise ValueError(
            f"correlation_num_den must be in [-1, 1] (got {correlation_num_den})."
        )
    if mde_relative == 0:
        raise ValueError("mde_relative must be non-zero.")
    if not 0 < alpha < 1:
        raise ValueError(f"alpha must be in (0, 1), got {alpha}.")
    if not 0 < power < 1:
        raise ValueError(f"power must be in (0, 1), got {power}.")

    baseline_ratio = baseline_num_mean / baseline_den_mean
    mde_absolute = abs(baseline_ratio * mde_relative)

    # Per-unit variance of the ratio via delta method.
    var_num = baseline_num_std ** 2
    var_den = baseline_den_std ** 2
    cov_nd = correlation_num_den * baseline_num_std * baseline_den_std
    var_ratio_per_unit = (
        var_num + (baseline_ratio ** 2) * var_den - 2 * baseline_ratio * cov_nd
    ) / (baseline_den_mean ** 2)

    if var_ratio_per_unit <= 0:
        return {
            "error": "non-positive delta-method variance",
            "interpretation": (
                "Delta-method variance is non-positive — usually caused by a "
                "correlation near 1 with similar scales. Check inputs."
            ),
        }

    # Two-sample z-test sample size:
    #     n = ((z_{1-alpha/2} + z_{power})² · 2·var_per_unit) / mde_absolute²
    z_alpha = sp_stats.norm.ppf(1 - alpha / 2)
    z_beta = sp_stats.norm.ppf(power)
    n_per_group = math.ceil(
        ((z_alpha + z_beta) ** 2) * 2 * var_ratio_per_unit / (mde_absolute ** 2)
    )
    total_n = n_per_group * 2

    if n_per_group <= 1_000_000:
        viability = "VIABLE"
    elif n_per_group <= 10_000_000:
        viability = "LARGE"
    else:
        viability = "INFEASIBLE"

    interp = (
        f"Need {n_per_group:,} units per group ({total_n:,} total) to detect a "
        f"{mde_relative:.1%} relative lift on baseline ratio {baseline_ratio:.4f} "
        f"(absolute MDE {mde_absolute:.4f}; alpha={alpha}, power={power:.0%}, "
        f"correlation={correlation_num_den:+.2f}). Viability: {viability}."
    )

    return {
        "n_per_group": n_per_group,
        "total_n": total_n,
        "baseline_ratio": float(baseline_ratio),
        "mde_absolute": float(mde_absolute),
        "mde_relative": float(mde_relative),
        "var_ratio_per_unit": float(var_ratio_per_unit),
        "alpha": alpha,
        "power": power,
        "correlation_num_den": float(correlation_num_den),
        "viability": viability,
        "interpretation": interp,
    }
