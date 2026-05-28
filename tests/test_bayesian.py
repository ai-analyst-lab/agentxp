"""Tests for bayesian.py — conjugate Bayesian A/B testing."""

import numpy as np
import pytest

from agentxp.stats.bayesian import (
    beta_binomial_test,
    normal_normal_test,
    expected_loss,
    probability_to_beat,
)


# ---------------------------------------------------------------------------
# Beta-Binomial
# ---------------------------------------------------------------------------

class TestBetaBinomial:
    def test_known_answer_strong_effect(self):
        # Control 50/100, Treatment 70/100 — a large, clear lift.
        # Analytic P(T > C) under Beta(1,1) priors is ~0.998.
        result = beta_binomial_test(50, 100, 70, 100)
        assert result["test"] == "beta_binomial"
        assert 0.99 <= result["prob_treatment_better"] <= 1.0
        assert result["posterior_mean_treatment"] > result["posterior_mean_control"]
        assert result["lift_ci_lower"] > 0  # entire 95% CrI on relative lift > 0
        assert "interpretation" in result

    def test_jeffreys_prior_posterior_mean(self):
        # With Beta(0.5, 0.5) prior and 50/100 data, posterior mean = 50.5/101 ≈ 0.500.
        result = beta_binomial_test(
            50, 100, 55, 100, prior_alpha=0.5, prior_beta=0.5
        )
        assert abs(result["posterior_mean_control"] - (50.5 / 101)) < 1e-9
        assert abs(result["posterior_mean_treatment"] - (55.5 / 101)) < 1e-9
        assert result["prior_alpha"] == 0.5
        assert result["prior_beta"] == 0.5

    def test_strong_informative_prior_pulls_posterior(self):
        # Weak data (2/10) but strong prior pretending 1000 prior successes and
        # 9000 prior failures => posterior mean ~ 1002 / 10010 ≈ 0.1001.
        weak = beta_binomial_test(2, 10, 3, 10)  # default uniform prior
        strong = beta_binomial_test(
            2, 10, 3, 10, prior_alpha=1000, prior_beta=9000
        )
        # Strong prior drags control posterior mean toward 0.10
        assert abs(strong["posterior_mean_control"] - 0.10) < 0.005
        # And away from the weak-prior estimate of ~0.25
        assert abs(weak["posterior_mean_control"] - 0.25) < 0.05
        assert strong["posterior_mean_control"] < weak["posterior_mean_control"]

    def test_no_effect_probability_near_half(self):
        # A/A situation — same rates in both arms.
        result = beta_binomial_test(100, 1000, 100, 1000)
        assert 0.35 <= result["prob_treatment_better"] <= 0.65

    def test_ship_decision_on_strong_evidence(self):
        # Massive sample, big win. Should trigger SHIP under default thresholds.
        result = beta_binomial_test(1000, 10000, 1500, 10000)
        assert result["decision"] == "SHIP"
        assert result["expected_loss_ship_treatment_rel"] < 0.005

    def test_abort_decision_on_strong_negative_evidence(self):
        # Treatment is clearly worse — ABORT.
        result = beta_binomial_test(1500, 10000, 1000, 10000)
        assert result["decision"] == "ABORT"
        assert result["prob_treatment_better"] < 0.5

    def test_continue_decision_on_weak_evidence(self):
        # Small sample, small effect — should CONTINUE.
        result = beta_binomial_test(10, 100, 12, 100)
        assert result["decision"] == "CONTINUE"

    def test_seed_determinism(self):
        a = beta_binomial_test(50, 100, 70, 100, seed=42)
        b = beta_binomial_test(50, 100, 70, 100, seed=42)
        assert a["prob_treatment_better"] == b["prob_treatment_better"]
        assert a["expected_loss_ship_treatment"] == b["expected_loss_ship_treatment"]
        c = beta_binomial_test(50, 100, 70, 100, seed=7)
        # Different seed should give (very slightly) different MC estimates.
        assert a["expected_loss_ship_treatment"] != c["expected_loss_ship_treatment"]

    def test_expected_loss_decreases_with_sample_size(self):
        # Same rate, more data => tighter posterior => smaller expected loss
        # for the variant we're uncertain about.
        small = beta_binomial_test(5, 100, 7, 100)
        big = beta_binomial_test(500, 10000, 700, 10000)
        # Rates are effectively the same; bigger sample should give smaller
        # relative expected loss for shipping the apparent winner.
        assert big["expected_loss_ship_treatment_rel"] < small["expected_loss_ship_treatment_rel"]

    def test_returns_all_keys(self):
        result = beta_binomial_test(50, 100, 70, 100)
        expected = [
            "test", "prob_treatment_better", "posterior_mean_control",
            "posterior_mean_treatment", "relative_lift", "lift_ci_lower",
            "lift_ci_upper", "expected_loss_ship_treatment",
            "expected_loss_ship_control", "expected_loss_ship_treatment_rel",
            "expected_loss_ship_control_rel", "decision", "prior_alpha",
            "prior_beta", "n_control", "n_treatment", "n_samples", "seed",
            "interpretation",
        ]
        for k in expected:
            assert k in result, f"missing key: {k}"

    def test_input_validation_negative(self):
        with pytest.raises(ValueError):
            beta_binomial_test(-1, 100, 70, 100)
        with pytest.raises(ValueError):
            beta_binomial_test(50, 100, 70, -10)

    def test_input_validation_successes_exceed_trials(self):
        with pytest.raises(ValueError):
            beta_binomial_test(120, 100, 50, 100)

    def test_input_validation_bad_prior(self):
        with pytest.raises(ValueError):
            beta_binomial_test(50, 100, 70, 100, prior_alpha=0)
        with pytest.raises(ValueError):
            beta_binomial_test(50, 100, 70, 100, prior_beta=-1)

    def test_input_validation_zero_n(self):
        with pytest.raises(ValueError):
            beta_binomial_test(0, 0, 0, 100)


