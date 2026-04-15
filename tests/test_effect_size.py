"""Tests for effect_size.py — effect size calculations."""

import numpy as np
import pytest

from openxp.stats.effect_size import cohens_d, relative_lift


class TestCohensD:
    def test_known_positive_effect(self, continuous_ab):
        result = cohens_d(continuous_ab["control"], continuous_ab["treatment"])
        assert result["d"] > 0  # treatment > control
        assert result["magnitude"] in ("Negligible", "Small", "Medium")
        assert "interpretation" in result

    def test_no_effect(self):
        rng = np.random.default_rng(42)
        a = rng.normal(50, 10, 1000)
        b = rng.normal(50, 10, 1000)
        result = cohens_d(a, b)
        assert abs(result["d"]) < 0.2
        assert result["magnitude"] == "Negligible"

    def test_insufficient_data(self):
        result = cohens_d([1], [2])
        assert result["magnitude"] == "Unknown"

    def test_zero_variance(self):
        result = cohens_d([5, 5, 5], [5, 5, 5])
        assert result["d"] == 0.0


class TestRelativeLift:
    def test_positive_lift(self):
        result = relative_lift(100, 110)
        assert abs(result["lift_pct"] - 10.0) < 0.01
        assert result["absolute_diff"] == 10.0

    def test_negative_lift(self):
        result = relative_lift(100, 90)
        assert result["lift_pct"] < 0

    def test_zero_baseline(self):
        result = relative_lift(0, 10)
        assert "undefined" in result["interpretation"].lower() or result["lift_pct"] == float("inf")

    def test_no_change(self):
        result = relative_lift(50, 50)
        assert result["lift_pct"] == 0.0
        assert result["absolute_diff"] == 0.0
