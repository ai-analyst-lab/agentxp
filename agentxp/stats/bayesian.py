"""
Bayesian A/B testing via conjugate priors.

Classic conjugate Bayesian analysis — no MCMC. Two metric types:

1. Beta-Binomial (for conversion rates / CTRs):
     prior:      Beta(alpha, beta)
     likelihood: Binomial(n, p)
     posterior:  Beta(alpha + successes, beta + failures)

2. Normal-Normal with unknown variance (for revenue, time-on-page, etc.):
     prior on mean:     N(prior_mean, prior_sd^2)
     prior on variance: Inverse-Gamma (implicit, from data)
     Posterior sampled via the Normal-Inverse-Gamma (NIG) conjugate update.
     With a weak prior (prior_sd -> infty) this reduces to the Student-t
     posterior for the mean.

For each test we compute:
  - P(treatment > control) from posterior draws
  - 95% credible interval on relative lift
  - Expected loss under shipping treatment (risk if treatment is actually worse)
  - Expected loss under shipping control (risk if control is actually worse)
  - Decision (SHIP / ABORT / CONTINUE) based on expected-loss thresholds
  - A plain-language `interpretation` string

Expected loss is the industry-standard Bayesian stopping criterion (GrowthBook,
VWO, Dynamic Yield): ship when the expected cost of being wrong is below a
"threshold of caring" (default 0.5% relative). This is a decision-theoretic
framing — you stop when the worst-case regret is small enough to tolerate.
"""

from __future__ import annotations

import numpy as np
from scipy import stats

# Default decision thresholds — expressed as relative expected loss (fraction
# of control mean / control rate). 0.005 = 0.5%, a common industry default.
DEFAULT_LOSS_THRESHOLD_SHIP = 0.005
DEFAULT_LOSS_THRESHOLD_ABORT = 0.005


# ---------------------------------------------------------------------------
# Utilities exposed for agent use and internal reuse
# ---------------------------------------------------------------------------

def probability_to_beat(
    posterior_samples_c: np.ndarray,
    posterior_samples_t: np.ndarray,
) -> float:
    """P(treatment > control) estimated from posterior samples.

    Args:
        posterior_samples_c: draws from the control posterior.
        posterior_samples_t: draws from the treatment posterior.

    Returns:
        Monte Carlo estimate of P(T > C) as a float in [0, 1].
    """
    c = np.asarray(posterior_samples_c, dtype=float)
    t = np.asarray(posterior_samples_t, dtype=float)
    if c.shape != t.shape:
        raise ValueError(
            f"posterior sample arrays must have the same shape, "
            f"got {c.shape} vs {t.shape}"
        )
    if c.size == 0:
        raise ValueError("posterior sample arrays must be non-empty")
    return float(np.mean(t > c))


def expected_loss(
    posterior_samples_c: np.ndarray,
    posterior_samples_t: np.ndarray,
    loss_type: str = "absolute",
) -> dict:
    """Expected loss from shipping each variant.

    Under a 0/1 decision loss with absolute regret:

        loss_ship_treatment = E[max(c - t, 0)]      # cost if we pick T and C wins
        loss_ship_control   = E[max(t - c, 0)]      # cost if we pick C and T wins

    "relative" expresses each loss as a fraction of the control mean (useful
    as a unit-free "threshold of caring").

    Args:
        posterior_samples_c: draws from control posterior.
        posterior_samples_t: draws from treatment posterior.
        loss_type: "absolute" or "relative".

    Returns:
        dict with keys: loss_ship_treatment, loss_ship_control, loss_type.
    """
    if loss_type not in ("absolute", "relative"):
        raise ValueError(
            f"loss_type must be 'absolute' or 'relative', got {loss_type!r}"
        )
    c = np.asarray(posterior_samples_c, dtype=float)
    t = np.asarray(posterior_samples_t, dtype=float)
    if c.shape != t.shape:
        raise ValueError(
            f"posterior sample arrays must have the same shape, "
            f"got {c.shape} vs {t.shape}"
        )
    if c.size == 0:
        raise ValueError("posterior sample arrays must be non-empty")

    loss_ship_t = float(np.mean(np.maximum(c - t, 0.0)))
    loss_ship_c = float(np.mean(np.maximum(t - c, 0.0)))

    if loss_type == "relative":
        denom = float(np.mean(c))
        scale = abs(denom) if denom != 0 else 1.0
        loss_ship_t = loss_ship_t / scale
        loss_ship_c = loss_ship_c / scale

    return {
        "loss_ship_treatment": loss_ship_t,
        "loss_ship_control": loss_ship_c,
        "loss_type": loss_type,
    }