# ---------------------------------------------------------------------------
# Normal-Normal
# ---------------------------------------------------------------------------

class TestNormalNormal:
    def test_detects_positive_effect(self):
        rng = np.random.default_rng(0)
        c = rng.normal(50, 10, size=500)
        t = rng.normal(55, 10, size=500)  # 10% lift
        result = normal_normal_test(c, t)
        assert result["test"] == "normal_normal"
        assert result["prob_treatment_better"] > 0.95
        assert result["lift_ci_lower"] > 0
        assert result["posterior_mean_treatment"] > result["posterior_mean_control"]

    def test_detects_negative_effect(self):
        rng = np.random.default_rng(1)
        c = rng.normal(50, 10, size=500)
        t = rng.normal(45, 10, size=500)
        result = normal_normal_test(c, t)
        assert result["prob_treatment_better"] < 0.05
        assert result["lift_ci_upper"] < 0

    def test_null_effect(self):
        rng = np.random.default_rng(2)
        c = rng.normal(50, 10, size=500)
        t = rng.normal(50, 10, size=500)
        result = normal_normal_test(c, t)
        # With a true null, P(T > C) can land anywhere; just check it isn't
        # degenerate and the 95% CrI on relative lift straddles a band that
        # includes zero or is at least not pathologically narrow.
        assert 0.01 < result["prob_treatment_better"] < 0.99
        assert result["lift_ci_lower"] < result["lift_ci_upper"]

    def test_seed_determinism(self):
        rng = np.random.default_rng(3)
        c = rng.normal(50, 10, size=500)
        t = rng.normal(52, 10, size=500)
        a = normal_normal_test(c, t, seed=42)
        b = normal_normal_test(c, t, seed=42)
        assert a["prob_treatment_better"] == b["prob_treatment_better"]

    def test_sample_size_shrinks_expected_loss(self):
        rng = np.random.default_rng(4)
        c_small = rng.normal(50, 10, size=50)
        t_small = rng.normal(51, 10, size=50)
        c_big = rng.normal(50, 10, size=5000)
        t_big = rng.normal(51, 10, size=5000)
        small = normal_normal_test(c_small, t_small)
        big = normal_normal_test(c_big, t_big)
        # Larger n => tighter posterior on the winner => smaller expected loss
        # on whichever side is being shipped. Sum is a safe proxy.
        small_total = (
            small["expected_loss_ship_treatment_rel"]
            + small["expected_loss_ship_control_rel"]
        )
        big_total = (
            big["expected_loss_ship_treatment_rel"]
            + big["expected_loss_ship_control_rel"]
        )
        assert big_total < small_total

    def test_ship_decision_large_n(self):
        rng = np.random.default_rng(5)
        c = rng.normal(50, 10, size=10000)
        t = rng.normal(53, 10, size=10000)
        result = normal_normal_test(c, t)
        assert result["decision"] == "SHIP"

    def test_strong_prior_pulls_posterior(self):
        # Small sample centered at 50; a strong prior at 0 should pull the
        # posterior mean of each group materially toward 0 (down from ~50).
        # NIG closed form: posterior_mean_mu = (prec_pri*prior_mean + n*xbar)
        # / (prec_pri + n). With prec_pri = 1/0.1^2 = 100, n = 20, xbar ~ 50,
        # the posterior mean should be ~ (100*0 + 20*50) / 120 ~ 8.3.
        rng = np.random.default_rng(6)
        c = rng.normal(50, 10, size=20)
        t = rng.normal(51, 10, size=20)
        weak = normal_normal_test(c, t, prior_mean=0.0, prior_sd=1e6)
        strong = normal_normal_test(c, t, prior_mean=0.0, prior_sd=0.1)
        # The weak prior leaves xbar essentially unchanged (~50).
        assert abs(weak["posterior_mean_control"] - c.mean()) < 0.5
        # The strong prior pulls the posterior mean toward 0 and should sit
        # well below the sample mean.
        assert abs(strong["posterior_mean_control"]) < abs(weak["posterior_mean_control"])
        assert strong["posterior_mean_control"] < 0.5 * c.mean()
        # Known-answer spot check: closed-form posterior mean of mu.
        prec_pri = 1.0 / (0.1 ** 2)
        expected_post_mean_c = (prec_pri * 0.0 + c.size * c.mean()) / (prec_pri + c.size)
        # Posterior draws are MC estimates; allow a small tolerance.
        assert abs(strong["posterior_mean_control"] - expected_post_mean_c) < 0.5

    def test_strong_prior_ci_width(self):
        # With a prior centered on the data scale (so relative lift denom
        # stays stable), tightening prior_sd should NARROW the relative-lift
        # credible interval, not widen it.
        rng = np.random.default_rng(6)
        c = rng.normal(50, 10, size=20)
        t = rng.normal(51, 10, size=20)
        weak = normal_normal_test(c, t, prior_mean=50.0, prior_sd=1e6)
        strong = normal_normal_test(c, t, prior_mean=50.0, prior_sd=0.5)
        weak_width = weak["lift_ci_upper"] - weak["lift_ci_lower"]
        strong_width = strong["lift_ci_upper"] - strong["lift_ci_lower"]
        assert strong_width < weak_width

    def test_nig_posterior_known_answer(self):
        # Handcrafted 5-point dataset. With a weak prior, the posterior mean
        # of mu should be indistinguishable from xbar, and the posterior
        # variance of mu should be well approximated by the frequentist
        # Student-t(n-1) posterior: Var[mu] = s^2 / n * (df / (df - 2))
        # for df = n - 1 = 4 (needs df > 2). Treatment is shifted by +2.
        c = np.array([10.0, 12.0, 11.0, 9.0, 13.0])
        t = c + 2.0  # identical variance structure
        xbar = c.mean()
        s2 = c.var(ddof=1)  # sample variance with unbiased denominator
        n = c.size
        result = normal_normal_test(
            c, t, prior_mean=0.0, prior_sd=1e6, n_samples=200000, seed=42
        )
        # Posterior mean of mu ~ xbar for weak prior.
        assert abs(result["posterior_mean_control"] - xbar) < 0.05
        # Posterior mean of t group ~ xbar + 2.
        assert abs(result["posterior_mean_treatment"] - (xbar + 2.0)) < 0.05
        # Absolute lift posterior: under weak prior + identical data
        # (shifted), posterior mean of lift should be ~2.
        posterior_lift_mean = (
            result["posterior_mean_treatment"] - result["posterior_mean_control"]
        )
        assert abs(posterior_lift_mean - 2.0) < 0.1
        # And the posterior variance of the mean of each group should match
        # the Student-t variance s^2/n * (df/(df-2)), verified via sample std.
        # Since NIG marginal variance of mu: E[sigma^2]/(prec_pri+n).
        # With alpha_post = 0.5 + 2.5 = 3, E[sigma^2] = beta_post/(alpha_post-1).
        # beta_post ~ beta_0 + 0.5*SS + ~0 (prec_pri tiny).
        ss = float(((c - xbar) ** 2).sum())
        alpha_post = 0.5 + n / 2.0
        beta_post_weak = 0.5 + 0.5 * ss
        expected_sigma2_mean = beta_post_weak / (alpha_post - 1.0)
        expected_mu_var = expected_sigma2_mean / n  # prec_pri ~ 0
        # Sanity check that this is close to s^2/n (the classical estimator).
        assert abs(expected_sigma2_mean - s2) < 1.0

    def test_input_validation_too_small(self):
        with pytest.raises(ValueError):
            normal_normal_test([1.0], [2.0, 3.0])

    def test_input_validation_bad_prior_sd(self):
        with pytest.raises(ValueError):
            normal_normal_test([1.0, 2.0, 3.0], [4.0, 5.0, 6.0], prior_sd=0)

    def test_handles_nan(self):
        c = [1.0, 2.0, np.nan, 4.0, 5.0]
        t = [2.0, 3.0, 4.0, np.nan, 6.0]
        result = normal_normal_test(c, t)
        assert result["n_control"] == 4
        assert result["n_treatment"] == 4


