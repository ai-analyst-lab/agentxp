"""
Sequential testing for experiments with optional stopping.

Fixed-horizon A/B tests are invalid under "peeking" — if you check results
repeatedly and stop when p < alpha, the realized Type I error is inflated
far beyond the nominal level. Sequential tests provide *always-valid*
inference: you may stop at any time, for any reason, and the coverage
guarantee of the CI (or Type I error of the test) still holds.

Two families are implemented:

1. Mixture Sequential Probability Ratio Test (mSPRT) — Robbins (1970),
   Howard, Ramdas, McAuliffe, Sekhon (2021, "Time-uniform, nonparametric,
   nonasymptotic confidence sequences"). Deployed in production at
   Optimizely (Johari et al. 2017), Netflix, and others. Supports
   *continuous* peeking — every observation is a valid decision point.

2. Group sequential design with alpha spending — O'Brien & Fleming (1979),
   Pocock (1977), Lan & DeMets (1983). Pre-specifies a fixed number of
   interim analyses and allocates a spending function over information time.

Defaults are chosen to mirror Optimizely / Netflix practice: Gaussian
mixing prior on the effect size for mSPRT, O'Brien-Fleming spending for
group sequential (conservative early, close to fixed-horizon at the end).
"""

import math

import numpy as np
import pandas as pd
from scipy import stats


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _validate_alpha(alpha):
    if not (0 < alpha < 1):
        raise ValueError(f"alpha must be in (0, 1), got {alpha}")


def _validate_tau(tau):
    if tau is not None and tau <= 0:
        raise ValueError(f"tau must be positive, got {tau}")


def _clean_pair(control, treatment):
    c = pd.Series(control).dropna().to_numpy(dtype=float)
    t = pd.Series(treatment).dropna().to_numpy(dtype=float)
    return c, t


def _pooled_sigma2(c, t):
    n_c, n_t = len(c), len(t)
    if n_c < 2 or n_t < 2:
        return None
    var_c = float(np.var(c, ddof=1))
    var_t = float(np.var(t, ddof=1))
    pooled = ((n_c - 1) * var_c + (n_t - 1) * var_t) / (n_c + n_t - 2)
    return max(pooled, 1e-12)


def _default_tau(sigma):
    # Why: a prior SD equal to 1 pooled SD puts ~95% prior mass on effects
    # within ~2 SDs, which is the standard "weakly informative" choice from
    # Howard et al. (2021) for the Gaussian mixture mSPRT.
    return sigma


# ---------------------------------------------------------------------------
# mSPRT — mixture SPRT with Gaussian mixing
# ---------------------------------------------------------------------------


def _msprt_core(diff, se, n_eff, sigma2, tau, alpha):
    """Always-valid CI radius and mixture e-value for a Gaussian mSPRT.

    Derivation (Robbins 1970; Howard et al. 2021, normal-mixture sequence).
    The effect estimate is treated as a sufficient statistic
    ``diff ~ N(theta, v)`` with ``v = sigma^2 / n_eff`` (the difference-in-
    means sampling variance). Mixing over the effect with a Gaussian prior
    ``theta ~ N(0, tau^2)`` gives the marginal ``diff ~ N(0, v + tau^2)``
    under H0, so the mixture likelihood ratio (the e-value) for testing
    ``theta = theta_0`` is:

        R(theta_0) = sqrt(v / (v + tau^2))
                     * exp( (diff - theta_0)^2 * tau^2 / (2 v (v + tau^2)) )

    This R is a nonnegative martingale with E[R] = 1 under H0, so by Ville's
    inequality rejecting when R >= 1/alpha controls type-I error at alpha
    under arbitrary optional stopping. Inverting ``R(theta_0) < 1/alpha``
    gives the always-valid CI half-width:

        radius^2 = 2 * v(v + tau^2) / tau^2 * log( sqrt((v + tau^2)/v) / alpha )

    Substituting ``v = sigma^2/n_eff`` and ``denom = sigma^2 + n_eff*tau^2``
    (so ``v + tau^2 = denom/n_eff`` and ``(v+tau^2)/v = denom/sigma^2``):

        radius^2 = 2 * sigma^2 * denom / (n_eff^2 * tau^2)
                   * log( sqrt(denom/sigma^2) / alpha )

    The e-value's exponent likewise carries ``n_eff^2`` once ``v`` is
    expanded. ``n_eff = n_c*n_t/(n_c+n_t)`` is the effective per-group size
    for the pooled-variance two-sample formulation.
    """
    s2 = sigma2
    denom = s2 + n_eff * tau * tau
    log_term = math.log(math.sqrt(denom / s2) / alpha)
    if log_term <= 0:
        log_term = 1e-9
    variance_term = s2 * denom / (n_eff * n_eff * tau * tau)
    radius = math.sqrt(2.0 * variance_term * log_term)

    # e-value (evidence measure): mixture likelihood ratio under H1/H0.
    # For decision, reject H0: diff = 0 when |diff| > radius.
    if se > 0:
        z = diff / se
    else:
        z = 0.0
    e_value = math.sqrt(s2 / denom) * math.exp(
        (n_eff * n_eff * diff * diff * tau * tau) / (2.0 * s2 * denom)
    )
    return radius, z, e_value


