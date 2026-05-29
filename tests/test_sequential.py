"""Tests for sequential.py — always-valid sequential testing."""

import math

import numpy as np
import pytest
from scipy import stats as scipy_stats

from agentxp.stats.sequential import (
    msprt_test,
    always_valid_ci,
    group_sequential_boundaries,
    sequential_proportion_test,
)


class TestMsprt:
    def test_type_i_rate_under_peeking(self):
        """Simulated null: Type I rate under repeated peeking must be <= alpha."""
        rng = np.random.default_rng(42)
        n_reps = 500
        alpha = 0.05
        false_rejects = 0

        # Peek schedule: check every 50 obs from n=100 to n=1000.
        peek_points = list(range(100, 1001, 50))

        for _ in range(n_reps):
            ctrl_full = rng.normal(0.0, 1.0, 1000)
            treat_full = rng.normal(0.0, 1.0, 1000)
            rejected = False
            for n in peek_points:
                res = msprt_test(ctrl_full[:n], treat_full[:n], alpha=alpha)
                if res.get("decision") == "STOP_REJECT":
                    rejected = True
                    break
            if rejected:
                false_rejects += 1

        rate = false_rejects / n_reps
        # Always-valid: rate should be <= alpha. Allow small Monte Carlo slack.
        assert rate <= alpha + 0.02, (
            f"Type I rate under peeking = {rate:.3f} > alpha = {alpha} "
            f"(with slack). Sequential guarantee violated."
        )

    def test_type_i_rate_peeking_from_tiny_n(self):
        """Peeking from n=2 must still control Type-I via the min_n floor.

        Without the floor, re-plugging the noisy running variance into the
        mixture at small n inflates the realized rate to ~0.10-0.13. The floor
        refuses to STOP until both groups reach min_n, restoring control.
        """
        rng = np.random.default_rng(11)
        n_reps = 600
        alpha = 0.05
        false_rejects = 0
        peek_points = list(range(2, 1001, 10))  # start at n=2

        for _ in range(n_reps):
            ctrl_full = rng.normal(0.0, 1.0, 1000)
            treat_full = rng.normal(0.0, 1.0, 1000)
            for n in peek_points:
                if msprt_test(ctrl_full[:n], treat_full[:n], alpha=alpha)[
                    "decision"
                ] == "STOP_REJECT":
                    false_rejects += 1
                    break

        rate = false_rejects / n_reps
        assert rate <= alpha + 0.02, (
            f"Type I peeking from n=2 = {rate:.3f} > alpha+slack; the small-n "
            f"floor is not protecting the guarantee."
        )

    def test_below_min_n_never_stops_even_on_huge_effect(self):
        """A clear effect below the floor must hold at CONTINUE; min_n=2 frees it."""
        ctrl = np.zeros(10)
        treat = np.ones(10) * 5.0
        held = msprt_test(ctrl, treat, alpha=0.05)
        assert held["decision"] == "CONTINUE"
        assert held["significant"] is False
        freed = msprt_test(ctrl, treat, alpha=0.05, min_n=2)
        assert freed["decision"] == "STOP_REJECT"

    def test_always_valid_ci_wider_than_fixed(self):
        """Always-valid CI must be strictly wider than fixed-horizon CI."""
        rng = np.random.default_rng(7)
        ctrl = rng.normal(0.0, 1.0, 500)
        treat = rng.normal(0.2, 1.0, 500)

        av = always_valid_ci(ctrl, treat, alpha=0.05)
        av_width = av["width"]

        # Fixed-horizon width at the same sample.
        diff = treat.mean() - ctrl.mean()
        se = math.sqrt(ctrl.var(ddof=1) / len(ctrl) + treat.var(ddof=1) / len(treat))
        z = scipy_stats.norm.ppf(1 - 0.05 / 2)
        fh_width = 2 * z * se

        assert av_width > fh_width, (
            f"Always-valid width {av_width:.4f} should exceed fixed-horizon "
            f"width {fh_width:.4f}."
        )

    def test_detects_large_effect(self):
        rng = np.random.default_rng(1)
        ctrl = rng.normal(0.0, 1.0, 2000)
        treat = rng.normal(0.5, 1.0, 2000)
        res = msprt_test(ctrl, treat, alpha=0.05)
        assert res["decision"] == "STOP_REJECT"
        assert res["significant"] is True
        assert res["ci_lower"] > 0

    def test_returns_all_keys(self):
        rng = np.random.default_rng(2)
        res = msprt_test(rng.normal(0, 1, 50), rng.normal(0, 1, 50))
        for key in [
            "test", "diff", "se", "n_control", "n_treatment", "tau",
            "sigma", "test_stat", "e_value", "ci_lower", "ci_upper",
            "decision", "significant", "alpha", "interpretation",
        ]:
            assert key in res, f"Missing key: {key}"

    def test_handles_nan(self):
        ctrl = [1.0, 2.0, np.nan, 3.0, 4.0]
        treat = [2.0, 3.0, 4.0, np.nan, 5.0]
        res = msprt_test(ctrl, treat)
        assert res["n_control"] == 4
        assert res["n_treatment"] == 4

    def test_insufficient_data(self):
        res = msprt_test([1.0], [2.0])
        assert res.get("error") is True

    def test_bad_alpha_raises(self):
        rng = np.random.default_rng(3)
        with pytest.raises(ValueError):
            msprt_test(rng.normal(0, 1, 50), rng.normal(0, 1, 50), alpha=1.5)
        with pytest.raises(ValueError):
            msprt_test(rng.normal(0, 1, 50), rng.normal(0, 1, 50), alpha=0.0)

    def test_bad_tau_raises(self):
        rng = np.random.default_rng(4)
        with pytest.raises(ValueError):
            msprt_test(rng.normal(0, 1, 50), rng.normal(0, 1, 50), tau=-1.0)


