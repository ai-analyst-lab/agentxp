"""
Guardrail (non-inferiority) tests and denominator SRM.

Guardrail metrics defend against unintended harm: we don't need treatment
to win, we need to be *confident it isn't losing by more than X%*. This is
a one-sided non-inferiority test against a margin, not a two-sided test
against zero.

Denominator SRM is the ratio-metric sanity check: when the denominator
counts differ between arms, any treatment effect on the ratio can be
driven by that imbalance rather than by a real behavioral change.
"""

import math

import numpy as np
import pandas as pd
from scipy import stats as sp_stats


def guardrail_test(
    control,
    treatment,
    metric_type="mean",
    nim_relative=0.02,
    alpha=0.05,
    invert=False,
):
    """Non-inferiority test for guardrail metrics.

    Direction convention: by default, we are worried treatment will be
    *lower* than control (e.g., revenue, retention). The non-inferiority
    margin is ``-nim_relative * control_mean`` — treatment is allowed to
    drop up to that much. Pass ``invert=True`` when lower-is-better (e.g.,
    latency, error rate): the margin flips to ``+nim_relative * control_mean``
    and treatment is allowed to rise up to that much.

    Verdict semantics:
        PASS: the worst case (one-sided CI bound) is still inside the margin.
        WARNING: point estimate is inside the margin, but the CI crosses it.
        BLOCK: point estimate itself is beyond the margin.

    Args:
        control: array-like of control observations (``metric_type="mean"``)
            OR a (success, n) tuple (``metric_type="proportion"``).
        treatment: array-like or (success, n) tuple, matching control.
        metric_type: "mean" (Welch one-sided t) or "proportion" (one-sided z).
        nim_relative: non-inferiority margin as a relative fraction of the
            control baseline (default 0.02 = 2%).
        alpha: significance threshold (default 0.05).
        invert: True when lower-is-better (latency, errors).

    Returns:
        dict with: verdict (PASS/WARNING/BLOCK), point_estimate, ni_margin,
        ci_lower_one_sided, worst_case_effect, p_value, interpretation.
    """
    if metric_type not in ("mean", "proportion"):
        raise ValueError(
            f"metric_type must be 'mean' or 'proportion' (got {metric_type!r})."
        )
    if nim_relative <= 0:
        raise ValueError(
            f"nim_relative must be > 0 (got {nim_relative}); margins are "
            "always expressed as a positive fraction."
        )
    if not 0 < alpha < 1:
        raise ValueError(f"alpha must be in (0, 1), got {alpha}.")

    if metric_type == "mean":
        c = pd.Series(control).dropna().values
        t = pd.Series(treatment).dropna().values
        n_c, n_t = len(c), len(t)
        if n_c < 2 or n_t < 2:
            raise ValueError("Need at least 2 observations per group for mean guardrail.")
        mean_c = float(c.mean())
        mean_t = float(t.mean())
        var_c = float(c.var(ddof=1))
        var_t = float(t.var(ddof=1))
        se = math.sqrt(var_c / n_c + var_t / n_t)
        if se == 0:
            raise ValueError(
                "Zero standard error — both groups are constant; "
                "guardrail test not meaningful."
            )
        nu_num = (var_c / n_c + var_t / n_t) ** 2
        nu_den = (var_c / n_c) ** 2 / (n_c - 1) + (var_t / n_t) ** 2 / (n_t - 1)
        df = nu_num / nu_den if nu_den > 0 else min(n_c, n_t) - 1
        crit = float(sp_stats.t.ppf(1 - alpha, df))
        baseline = mean_c
        point_estimate = mean_t - mean_c
    else:  # proportion
        try:
            c_success, c_n = control
            t_success, t_n = treatment
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "For metric_type='proportion', control and treatment must be "
                "(successes, n) tuples."
            ) from exc
        if c_n <= 0 or t_n <= 0:
            raise ValueError("proportion guardrail needs c_n > 0 and t_n > 0.")
        rate_c = c_success / c_n
        rate_t = t_success / t_n
        se = math.sqrt(rate_c * (1 - rate_c) / c_n + rate_t * (1 - rate_t) / t_n)
        if se == 0:
            raise ValueError(
                "Zero standard error on proportion guardrail — degenerate rates."
            )
        crit = float(sp_stats.norm.ppf(1 - alpha))
        baseline = rate_c
        point_estimate = rate_t - rate_c

    if baseline == 0:
        raise ValueError(
            "Control baseline is zero — relative non-inferiority margin is undefined."
        )

    # Orient so that "bad" is a negative point_estimate.
    # invert=True → flip sign of the effect so the rest of the logic is uniform.
    oriented_effect = -point_estimate if invert else point_estimate
    ni_margin = -abs(nim_relative * baseline)  # always negative in oriented space
    # One-sided lower CI bound on the *oriented* effect.
    ci_lower_one_sided = oriented_effect - crit * se
    worst_case_effect = ci_lower_one_sided

    # p-value for H0: oriented_effect <= ni_margin vs H1: oriented_effect > ni_margin
    z_stat = (oriented_effect - ni_margin) / se
    if metric_type == "mean":
        p_value = float(1 - sp_stats.t.cdf(z_stat, df))
    else:
        p_value = float(1 - sp_stats.norm.cdf(z_stat))

    if oriented_effect < ni_margin:
        verdict = "BLOCK"
        note = (
            "Point estimate itself is beyond the non-inferiority margin. "
            "Treatment causes unacceptable degradation."
        )
    elif worst_case_effect < ni_margin:
        verdict = "WARNING"
        note = (
            "Point estimate is within the margin, but the one-sided CI crosses it. "
            "Not confident the guardrail passes. Collect more data."
        )
    else:
        verdict = "PASS"
        note = (
            "Worst-case effect (one-sided CI bound) is still inside the "
            "non-inferiority margin. Guardrail holds."
        )

    interp = (
        f"Guardrail {metric_type} test "
        f"({'lower-is-better' if invert else 'higher-is-better'}): "
        f"point estimate {point_estimate:+.4f} (oriented {oriented_effect:+.4f}), "
        f"margin {ni_margin:.4f} (rel {nim_relative:.1%}), "
        f"worst case {worst_case_effect:+.4f}. Verdict: {verdict}. {note}"
    )

    return {
        "test": "guardrail_ni",
        "metric_type": metric_type,
        "invert": bool(invert),
        "verdict": verdict,
        "point_estimate": float(point_estimate),
        "oriented_effect": float(oriented_effect),
        "ni_margin": float(ni_margin),
        "nim_relative": float(nim_relative),
        "ci_lower_one_sided": float(ci_lower_one_sided),
        "worst_case_effect": float(worst_case_effect),
        "se": float(se),
        "p_value": p_value,
        "alpha": alpha,
        "baseline": float(baseline),
        "interpretation": interp,
    }