def msprt_test(control, treatment, tau=None, alpha=0.05):
    """Mixture SPRT for the difference in means between two groups.

    Always-valid: decisions and CIs remain valid under arbitrary optional
    stopping. Uses a Gaussian mixing distribution on the effect size with
    prior SD `tau`. If `tau` is None, defaults to the pooled sample SD
    (a weakly-informative choice from Howard et al. 2021).

    Args:
        control: array-like of continuous outcomes for control.
        treatment: array-like of continuous outcomes for treatment.
        tau: prior SD on the true effect size (None = pooled sigma).
        alpha: one minus the desired coverage level (default 0.05).

    Returns:
        dict with: test, diff, se, n_control, n_treatment, tau, sigma,
        test_stat, e_value, ci_lower, ci_upper, decision, significant,
        alpha, interpretation.
    """
    _validate_alpha(alpha)
    _validate_tau(tau)

    c, t = _clean_pair(control, treatment)
    n_c, n_t = len(c), len(t)

    if n_c < 2 or n_t < 2:
        return {
            "test": "msprt",
            "error": True,
            "error_type": "insufficient_data",
            "message": "Need at least 2 observations per group",
            "significant": False,
            "decision": "CONTINUE",
            "interpretation": "Insufficient data for sequential test.",
        }

    sigma2 = _pooled_sigma2(c, t)
    sigma = math.sqrt(sigma2)
    if tau is None:
        tau = _default_tau(sigma)

    mean_c = float(c.mean())
    mean_t = float(t.mean())
    diff = mean_t - mean_c

    se = math.sqrt(sigma2 / n_c + sigma2 / n_t)
    # Effective per-group sample size for the pooled-variance formulation.
    n_eff = (n_c * n_t) / (n_c + n_t)

    radius, z, e_value = _msprt_core(diff, se, n_eff, sigma2, tau, alpha)

    ci_lower = diff - radius
    ci_upper = diff + radius

    if ci_lower > 0 or ci_upper < 0:
        decision = "STOP_REJECT"
        significant = True
    else:
        decision = "CONTINUE"
        significant = False

    if significant:
        direction = "higher" if diff > 0 else "lower"
        interp = (
            f"Always-valid CI excludes zero: treatment ({mean_t:.4f}) is "
            f"{direction} than control ({mean_c:.4f}) by {diff:+.4f} "
            f"(95% AV CI: [{ci_lower:.4f}, {ci_upper:.4f}]). STOP and reject null."
        )
    else:
        interp = (
            f"Always-valid CI still includes zero (diff = {diff:+.4f}, "
            f"AV CI: [{ci_lower:.4f}, {ci_upper:.4f}]). CONTINUE collecting data; "
            f"you may peek again without Type I inflation."
        )

    return {
        "test": "msprt",
        "diff": float(diff),
        "se": float(se),
        "mean_control": mean_c,
        "mean_treatment": mean_t,
        "n_control": n_c,
        "n_treatment": n_t,
        "tau": float(tau),
        "sigma": float(sigma),
        "test_stat": float(z),
        "e_value": float(e_value),
        "ci_lower": float(ci_lower),
        "ci_upper": float(ci_upper),
        "decision": decision,
        "significant": significant,
        "alpha": alpha,
        "interpretation": interp,
    }


def always_valid_ci(control, treatment, alpha=0.05, tau=None):
    """Always-valid confidence interval for the difference in means.

    Standalone endpoint exposing just the CI from the Gaussian-mixture
    mSPRT. Safe under optional stopping: coverage is 1-alpha simultaneously
    over all sample sizes (Howard et al. 2021).

    Args:
        control: array-like of control outcomes.
        treatment: array-like of treatment outcomes.
        alpha: one minus coverage (default 0.05).
        tau: Gaussian mixing prior SD (None = pooled sigma).

    Returns:
        dict with: lower, upper, width, diff, n_control, n_treatment,
        alpha, tau, interpretation.
    """
    _validate_alpha(alpha)
    _validate_tau(tau)

    c, t = _clean_pair(control, treatment)
    n_c, n_t = len(c), len(t)

    if n_c < 2 or n_t < 2:
        return {
            "test": "always_valid_ci",
            "error": True,
            "error_type": "insufficient_data",
            "message": "Need at least 2 observations per group",
            "interpretation": "Insufficient data for always-valid CI.",
        }

    sigma2 = _pooled_sigma2(c, t)
    sigma = math.sqrt(sigma2)
    if tau is None:
        tau = _default_tau(sigma)

    diff = float(t.mean() - c.mean())
    se = math.sqrt(sigma2 / n_c + sigma2 / n_t)
    n_eff = (n_c * n_t) / (n_c + n_t)

    radius, _, _ = _msprt_core(diff, se, n_eff, sigma2, tau, alpha)
    lower = diff - radius
    upper = diff + radius
    width = upper - lower

    interp = (
        f"Always-valid {int((1 - alpha) * 100)}% CI for (treatment - control): "
        f"[{lower:.4f}, {upper:.4f}] (width {width:.4f}). "
        f"Valid under arbitrary peeking."
    )

    return {
        "test": "always_valid_ci",
        "lower": float(lower),
        "upper": float(upper),
        "width": float(width),
        "diff": diff,
        "n_control": n_c,
        "n_treatment": n_t,
        "alpha": alpha,
        "tau": float(tau),
        "interpretation": interp,
    }