def _decide(
    loss_ship_t_rel: float,
    loss_ship_c_rel: float,
    prob_t_beats_c: float,
    threshold_ship: float,
    threshold_abort: float,
) -> str:
    """Decision rule based on relative expected loss.

    - SHIP: shipping treatment has tiny expected loss AND treatment is probably better.
    - ABORT: shipping control has tiny expected loss AND control is probably better
      (i.e. treatment is likely worse).
    - CONTINUE: not enough evidence either way.
    """
    if loss_ship_t_rel < threshold_ship and prob_t_beats_c >= 0.5:
        return "SHIP"
    if loss_ship_c_rel < threshold_abort and prob_t_beats_c < 0.5:
        return "ABORT"
    return "CONTINUE"


def _relative_lift_samples(
    samples_c: np.ndarray,
    samples_t: np.ndarray,
) -> np.ndarray:
    """Relative lift draws (t - c) / |c|, with safe handling of c ≈ 0."""
    denom = np.where(np.abs(samples_c) < 1e-12, np.nan, np.abs(samples_c))
    return (samples_t - samples_c) / denom


# ---------------------------------------------------------------------------
# Beta-Binomial test
# ---------------------------------------------------------------------------

def beta_binomial_test(
    c_success: int,
    c_n: int,
    t_success: int,
    t_n: int,
    prior_alpha: float = 1.0,
    prior_beta: float = 1.0,
    n_samples: int = 50000,
    seed: int = 42,
    loss_threshold_ship: float = DEFAULT_LOSS_THRESHOLD_SHIP,
    loss_threshold_abort: float = DEFAULT_LOSS_THRESHOLD_ABORT,
) -> dict:
    """Bayesian A/B test for a binary metric (conversion rate, CTR).

    Uses the Beta-Binomial conjugate model. The default Beta(1, 1) prior is
    uniform on [0, 1] (GrowthBook's default). Use Beta(0.5, 0.5) for the
    Jeffreys prior, or a strong informative prior like Beta(100, 900) to
    anchor a baseline 10% rate.

    Args:
        c_success: control successes (non-negative integer).
        c_n: control trials (positive integer, >= c_success).
        t_success: treatment successes.
        t_n: treatment trials.
        prior_alpha: prior alpha parameter (> 0, applied to both groups).
        prior_beta: prior beta parameter (> 0).
        n_samples: Monte Carlo sample count for posterior integration.
        seed: RNG seed for reproducibility.
        loss_threshold_ship: relative expected loss threshold for SHIP.
        loss_threshold_abort: relative expected loss threshold for ABORT.

    Returns:
        dict with: test, prob_treatment_better, lift_ci_lower, lift_ci_upper,
        posterior_mean_control, posterior_mean_treatment, relative_lift,
        expected_loss_ship_treatment, expected_loss_ship_control,
        expected_loss_ship_treatment_rel, expected_loss_ship_control_rel,
        decision, prior_alpha, prior_beta, n_samples, seed, interpretation.
    """
    # --- input validation -------------------------------------------------
    for name, val in [
        ("c_success", c_success),
        ("c_n", c_n),
        ("t_success", t_success),
        ("t_n", t_n),
    ]:
        if not isinstance(val, (int, np.integer)):
            raise TypeError(f"{name} must be an integer, got {type(val).__name__}")
        if val < 0:
            raise ValueError(f"{name} must be non-negative, got {val}")
    if c_n <= 0 or t_n <= 0:
        raise ValueError("c_n and t_n must be positive")
    if c_success > c_n or t_success > t_n:
        raise ValueError("successes cannot exceed trials")
    if prior_alpha <= 0 or prior_beta <= 0:
        raise ValueError("prior_alpha and prior_beta must be > 0")
    if n_samples <= 0:
        raise ValueError("n_samples must be positive")

    rng = np.random.default_rng(seed)

    post_alpha_c = prior_alpha + c_success
    post_beta_c = prior_beta + (c_n - c_success)
    post_alpha_t = prior_alpha + t_success
    post_beta_t = prior_beta + (t_n - t_success)

    samples_c = rng.beta(post_alpha_c, post_beta_c, size=n_samples)
    samples_t = rng.beta(post_alpha_t, post_beta_t, size=n_samples)

    prob_t_beats_c = float(np.mean(samples_t > samples_c))
    posterior_mean_c = post_alpha_c / (post_alpha_c + post_beta_c)
    posterior_mean_t = post_alpha_t / (post_alpha_t + post_beta_t)

    lift_samples = _relative_lift_samples(samples_c, samples_t)
    lift_samples_clean = lift_samples[~np.isnan(lift_samples)]
    if lift_samples_clean.size == 0:
        lift_ci_lower, lift_ci_upper, rel_lift_point = float("nan"), float("nan"), float("nan")
    else:
        lift_ci_lower = float(np.quantile(lift_samples_clean, 0.025))
        lift_ci_upper = float(np.quantile(lift_samples_clean, 0.975))
        rel_lift_point = (posterior_mean_t - posterior_mean_c) / abs(posterior_mean_c) \
            if posterior_mean_c != 0 else float("inf")

    loss_abs = expected_loss(samples_c, samples_t, loss_type="absolute")
    loss_rel = expected_loss(samples_c, samples_t, loss_type="relative")

    decision = _decide(
        loss_ship_t_rel=loss_rel["loss_ship_treatment"],
        loss_ship_c_rel=loss_rel["loss_ship_control"],
        prob_t_beats_c=prob_t_beats_c,
        threshold_ship=loss_threshold_ship,
        threshold_abort=loss_threshold_abort,
    )

    if decision == "SHIP":
        interp = (
            f"SHIP treatment. P(T > C) = {prob_t_beats_c:.3f}, "
            f"posterior rates {posterior_mean_c:.4f} -> {posterior_mean_t:.4f} "
            f"(lift {rel_lift_point:+.1%}, 95% CrI [{lift_ci_lower:+.1%}, {lift_ci_upper:+.1%}]). "
            f"Relative expected loss from shipping T is "
            f"{loss_rel['loss_ship_treatment']:.4%}, below threshold "
            f"{loss_threshold_ship:.2%}."
        )
    elif decision == "ABORT":
        interp = (
            f"ABORT. Treatment is likely worse: P(T > C) = {prob_t_beats_c:.3f}, "
            f"posterior rates {posterior_mean_c:.4f} -> {posterior_mean_t:.4f} "
            f"(lift {rel_lift_point:+.1%}, 95% CrI [{lift_ci_lower:+.1%}, {lift_ci_upper:+.1%}]). "
            f"Relative expected loss from shipping C is "
            f"{loss_rel['loss_ship_control']:.4%}, below threshold "
            f"{loss_threshold_abort:.2%}."
        )
    else:
        interp = (
            f"CONTINUE. Not enough evidence yet. P(T > C) = {prob_t_beats_c:.3f}, "
            f"posterior rates {posterior_mean_c:.4f} -> {posterior_mean_t:.4f} "
            f"(lift {rel_lift_point:+.1%}, 95% CrI [{lift_ci_lower:+.1%}, {lift_ci_upper:+.1%}]). "
            f"Relative expected loss ship-T = {loss_rel['loss_ship_treatment']:.4%}, "
            f"ship-C = {loss_rel['loss_ship_control']:.4%}."
        )

    return {
        "test": "beta_binomial",
        "prob_treatment_better": prob_t_beats_c,
        "posterior_mean_control": float(posterior_mean_c),
        "posterior_mean_treatment": float(posterior_mean_t),
        "relative_lift": float(rel_lift_point),
        "lift_ci_lower": float(lift_ci_lower),
        "lift_ci_upper": float(lift_ci_upper),
        "expected_loss_ship_treatment": loss_abs["loss_ship_treatment"],
        "expected_loss_ship_control": loss_abs["loss_ship_control"],
        "expected_loss_ship_treatment_rel": loss_rel["loss_ship_treatment"],
        "expected_loss_ship_control_rel": loss_rel["loss_ship_control"],
        "decision": decision,
        "prior_alpha": float(prior_alpha),
        "prior_beta": float(prior_beta),
        "posterior_alpha_control": float(post_alpha_c),
        "posterior_beta_control": float(post_beta_c),
        "posterior_alpha_treatment": float(post_alpha_t),
        "posterior_beta_treatment": float(post_beta_t),
        "n_control": int(c_n),
        "n_treatment": int(t_n),
        "n_samples": int(n_samples),
        "seed": int(seed),
        "loss_threshold_ship": float(loss_threshold_ship),
        "loss_threshold_abort": float(loss_threshold_abort),
        "interpretation": interp,
    }