def denominator_srm(num_c, den_c, num_t, den_t, expected_ratio=1.0, threshold=0.05):
    """Sanity-check that ratio-metric denominators are balanced across arms.

    Ratio metrics like revenue-per-session are only interpretable when the
    denominator counts are comparable between arms. If treatment induces
    more (or fewer) sessions per user, the ratio will move even when the
    underlying per-session behavior is unchanged — Simpson's paradox
    territory. Run this before ``ratio_metric_test``.

    The test: chi-square goodness-of-fit on ``[den_c_total, den_t_total]``
    against the expected allocation (``expected_ratio`` of control per unit
    of treatment, default 1:1).

    Args:
        num_c: control numerator total (unused by the test itself; kept in
            the signature so the orchestrator can pass all four sums and
            keep call sites symmetric with ``ratio_metric_test``).
        den_c: control denominator total count.
        num_t: treatment numerator total.
        den_t: treatment denominator total count.
        expected_ratio: expected control:treatment denominator ratio
            (default 1.0 = balanced).
        threshold: p-value threshold below which we downgrade to WARNING /
            BLOCK (default 0.05, more lenient than count SRM because
            denominator imbalance is often a legitimate treatment effect).

    Returns:
        dict with: chi2_stat, p_value, verdict (PASS/WARNING/BLOCK),
        observed_ratio, expected_ratio, interpretation.
    """
    if den_c <= 0 or den_t <= 0:
        raise ValueError(
            f"den_c and den_t must be > 0 (got den_c={den_c}, den_t={den_t})."
        )
    if expected_ratio <= 0:
        raise ValueError(f"expected_ratio must be > 0 (got {expected_ratio}).")
    if not 0 < threshold < 1:
        raise ValueError(f"threshold must be in (0, 1), got {threshold}.")

    total = den_c + den_t
    # expected_ratio = expected(den_c) / expected(den_t)
    expected_c = total * expected_ratio / (1 + expected_ratio)
    expected_t = total - expected_c

    observed = np.array([den_c, den_t], dtype=float)
    expected = np.array([expected_c, expected_t], dtype=float)
    chi2_stat, p_value = sp_stats.chisquare(observed, f_exp=expected)

    observed_ratio = den_c / den_t

    if p_value >= threshold * 2:  # comfortably above threshold
        verdict = "PASS"
        note = "Denominator counts are balanced; ratio metric is interpretable."
    elif p_value >= threshold:
        verdict = "WARNING"
        note = (
            "Denominator counts are marginally imbalanced. Ratio effect may be "
            "partly driven by denominator behavior — inspect num/den separately."
        )
    else:
        verdict = "BLOCK"
        note = (
            "Denominator SRM: treatment arms have significantly different "
            "denominator counts. The ratio metric is NOT directly comparable "
            "between arms. Decompose into numerator and denominator analyses."
        )

    interp = (
        f"Denominator SRM: den_c={int(den_c):,} vs den_t={int(den_t):,} "
        f"(observed ratio {observed_ratio:.3f}, expected {expected_ratio:.3f}), "
        f"chi2={chi2_stat:.2f}, p={p_value:.6f}. Verdict: {verdict}. {note}"
    )

    return {
        "test": "denominator_srm",
        "chi2_stat": float(chi2_stat),
        "p_value": float(p_value),
        "verdict": verdict,
        "den_control": float(den_c),
        "den_treatment": float(den_t),
        "num_control": float(num_c),
        "num_treatment": float(num_t),
        "observed_ratio": float(observed_ratio),
        "expected_ratio": float(expected_ratio),
        "threshold": float(threshold),
        "interpretation": interp,
    }