# ---------------------------------------------------------------------------
# Group sequential boundaries — O'Brien-Fleming / Pocock
# ---------------------------------------------------------------------------


def group_sequential_boundaries(n_interims, alpha=0.05, spending="obrien_fleming"):
    """Z-value boundaries at each interim for a group sequential design.

    Computes critical z-values at `n_interims` equally-spaced interim looks
    using either O'Brien-Fleming or Pocock alpha spending. Boundaries are
    two-sided. Interims are spaced at information fractions
    t_k = k / n_interims for k = 1..n_interims.

    - O'Brien-Fleming (1979): very conservative early, relaxing toward the
      fixed-horizon critical value at the final look. Boundary falls
      monotonically across interims.
    - Pocock (1977): a near-constant boundary, trending mildly upward across
      looks under this implementation (see the approximation note below).

    Approximation: boundaries are derived from the Lan-DeMets (1983) alpha
    *spending functions* (the OBF and Pocock forms), but the per-look z is
    obtained by converting the *incremental* alpha at each look to a nominal
    two-sided z, treating looks as independent. Exact group-sequential
    boundaries require recursive integration over the multivariate normal of
    the test statistic at successive looks, which accounts for the positive
    correlation between cumulative statistics. Because that correlation is
    ignored here, the boundaries reproduce the qualitative OBF (monotone
    decreasing) and Pocock (roughly flat) shapes but are not the exact
    classical critical values: the final-look OBF bound is somewhat more
    conservative than the textbook value, and the Pocock bound drifts mildly
    upward rather than being exactly constant. Use these for shape/intuition
    and conservative gating, not as drop-in replacements for an exact
    group-sequential package.

    Args:
        n_interims: number of interim analyses (>= 1).
        alpha: overall two-sided Type I error budget.
        spending: "obrien_fleming" or "pocock".

    Returns:
        dict with: spending, alpha, n_interims, information_fractions,
        cumulative_alpha, boundaries (z-values), nominal_p (two-sided),
        interpretation.
    """
    _validate_alpha(alpha)
    if not isinstance(n_interims, (int, np.integer)) or n_interims < 1:
        raise ValueError(f"n_interims must be a positive int, got {n_interims}")
    if spending not in ("obrien_fleming", "pocock"):
        raise ValueError(
            f"spending must be 'obrien_fleming' or 'pocock', got {spending!r}"
        )

    t = np.array(
        [(k + 1) / n_interims for k in range(n_interims)], dtype=float
    )

    if spending == "obrien_fleming":
        # Lan-DeMets O'Brien-Fleming spending function:
        #   alpha(t) = 2 * (1 - Phi( z_{1-alpha/2} / sqrt(t) ))
        z_half = stats.norm.ppf(1 - alpha / 2)
        cumulative = 2.0 * (1.0 - stats.norm.cdf(z_half / np.sqrt(t)))
    else:  # pocock
        # Lan-DeMets Pocock spending function:
        #   alpha(t) = alpha * log(1 + (e - 1) * t)
        cumulative = alpha * np.log(1.0 + (math.e - 1.0) * t)

    # Boundary at each interim: use the incremental alpha spent, convert
    # to a two-sided nominal z. This ignores correlation across looks
    # (a simplification — exact group-sequential boundaries require
    # recursive integration over the multivariate normal of the test
    # statistic at successive looks). For equally-spaced looks this gives
    # the classical monotone OBF / near-constant Pocock shapes, which is
    # what the spec asks us to verify.
    incr = np.diff(np.concatenate([[0.0], cumulative]))
    incr = np.clip(incr, 1e-12, None)
    boundaries = stats.norm.ppf(1.0 - incr / 2.0)
    nominal_p = 2.0 * (1.0 - stats.norm.cdf(boundaries))

    if spending == "obrien_fleming":
        shape_note = (
            "O'Brien-Fleming: conservative early (high z-boundary), relaxing "
            "toward the fixed-horizon level at the final look."
        )
    else:
        shape_note = (
            "Pocock: near-constant z-boundary across interims (drifts mildly "
            "upward under the independent-increment spending approximation)."
        )

    interp = (
        f"{spending} spending with {n_interims} interim looks at alpha = {alpha}. "
        f"Boundaries (z): {np.round(boundaries, 3).tolist()}. {shape_note}"
    )

    return {
        "test": "group_sequential_boundaries",
        "spending": spending,
        "alpha": alpha,
        "n_interims": int(n_interims),
        "information_fractions": t.tolist(),
        "cumulative_alpha": cumulative.tolist(),
        "boundaries": boundaries.tolist(),
        "nominal_p": nominal_p.tolist(),
        "interpretation": interp,
    }


