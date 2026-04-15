"""
Experiment extension estimation for underpowered null results.

When a test returns "no significant effect" but the observed effect size
is actually interesting, the usual question is: how many more days would
we need to reach adequate power against *that* observed effect? This
function answers that — used in the LEARN branch of the interpretation
tree.
"""

import math

from scipy import stats as sp_stats


def extension_estimate(
    current_n,
    current_mde_observed,
    required_power,
    baseline_variance,
    daily_traffic,
    alpha=0.05,
):
    """How much longer should we run to reach required power at observed effect?

    Solves the standard two-sample z-formula for the total per-group sample
    needed to detect ``current_mde_observed`` at ``required_power``, then
    reports the gap to ``current_n`` and converts it to days of collection
    at ``daily_traffic`` (across both arms).

    Args:
        current_n: current sample size per group.
        current_mde_observed: absolute effect size actually seen so far
            (treatment_mean - control_mean or equivalent). Non-zero.
        required_power: target power (e.g., 0.80).
        baseline_variance: per-unit variance of the outcome (used for both
            arms; Welch approximation assumes homoscedasticity).
        daily_traffic: total new enrollments per day across both arms.
        alpha: significance level for the two-sided test (default 0.05).

    Returns:
        dict with: required_n_per_group, additional_n_needed, additional_days,
        total_duration, feasible (bool), interpretation.
    """
    if current_n < 2:
        raise ValueError(f"current_n must be >= 2 (got {current_n}).")
    if current_mde_observed == 0:
        raise ValueError(
            "current_mde_observed must be non-zero — cannot size an "
            "experiment around a zero effect."
        )
    if not 0 < required_power < 1:
        raise ValueError(f"required_power must be in (0, 1), got {required_power}.")
    if baseline_variance <= 0:
        raise ValueError(f"baseline_variance must be > 0 (got {baseline_variance}).")
    if daily_traffic <= 0:
        raise ValueError(f"daily_traffic must be > 0 (got {daily_traffic}).")
    if not 0 < alpha < 1:
        raise ValueError(f"alpha must be in (0, 1), got {alpha}.")

    z_alpha = sp_stats.norm.ppf(1 - alpha / 2)
    z_beta = sp_stats.norm.ppf(required_power)

    # Standard two-sample z-test sample size for continuous outcome with
    # shared variance:  n = ((z_a + z_b)² · 2·var) / effect²
    required_n_per_group = math.ceil(
        ((z_alpha + z_beta) ** 2) * 2 * baseline_variance
        / (current_mde_observed ** 2)
    )

    additional_n_needed = max(0, required_n_per_group - current_n)
    # daily_traffic is total across both arms → per-group enrollment / day
    per_group_per_day = daily_traffic / 2
    additional_days = math.ceil(additional_n_needed / per_group_per_day) if additional_n_needed > 0 else 0
    current_days = math.ceil(current_n / per_group_per_day) if current_n > 0 else 0
    total_duration = current_days + additional_days

    # Feasibility rule of thumb: anything past ~56 days (8 weeks) of
    # additional collection is typically not worth it — matches
    # ``duration_estimate`` viability bands.
    feasible = additional_days <= 56

    if additional_n_needed == 0:
        interp = (
            f"Already at or above required power: need {required_n_per_group:,} "
            f"per group, have {current_n:,}. No extension required."
        )
    elif feasible:
        interp = (
            f"Need {required_n_per_group:,} per group to hit {required_power:.0%} "
            f"power at observed effect {current_mde_observed:+.4f}. "
            f"Have {current_n:,}, need {additional_n_needed:,} more. "
            f"At {daily_traffic:,.0f} users/day total, that's "
            f"{additional_days} more days ({total_duration} days total). Feasible."
        )
    else:
        interp = (
            f"Need {additional_n_needed:,} more per group ({additional_days} "
            f"days at current traffic) to reach {required_power:.0%} power at "
            f"observed effect {current_mde_observed:+.4f}. "
            "This exceeds the 56-day feasibility threshold — consider a larger "
            "MDE, more traffic, or a quasi-experimental follow-up instead."
        )

    return {
        "required_n_per_group": required_n_per_group,
        "current_n": int(current_n),
        "additional_n_needed": int(additional_n_needed),
        "additional_days": int(additional_days),
        "total_duration": int(total_duration),
        "feasible": bool(feasible),
        "current_mde_observed": float(current_mde_observed),
        "required_power": float(required_power),
        "alpha": float(alpha),
        "daily_traffic": float(daily_traffic),
        "interpretation": interp,
    }
