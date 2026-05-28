"""Tests for cuped.py — CUPED variance reduction."""

import math

import numpy as np
import pytest

from agentxp.stats.ab_tests import welch_test
from agentxp.stats.cuped import (
    cuped_adjust,
    cuped_welch_test,
    variance_reduction,
)


def _correlated_pair(n, rho, rng, pre_mean=100.0, pre_std=10.0, post_std=10.0):
    """Generate (pre, post) with approximate correlation rho."""
    z1 = rng.standard_normal(n)
    z2 = rng.standard_normal(n)
    pre = pre_mean + pre_std * z1
    post_noise = rho * z1 + math.sqrt(max(0.0, 1 - rho * rho)) * z2
    post = pre_mean + post_std * post_noise
    return pre, post


class TestVarianceReduction:
    def test_high_correlation_reduces_variance(self):
        rng = np.random.default_rng(42)
        pre, post = _correlated_pair(5000, rho=0.7, rng=rng)
        result = variance_reduction(pre, post)
        # rho^2 ~= 0.49
        assert abs(result["correlation"] - 0.7) < 0.05
        assert abs(result["variance_reduction_pct"] - 49.0) < 5.0
        assert "interpretation" in result

    def test_zero_correlation_gives_zero_reduction(self):
        rng = np.random.default_rng(7)
        pre = rng.normal(100, 10, 5000)
        post = rng.normal(100, 10, 5000)  # independent
        result = variance_reduction(pre, post)
        assert abs(result["correlation"]) < 0.05
        assert result["variance_reduction_pct"] < 2.0

    def test_mismatched_lengths_raises(self):
        with pytest.raises(ValueError, match="same length"):
            variance_reduction([1, 2, 3], [1, 2, 3, 4])

    def test_nan_raises(self):
        with pytest.raises(ValueError, match="NaN"):
            variance_reduction([1.0, 2.0, np.nan], [1.0, 2.0, 3.0])

    def test_identical_raises(self):
        with pytest.raises(ValueError, match="identical"):
            variance_reduction([1.0, 2.0, 3.0, 4.0], [1.0, 2.0, 3.0, 4.0])


class TestCupedAdjust:
    def test_theta_closed_form_on_tiny_example(self):
        # Handcrafted: pre = [1..10], post = 2*pre + 1 exactly.
        # Cov(post, pre) / Var(pre) = 2 exactly.
        pre = np.arange(1.0, 11.0)
        post = 2.0 * pre + 1.0
        result = cuped_adjust(pre, post)
        assert abs(result["theta"] - 2.0) < 1e-9
        # rho should be 1.0
        assert abs(result["correlation"] - 1.0) < 1e-9
        assert abs(result["variance_reduction_pct"] - 100.0) < 1e-6
        # Adjusted outcomes should equal post - 2*(pre - mean(pre))
        expected = post - 2.0 * (pre - pre.mean())
        np.testing.assert_allclose(result["y_adjusted"], expected)

    def test_adjust_with_treatment_splits_groups(self):
        rng = np.random.default_rng(5)
        n = 200
        pre, post = _correlated_pair(n, rho=0.6, rng=rng)
        treatment = np.array([0] * 100 + [1] * 100)
        result = cuped_adjust(pre, post, treatment=treatment)
        assert "control_adjusted" in result
        assert "treatment_adjusted" in result
        assert len(result["control_adjusted"]) == 100
        assert len(result["treatment_adjusted"]) == 100
        assert result["n_control"] == 100
        assert result["n_treatment"] == 100

    def test_adjust_mismatched_lengths_raises(self):
        with pytest.raises(ValueError, match="same length"):
            cuped_adjust([1, 2, 3, 4], [1, 2, 3])

    def test_adjust_nan_raises(self):
        with pytest.raises(ValueError, match="NaN"):
            cuped_adjust([1.0, 2.0, 3.0], [1.0, np.nan, 3.0])

    def test_zero_variance_covariate_returns_theta_zero(self):
        # Covariate constant => Var(y_pre) = 0 => theta is undefined.
        # Documented behavior: _compute_theta returns 0.0, so the adjusted
        # outcome equals y_post unchanged and correlation is 0.
        pre = np.array([5.0, 5.0, 5.0, 5.0, 5.0])
        post = np.array([10.0, 11.0, 12.0, 13.0, 14.0])
        result = cuped_adjust(pre, post)
        assert result["theta"] == 0.0
        assert result["correlation"] == 0.0
        assert result["variance_reduction_pct"] == 0.0
        # Adjusted outcome collapses to raw post when theta is 0.
        np.testing.assert_allclose(result["y_adjusted"], post)

    def test_zero_variance_covariate_variance_reduction(self):
        # variance_reduction helper on a constant covariate: rho = 0, no
        # variance reduction expected.
        pre = np.array([5.0, 5.0, 5.0, 5.0, 5.0])
        post = np.array([10.0, 11.0, 12.0, 13.0, 14.0])
        result = variance_reduction(pre, post)
        assert result["correlation"] == 0.0
        assert result["variance_reduction_pct"] == 0.0


class TestCupedWelchTest:
    def test_cuped_narrower_ci_than_raw_when_correlated(self):
        rng = np.random.default_rng(123)
        n = 2000
        # Shared pre, correlated post, inject known treatment effect
        c_pre, c_post = _correlated_pair(n, rho=0.8, rng=rng)
        t_pre, t_post = _correlated_pair(n, rho=0.8, rng=rng)
        t_post = t_post + 2.0  # true treatment effect

        cuped = cuped_welch_test(c_pre, c_post, t_pre, t_post)
        raw = welch_test(c_post, t_post)

        # CUPED CI should be narrower
        raw_width = raw["ci_upper"] - raw["ci_lower"]
        cuped_width = cuped["ci_upper"] - cuped["ci_lower"]
        assert cuped_width < raw_width
        # Realized variance reduction should be positive
        assert cuped["variance_reduction_pct"] > 20.0
        # Both should detect the effect
        assert cuped["significant"] is True
        assert cuped["unadjusted_p_value"] is not None
        # Theta near 1 (since post_std == pre_std * rho in generator)
        assert abs(cuped["theta"] - 0.8) < 0.1

    def test_cuped_returns_interpretation_and_theta(self):
        rng = np.random.default_rng(11)
        n = 500
        c_pre, c_post = _correlated_pair(n, rho=0.5, rng=rng)
        t_pre, t_post = _correlated_pair(n, rho=0.5, rng=rng)
        result = cuped_welch_test(c_pre, c_post, t_pre, t_post)
        for key in [
            "theta",
            "p_value",
            "ci_lower",
            "ci_upper",
            "variance_reduction_pct",
            "expected_variance_reduction_pct",
            "unadjusted_p_value",
            "interpretation",
        ]:
            assert key in result

    def test_cuped_welch_insufficient_data(self):
        result = cuped_welch_test([1.0], [2.0], [3.0], [4.0])
        assert result.get("error")
        assert result["significant"] is False

    def test_cuped_welch_mismatched_group_lengths_raises(self):
        with pytest.raises(ValueError, match="same length"):
            cuped_welch_test([1.0, 2.0, 3.0], [1.0, 2.0], [1.0, 2.0], [1.0, 2.0])