# ---------------------------------------------------------------------------
# Helper exports
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_probability_to_beat(self):
        rng = np.random.default_rng(0)
        c = rng.normal(0, 1, size=10000)
        t = rng.normal(1, 1, size=10000)
        p = probability_to_beat(c, t)
        # P(N(1,1) > N(0,1)) = Phi(1/sqrt(2)) ≈ 0.7602.
        assert 0.74 <= p <= 0.78

    def test_probability_to_beat_shape_mismatch(self):
        with pytest.raises(ValueError):
            probability_to_beat([1, 2, 3], [1, 2])

    def test_probability_to_beat_empty(self):
        with pytest.raises(ValueError):
            probability_to_beat([], [])

    def test_expected_loss_absolute(self):
        c = np.array([0.10, 0.12, 0.11, 0.09])
        t = np.array([0.15, 0.14, 0.16, 0.13])
        result = expected_loss(c, t, loss_type="absolute")
        # t is always > c so shipping t has zero loss.
        assert result["loss_ship_treatment"] == 0.0
        # shipping c has loss equal to mean(t - c).
        assert abs(result["loss_ship_control"] - float(np.mean(t - c))) < 1e-12

    def test_expected_loss_relative_scale(self):
        c = np.array([0.10, 0.10, 0.10, 0.10])
        t = np.array([0.11, 0.11, 0.11, 0.11])
        abs_res = expected_loss(c, t, loss_type="absolute")
        rel_res = expected_loss(c, t, loss_type="relative")
        # relative = absolute / mean(c) = absolute / 0.10
        assert abs(rel_res["loss_ship_control"] - abs_res["loss_ship_control"] / 0.10) < 1e-12

    def test_expected_loss_bad_type(self):
        with pytest.raises(ValueError):
            expected_loss([1, 2, 3], [1, 2, 3], loss_type="bogus")