class TestAlwaysValidCi:
    def test_contains_diff(self):
        rng = np.random.default_rng(5)
        ctrl = rng.normal(0, 1, 300)
        treat = rng.normal(0.1, 1, 300)
        res = always_valid_ci(ctrl, treat)
        assert res["lower"] <= res["diff"] <= res["upper"]
        assert res["width"] > 0

    def test_returns_keys(self):
        rng = np.random.default_rng(6)
        res = always_valid_ci(rng.normal(0, 1, 50), rng.normal(0, 1, 50))
        for key in ["lower", "upper", "width", "diff", "interpretation"]:
            assert key in res


class TestGroupSequentialBoundaries:
    def test_obrien_fleming_monotone_decreasing(self):
        res = group_sequential_boundaries(5, alpha=0.05, spending="obrien_fleming")
        b = res["boundaries"]
        for i in range(len(b) - 1):
            assert b[i] > b[i + 1], (
                f"OBF boundaries should be monotone decreasing, got {b}"
            )

    def test_obrien_fleming_conservative_early(self):
        res = group_sequential_boundaries(4, alpha=0.05, spending="obrien_fleming")
        # First interim should be much more conservative than fixed-horizon z=1.96.
        assert res["boundaries"][0] > 3.0

    def test_pocock_roughly_constant(self):
        res = group_sequential_boundaries(5, alpha=0.05, spending="pocock")
        b = np.array(res["boundaries"])
        # Pocock: spread across interims should be small relative to the level.
        assert (b.max() - b.min()) < 0.5, (
            f"Pocock boundaries should be near-constant, got {b.tolist()}"
        )

    def test_cumulative_alpha_sums_to_alpha(self):
        res = group_sequential_boundaries(10, alpha=0.05, spending="obrien_fleming")
        assert abs(res["cumulative_alpha"][-1] - 0.05) < 1e-6

        res2 = group_sequential_boundaries(10, alpha=0.05, spending="pocock")
        assert abs(res2["cumulative_alpha"][-1] - 0.05) < 1e-6

    def test_bad_spending_raises(self):
        with pytest.raises(ValueError):
            group_sequential_boundaries(3, spending="haybittle")

    def test_bad_n_interims_raises(self):
        with pytest.raises(ValueError):
            group_sequential_boundaries(0)
        with pytest.raises(ValueError):
            group_sequential_boundaries(-2)

    def test_bad_alpha_raises(self):
        with pytest.raises(ValueError):
            group_sequential_boundaries(3, alpha=1.1)


class TestSequentialProportionTest:
    def test_detects_known_difference(self):
        # 50% vs 70% with 1000 per arm is overwhelming evidence.
        res = sequential_proportion_test(500, 1000, 700, 1000, alpha=0.05)
        assert res["decision"] == "STOP_REJECT"
        assert res["significant"] is True
        assert res["ci_lower"] > 0

    def test_no_decision_tiny_effect(self):
        # 10% vs 10.5% with small sample is not enough.
        res = sequential_proportion_test(10, 100, 11, 100, alpha=0.05)
        assert res["decision"] == "CONTINUE"
        assert res["significant"] is False

    def test_returns_keys(self):
        res = sequential_proportion_test(100, 1000, 120, 1000)
        for key in [
            "rate_control", "rate_treatment", "diff", "ci_lower",
            "ci_upper", "decision", "significant", "interpretation",
        ]:
            assert key in res

    def test_bad_counts_raise(self):
        with pytest.raises(ValueError):
            sequential_proportion_test(0, 0, 10, 100)
        with pytest.raises(ValueError):
            sequential_proportion_test(150, 100, 10, 100)
        with pytest.raises(ValueError):
            sequential_proportion_test(-1, 100, 10, 100)

    def test_bad_alpha_raises(self):
        with pytest.raises(ValueError):
            sequential_proportion_test(10, 100, 20, 100, alpha=0.0)


class TestMismatchedHandling:
    def test_empty_inputs(self):
        res = msprt_test([], [])
        assert res.get("error") is True

    def test_always_valid_ci_insufficient(self):
        res = always_valid_ci([1.0], [2.0])
        assert res.get("error") is True