# ---------------------------------------------------------------------------
# Sequential proportion test — asymptotic mSPRT on the log-odds
# ---------------------------------------------------------------------------


def sequential_proportion_test(c_success, c_n, t_success, t_n, alpha=0.05):
    """Always-valid sequential test for two proportions.

    Uses the Gaussian-mixture mSPRT on the difference of rates with a
    plug-in variance estimate. We chose the asymptotic Gaussian form on
    the rate difference (not log-odds) because:

    1. It matches `proportion_test` from ab_tests.py (same scale, same
       interpretation field), so users see a consistent CI.
    2. The mixture radius derivation is clean and reduces to the same
       mSPRT formula as the continuous case with sigma^2 = plug-in
       Bernoulli variance.
    3. Beta-Binomial conjugate bounds (Howard et al. 2021, §4.2) are an
       alternative but give non-symmetric intervals and complicate the
       API; we defer that to a Bayesian endpoint.

    Args:
        c_success: successes in control.
        c_n: total control observations.
        t_success: successes in treatment.
        t_n: total treatment observations.
        alpha: one minus coverage (default 0.05).

    Returns:
        dict with: test, rate_control, rate_treatment, diff, ci_lower,
        ci_upper, decision, significant, e_value, alpha, interpretation.
    """
    _validate_alpha(alpha)

    if c_n <= 0 or t_n <= 0:
        raise ValueError("Sample sizes must be positive integers")
    if not (0 <= c_success <= c_n) or not (0 <= t_success <= t_n):
        raise ValueError("Success counts must satisfy 0 <= success <= n")

    rate_c = c_success / c_n
    rate_t = t_success / t_n
    diff = rate_t - rate_c

    # Plug-in Bernoulli variance per group, then combine.
    var_c = rate_c * (1 - rate_c)
    var_t = rate_t * (1 - rate_t)
    # Why: near 0 or 1, the plug-in variance collapses to 0, which would
    # blow up the mSPRT radius formula; floor at a tiny value so the CI
    # remains finite but very wide.
    sigma2 = max((var_c + var_t) / 2.0, 1e-6)

    tau = math.sqrt(sigma2)
    n_eff = (c_n * t_n) / (c_n + t_n)
    se = math.sqrt(var_c / c_n + var_t / t_n)

    radius, z, e_value = _msprt_core(diff, se, n_eff, sigma2, tau, alpha)
    ci_lower = diff - radius
    ci_upper = diff + radius

    if ci_lower > 0 or ci_upper < 0:
        decision = "STOP_REJECT"
        significant = True
    else:
        decision = "CONTINUE"
        significant = False

    rel_lift = diff / rate_c * 100 if rate_c > 0 else float("inf")

    if significant:
        direction = "higher" if diff > 0 else "lower"
        interp = (
            f"Sequential proportion test: treatment rate ({rate_t:.4f}) is "
            f"{direction} than control ({rate_c:.4f}), diff = {diff:+.4f} "
            f"({rel_lift:+.1f}%), AV CI [{ci_lower:.4f}, {ci_upper:.4f}]. "
            f"STOP and reject null."
        )
    else:
        interp = (
            f"Sequential proportion test: no decision yet. "
            f"Treatment ({rate_t:.4f}) vs control ({rate_c:.4f}), "
            f"diff = {diff:+.4f}, AV CI [{ci_lower:.4f}, {ci_upper:.4f}]. "
            f"CONTINUE; peek again safely."
        )

    return {
        "test": "sequential_proportion",
        "rate_control": float(rate_c),
        "rate_treatment": float(rate_t),
        "diff": float(diff),
        "relative_lift_pct": float(rel_lift),
        "ci_lower": float(ci_lower),
        "ci_upper": float(ci_upper),
        "n_control": int(c_n),
        "n_treatment": int(t_n),
        "test_stat": float(z),
        "e_value": float(e_value),
        "decision": decision,
        "significant": significant,
        "alpha": alpha,
        "interpretation": interp,
    }
