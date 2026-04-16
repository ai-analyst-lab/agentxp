"""Integration tests: verify that each sample CSV produces the expected statistical direction.

These are mini integration tests — they run the stats functions directly on the
sample datasets and assert the expected verdict direction. They do NOT exercise
the full /experiment skill, just the underlying stat functions.
"""

from __future__ import annotations

import pandas as pd
import pytest

from openxp.stats import (
    guardrail_test,
    proportion_test,
    srm_check,
    welch_test,
)

SAMPLE_DIR = "sample-data"


def _load(name: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (control, treatment) DataFrames for a sample CSV."""
    df = pd.read_csv(f"{SAMPLE_DIR}/{name}")
    return df[df["variant"] == "control"], df[df["variant"] == "treatment"]


# -----------------------------------------------------------------------
# 1. clean_ab.csv — SHIP direction: positive lift, SRM clean
# -----------------------------------------------------------------------
class TestCleanAb:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.c, self.t = _load("clean_ab.csv")

    def test_srm_passes(self):
        srm = srm_check([len(self.c), len(self.t)], [0.5, 0.5])
        assert srm["verdict"] == "PASS"

    def test_conversion_lift_positive(self):
        result = proportion_test(
            int(self.c["converted"].sum()),
            len(self.c),
            int(self.t["converted"].sum()),
            len(self.t),
        )
        assert result["relative_lift_pct"] > 0, "Expected positive conversion lift"

    def test_revenue_lift_positive(self):
        result = welch_test(self.c["revenue"].values, self.t["revenue"].values)
        assert result["relative_lift_pct"] > 0, "Expected positive revenue lift"


# -----------------------------------------------------------------------
# 2. checkout_redesign.csv — SHIP: primary significant positive, SRM clean
# -----------------------------------------------------------------------
class TestCheckoutRedesign:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.c, self.t = _load("checkout_redesign.csv")

    def test_srm_passes(self):
        srm = srm_check([len(self.c), len(self.t)], [0.5, 0.5])
        assert srm["verdict"] == "PASS"

    def test_checkout_completed_significant_positive(self):
        result = proportion_test(
            int(self.c["checkout_completed"].sum()),
            len(self.c),
            int(self.t["checkout_completed"].sum()),
            len(self.t),
        )
        assert result["significant"] is True
        assert result["relative_lift_pct"] > 0

    def test_revenue_lift_positive(self):
        result = welch_test(self.c["revenue"].values, self.t["revenue"].values)
        assert result["relative_lift_pct"] > 0, "Revenue lift should be positive"

    def test_revenue_not_significant(self):
        result = welch_test(self.c["revenue"].values, self.t["revenue"].values)
        assert result["significant"] is False, "Revenue should not reach significance"


# -----------------------------------------------------------------------
# 3. no_effect.csv — LEARN (powered): null result, large sample, SRM clean
# -----------------------------------------------------------------------
class TestNoEffect:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.c, self.t = _load("no_effect.csv")

    def test_srm_passes(self):
        srm = srm_check([len(self.c), len(self.t)], [0.5, 0.5])
        assert srm["verdict"] == "PASS"

    def test_conversion_not_significant(self):
        result = proportion_test(
            int(self.c["converted"].sum()),
            len(self.c),
            int(self.t["converted"].sum()),
            len(self.t),
        )
        assert result["significant"] is False

    def test_revenue_not_significant(self):
        result = welch_test(self.c["revenue"].values, self.t["revenue"].values)
        assert result["significant"] is False

    def test_adequately_powered(self):
        """With n=5000 per group, this is an adequately powered null."""
        assert len(self.c) >= 5000
        assert len(self.t) >= 5000


# -----------------------------------------------------------------------
# 4. underpowered.csv — LEARN (underpowered): null, small sample
# -----------------------------------------------------------------------
class TestUnderpowered:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.c, self.t = _load("underpowered.csv")

    def test_srm_passes(self):
        srm = srm_check([len(self.c), len(self.t)], [0.5, 0.5])
        assert srm["verdict"] == "PASS"

    def test_conversion_not_significant(self):
        result = proportion_test(
            int(self.c["converted"].sum()),
            len(self.c),
            int(self.t["converted"].sum()),
            len(self.t),
        )
        assert result["significant"] is False

    def test_small_sample(self):
        """n=500 per group is too small to detect moderate effects."""
        assert len(self.c) <= 500
        assert len(self.t) <= 500


# -----------------------------------------------------------------------
# 5. srm_violation.csv — INVALID: broken randomization
# -----------------------------------------------------------------------
class TestSrmViolation:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.c, self.t = _load("srm_violation.csv")

    def test_srm_blocks(self):
        srm = srm_check([len(self.c), len(self.t)], [0.5, 0.5])
        assert srm["verdict"] == "BLOCK"

    def test_srm_p_below_threshold(self):
        srm = srm_check([len(self.c), len(self.t)], [0.5, 0.5])
        assert srm["p_value"] < 0.01


# -----------------------------------------------------------------------
# 6. guardrail_violation.csv — INVESTIGATE: guardrail degraded
# -----------------------------------------------------------------------
class TestGuardrailViolation:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.c, self.t = _load("guardrail_violation.csv")

    def test_srm_passes(self):
        srm = srm_check([len(self.c), len(self.t)], [0.5, 0.5])
        assert srm["verdict"] == "PASS"

    def test_page_load_significantly_degraded(self):
        """Page load ms increased significantly — treatment is slower."""
        result = welch_test(
            self.c["page_load_ms"].values, self.t["page_load_ms"].values
        )
        assert result["significant"] is True
        assert result["relative_lift_pct"] > 0, "Treatment should be slower (higher ms)"

    def test_guardrail_blocks(self):
        """guardrail_test with invert=True should BLOCK on page_load_ms."""
        result = guardrail_test(
            self.c["page_load_ms"].values,
            self.t["page_load_ms"].values,
            metric_type="mean",
            nim_relative=0.02,
            alpha=0.05,
            invert=True,
        )
        assert result["verdict"] == "BLOCK"

    def test_primary_not_significant(self):
        result = proportion_test(
            int(self.c["converted"].sum()),
            len(self.c),
            int(self.t["converted"].sum()),
            len(self.t),
        )
        assert result["significant"] is False


# -----------------------------------------------------------------------
# 7. mixed_results.csv — INVESTIGATE: segment reversals (Simpson's paradox)
# -----------------------------------------------------------------------
class TestMixedResults:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.c, self.t = _load("mixed_results.csv")
        self.df = pd.concat([self.c, self.t])

    def test_srm_passes(self):
        srm = srm_check([len(self.c), len(self.t)], [0.5, 0.5])
        assert srm["verdict"] == "PASS"

    def test_sessions_significant_positive(self):
        result = welch_test(
            self.c["sessions_14d"].values, self.t["sessions_14d"].values
        )
        assert result["significant"] is True
        assert result["relative_lift_pct"] > 0

    def test_revenue_significant_positive(self):
        result = welch_test(
            self.c["revenue_30d"].values, self.t["revenue_30d"].values
        )
        assert result["significant"] is True
        assert result["relative_lift_pct"] > 0

    def test_retention_significant_negative(self):
        """Retention degrades — the mixed signal that triggers INVESTIGATE."""
        result = proportion_test(
            int(self.c["retained_30d"].sum()),
            len(self.c),
            int(self.t["retained_30d"].sum()),
            len(self.t),
        )
        assert result["significant"] is True
        assert result["relative_lift_pct"] < 0, "Retention should drop in treatment"