# ---------------------------------------------------------------------------
# Normal-Normal test (unknown variance via NIG)
# ---------------------------------------------------------------------------

def normal_normal_test(
    control,
    treatment,
    prior_mean: float = 0.0,
    prior_sd: float = 1e6,
    n_samples: int = 50000,
    seed: int = 42,
    loss_threshold_ship: float = DEFAULT_LOSS_THRESHOLD_SHIP,
    loss_threshold_abort: float = DEFAULT_LOSS_THRESHOLD_ABORT,
) -> dict:
    """Bayesian A/B test for a continuous metric.

    Uses the Normal model with unknown variance. Variance is estimated from
    data with an (implicit) non-informative Jeffreys prior on sigma^2, so the
    posterior for each group's mean is a scaled-and-shifted Student-t with
    df = n - 1. The Gaussian prior on the mean is combined via a standard
    conjugate update, which blends the prior with the Student-t likelihood.

    With the default weak prior (prior_sd = 1e6), the posterior is
    effectively the textbook Student-t(n-1) posterior on the mean.

    Args:
        control: array-like of control-group values.
        treatment: array-like of treatment-group values.
        prior_mean: prior mean (same for both groups).
        prior_sd: prior standard deviation on the mean. Use a large value for
            a weakly informative prior.
        n_samples: Monte Carlo sample count.
        seed: RNG seed.
        loss_threshold_ship: relative expected loss threshold for SHIP.
        loss_threshold_abort: relative expected loss threshold for ABORT.

    Returns:
        dict with keys analogous to beta_binomial_test, plus sample means and
        sample SDs per group.
    """
    c = np.asarray(control, dtype=float)
    t = np.asarray(treatment, dtype=float)
    c = c[~np.isnan(c)]
    t = t[~np.isnan(t)]

    if c.size < 2 or t.size < 2:
        raise ValueError("need at least 2 observations in each group")
    if prior_sd <= 0:
        raise ValueError("prior_sd must be > 0")
    if n_samples <= 0:
        raise ValueError("n_samples must be positive")

    rng = np.random.default_rng(seed)

    # Normal-Inverse-Gamma (NIG) conjugate prior hyperparameters.
    # Variance prior: sigma^2 ~ InverseGamma(alpha_0=0.5, beta_0=0.5) — a
    # *proper*, weakly-informative prior (equivalently nu_0 = 1 prior degree
    # of freedom). This is NOT the Jeffreys prior: Jeffreys for a scale is the
    # improper limit alpha_0, beta_0 -> 0, and the flat-variance reference
    # prior that yields an exact Student-t(n-1) posterior is alpha_0 = -1/2,
    # beta_0 = 0. We deliberately use a proper prior so the posterior is well
    # defined for tiny n; with n large the data dominate and the marginal
    # posterior on mu is close to the textbook Student-t(n-1).
    # The prior precision on mu is encoded in prior_sd: prec_pri = 1/prior_sd^2.
    alpha_0 = 0.5
    beta_0 = 0.5
    prec_pri = 1.0 / (prior_sd ** 2)

    def _posterior_samples(x: np.ndarray) -> np.ndarray:
        """Draw posterior samples of the mean for one group using NIG conjugacy.

        Model: x_i ~ N(mu, sigma^2), mu ~ N(prior_mean, prior_sd^2),
        sigma^2 ~ InverseGamma(alpha_0, beta_0).

        Posterior (Normal-Inverse-Gamma conjugate update):
            posterior_mean_mu = (prec_pri*prior_mean + n*xbar) / (prec_pri + n)
            alpha_post = alpha_0 + n/2
            beta_post  = beta_0 + 0.5*SS + 0.5*(prec_pri*n/(prec_pri+n))*(xbar-prior_mean)^2
            sigma^2 | x  ~ InverseGamma(alpha_post, beta_post)
            mu | sigma^2, x ~ N(posterior_mean_mu, sigma^2/(prec_pri + n))

        Under a weak mean prior (prec_pri -> 0) the marginal posterior on mu
        is Student-t with 2*alpha_post = n + 1 df, centered at xbar; for large
        n this is close to the textbook Student-t(n-1) posterior (xbar, s^2/n)
        for the unknown-variance case. (The small df/scale offset comes from
        the proper InverseGamma(0.5, 0.5) variance prior; see above.)
        """
        n = x.size
        xbar = float(x.mean())
        ss = float(np.sum((x - xbar) ** 2))  # sum of squared deviations

        posterior_mean_mu = (prec_pri * prior_mean + n * xbar) / (prec_pri + n)
        alpha_post = alpha_0 + n / 2.0
        beta_post = (
            beta_0
            + 0.5 * ss
            + 0.5 * (prec_pri * n / (prec_pri + n)) * (xbar - prior_mean) ** 2
        )

        # Draw sigma^2 ~ InverseGamma(alpha_post, beta_post).
        # numpy has Gamma; InvGamma(a, b) is 1 / Gamma(shape=a, scale=1/b).
        gamma_draws = rng.gamma(shape=alpha_post, scale=1.0 / beta_post, size=n_samples)
        sigma2_draws = 1.0 / gamma_draws

        # Draw mu | sigma^2 ~ N(posterior_mean_mu, sigma^2 / (prec_pri + n)).
        sd_mu = np.sqrt(sigma2_draws / (prec_pri + n))
        z = rng.standard_normal(size=n_samples)
        return posterior_mean_mu + sd_mu * z

    samples_c = _posterior_samples(c)
    samples_t = _posterior_samples(t)

    prob_t_beats_c = float(np.mean(samples_t > samples_c))
    posterior_mean_c = float(np.mean(samples_c))
    posterior_mean_t = float(np.mean(samples_t))

    lift_samples = _relative_lift_samples(samples_c, samples_t)
    lift_samples_clean = lift_samples[~np.isnan(lift_samples)]
    if lift_samples_clean.size == 0:
        lift_ci_lower, lift_ci_upper, rel_lift_point = float("nan"), float("nan"), float("nan")
    else:
        lift_ci_lower = float(np.quantile(lift_samples_clean, 0.025))
        lift_ci_upper = float(np.quantile(lift_samples_clean, 0.975))
        rel_lift_point = (posterior_mean_t - posterior_mean_c) / abs(posterior_mean_c) \
            if posterior_mean_c != 0 else float("inf")

    loss_abs = expected_loss(samples_c, samples_t, loss_type="absolute")
    loss_rel = expected_loss(samples_c, samples_t, loss_type="relative")

    decision = _decide(
        loss_ship_t_rel=loss_rel["loss_ship_treatment"],
        loss_ship_c_rel=loss_rel["loss_ship_control"],
        prob_t_beats_c=prob_t_beats_c,
        threshold_ship=loss_threshold_ship,
        threshold_abort=loss_threshold_abort,
    )

    if decision == "SHIP":
        interp = (
            f"SHIP treatment. P(T > C) = {prob_t_beats_c:.3f}, "
            f"posterior means {posterior_mean_c:.4f} -> {posterior_mean_t:.4f} "
            f"(lift {rel_lift_point:+.1%}, 95% CrI [{lift_ci_lower:+.1%}, {lift_ci_upper:+.1%}]). "
            f"Relative expected loss from shipping T is "
            f"{loss_rel['loss_ship_treatment']:.4%}, below threshold "
            f"{loss_threshold_ship:.2%}."
        )
    elif decision == "ABORT":
        interp = (
            f"ABORT. Treatment is likely worse: P(T > C) = {prob_t_beats_c:.3f}, "
            f"posterior means {posterior_mean_c:.4f} -> {posterior_mean_t:.4f} "
            f"(lift {rel_lift_point:+.1%}, 95% CrI [{lift_ci_lower:+.1%}, {lift_ci_upper:+.1%}]). "
            f"Relative expected loss from shipping C is "
            f"{loss_rel['loss_ship_control']:.4%}."
        )
    else:
        interp = (
            f"CONTINUE. Not enough evidence. P(T > C) = {prob_t_beats_c:.3f}, "
            f"posterior means {posterior_mean_c:.4f} -> {posterior_mean_t:.4f} "
            f"(lift {rel_lift_point:+.1%}, 95% CrI [{lift_ci_lower:+.1%}, {lift_ci_upper:+.1%}]). "
            f"ship-T rel loss = {loss_rel['loss_ship_treatment']:.4%}, "
            f"ship-C rel loss = {loss_rel['loss_ship_control']:.4%}."
        )

    return {
        "test": "normal_normal",
        "prob_treatment_better": prob_t_beats_c,
        "posterior_mean_control": posterior_mean_c,
        "posterior_mean_treatment": posterior_mean_t,
        "sample_mean_control": float(c.mean()),
        "sample_mean_treatment": float(t.mean()),
        "sample_sd_control": float(c.std(ddof=1)),
        "sample_sd_treatment": float(t.std(ddof=1)),
        "relative_lift": float(rel_lift_point),
        "lift_ci_lower": float(lift_ci_lower),
        "lift_ci_upper": float(lift_ci_upper),
        "expected_loss_ship_treatment": loss_abs["loss_ship_treatment"],
        "expected_loss_ship_control": loss_abs["loss_ship_control"],
        "expected_loss_ship_treatment_rel": loss_rel["loss_ship_treatment"],
        "expected_loss_ship_control_rel": loss_rel["loss_ship_control"],
        "decision": decision,
        "prior_mean": float(prior_mean),
        "prior_sd": float(prior_sd),
        "n_control": int(c.size),
        "n_treatment": int(t.size),
        "n_samples": int(n_samples),
        "seed": int(seed),
        "loss_threshold_ship": float(loss_threshold_ship),
        "loss_threshold_abort": float(loss_threshold_abort),
        "interpretation": interp,
    }
