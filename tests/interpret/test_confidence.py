"""Tests for agentxp.interpret.confidence.map_confidence (§23 / §1.8.10)."""

from __future__ import annotations

import pytest

from agentxp.interpret.confidence import (
    ConfidenceLabel,
    map_confidence,
)

# The closed set of 7 labels per §1.8.10.
ALLOWED_LABELS = {
    "highly likely positive",
    "very likely positive",
    "leaning positive",
    "inconclusive",
    "leaning negative",
    "very likely negative",
    "highly likely negative",
}


def test_highly_likely_positive_higher_is_better():
    # 95% CI entirely above 0: clearly significant lift on benefit side.
    label = map_confidence(
        ci_lower_95=1.5, ci_upper_95=4.5,
        ci_lower_90=2.0, ci_upper_90=4.0,
        direction="higher_is_better",
    )
    assert label == "highly likely positive"


def test_very_likely_positive_higher_is_better():
    # 95% straddles 0; 90% excludes on positive side.
    label = map_confidence(
        ci_lower_95=-0.2, ci_upper_95=3.0,
        ci_lower_90=0.3, ci_upper_90=2.5,
        direction="higher_is_better",
    )
    assert label == "very likely positive"


def test_leaning_positive_higher_is_better():
    # Both CIs straddle 0, but center positive and away from 0.
    label = map_confidence(
        ci_lower_95=-2.0, ci_upper_95=4.0,
        ci_lower_90=-1.0, ci_upper_90=3.0,
        direction="higher_is_better",
    )
    # 90% center = 1.0, half-width = 2.0, near-zero band = 0.1. center > band.
    assert label == "leaning positive"


def test_inconclusive_centered_near_zero():
    # 90% CI is [-1, 1], center exactly 0 -> inconclusive.
    label = map_confidence(
        ci_lower_95=-2.0, ci_upper_95=2.0,
        ci_lower_90=-1.0, ci_upper_90=1.0,
        direction="higher_is_better",
    )
    assert label == "inconclusive"


def test_leaning_negative_higher_is_better():
    # Both CIs straddle 0, center negative.
    label = map_confidence(
        ci_lower_95=-4.0, ci_upper_95=2.0,
        ci_lower_90=-3.0, ci_upper_90=1.0,
        direction="higher_is_better",
    )
    # 90% center = -1.0, half-width = 2.0, band = 0.1. |center| > band, neg.
    assert label == "leaning negative"


def test_very_likely_negative():
    # Mirror of test_very_likely_positive.
    label = map_confidence(
        ci_lower_95=-3.0, ci_upper_95=0.2,
        ci_lower_90=-2.5, ci_upper_90=-0.3,
        direction="higher_is_better",
    )
    assert label == "very likely negative"


def test_highly_likely_negative():
    # Mirror of test_highly_likely_positive: both CIs entirely below 0.
    label = map_confidence(
        ci_lower_95=-4.5, ci_upper_95=-1.5,
        ci_lower_90=-4.0, ci_upper_90=-2.0,
        direction="higher_is_better",
    )
    assert label == "highly likely negative"


def test_lower_is_better_flips_signs():
    # Same bounds as test_highly_likely_positive (both CIs above 0).
    # For higher_is_better -> "highly likely positive".
    # For lower_is_better, positive lift = harmful -> "highly likely negative".
    bounds = dict(
        ci_lower_95=1.5, ci_upper_95=4.5,
        ci_lower_90=2.0, ci_upper_90=4.0,
    )
    assert map_confidence(**bounds, direction="higher_is_better") == "highly likely positive"
    assert map_confidence(**bounds, direction="lower_is_better") == "highly likely negative"

    # And the symmetric flip: negative CI on lower_is_better = benefit.
    neg_bounds = dict(
        ci_lower_95=-4.5, ci_upper_95=-1.5,
        ci_lower_90=-4.0, ci_upper_90=-2.0,
    )
    assert map_confidence(**neg_bounds, direction="higher_is_better") == "highly likely negative"
    assert map_confidence(**neg_bounds, direction="lower_is_better") == "highly likely positive"


def test_neither_uses_absolute_magnitude():
    # direction="neither": large CI excluding 0 -> "highly likely positive"
    # regardless of sign (no direction-specific labeling).
    pos = map_confidence(
        ci_lower_95=1.5, ci_upper_95=4.5,
        ci_lower_90=2.0, ci_upper_90=4.0,
        direction="neither",
    )
    neg = map_confidence(
        ci_lower_95=-4.5, ci_upper_95=-1.5,
        ci_lower_90=-4.0, ci_upper_90=-2.0,
        direction="neither",
    )
    assert pos == "highly likely positive"
    assert neg == "highly likely positive"


def test_boundary_ci_at_exactly_zero():
    # ci_lower_95 = 0.0 exactly. The "highly likely" rule requires lo95 > 0
    # (strict). With lo95 == 0, we fall through to the 90% check.
    # ci_lower_90 = 0.3 > 0 -> "very likely positive".
    label = map_confidence(
        ci_lower_95=0.0, ci_upper_95=3.0,
        ci_lower_90=0.3, ci_upper_90=2.5,
        direction="higher_is_better",
    )
    assert label == "very likely positive"


def test_returns_closed_set_value():
    # Cover several distinct cases and assert every output is in the closed set.
    cases = [
        dict(ci_lower_95=1.5, ci_upper_95=4.5, ci_lower_90=2.0, ci_upper_90=4.0,
             direction="higher_is_better"),
        dict(ci_lower_95=-0.2, ci_upper_95=3.0, ci_lower_90=0.3, ci_upper_90=2.5,
             direction="higher_is_better"),
        dict(ci_lower_95=-2.0, ci_upper_95=4.0, ci_lower_90=-1.0, ci_upper_90=3.0,
             direction="higher_is_better"),
        dict(ci_lower_95=-2.0, ci_upper_95=2.0, ci_lower_90=-1.0, ci_upper_90=1.0,
             direction="higher_is_better"),
        dict(ci_lower_95=-4.0, ci_upper_95=2.0, ci_lower_90=-3.0, ci_upper_90=1.0,
             direction="higher_is_better"),
        dict(ci_lower_95=-3.0, ci_upper_95=0.2, ci_lower_90=-2.5, ci_upper_90=-0.3,
             direction="higher_is_better"),
        dict(ci_lower_95=-4.5, ci_upper_95=-1.5, ci_lower_90=-4.0, ci_upper_90=-2.0,
             direction="higher_is_better"),
        dict(ci_lower_95=1.5, ci_upper_95=4.5, ci_lower_90=2.0, ci_upper_90=4.0,
             direction="lower_is_better"),
        dict(ci_lower_95=-2.0, ci_upper_95=2.0, ci_lower_90=-1.0, ci_upper_90=1.0,
             direction="neither"),
    ]
    for kwargs in cases:
        out = map_confidence(**kwargs)
        assert out in ALLOWED_LABELS, f"{out!r} not in closed set for {kwargs}"


def test_function_is_pure():
    # Same inputs -> same output, no side effects.
    kwargs = dict(
        ci_lower_95=-0.2, ci_upper_95=3.0,
        ci_lower_90=0.3, ci_upper_90=2.5,
        direction="higher_is_better",
    )
    out1 = map_confidence(**kwargs)
    out2 = map_confidence(**kwargs)
    out3 = map_confidence(**kwargs)
    assert out1 == out2 == out3


def test_inconclusive_threshold_exact():
    # CI center exactly at the ±5% band edge. Use integer-friendly values to
    # avoid float drift: 90% CI [-95, 105] -> center=5.0, half-width=100.0,
    # band = 5.0. Tie-breaking convention: |center| <= band -> "inconclusive"
    # (inclusive, so the exact threshold lands on inconclusive).
    label = map_confidence(
        ci_lower_95=-150.0, ci_upper_95=160.0,
        ci_lower_90=-95.0, ci_upper_90=105.0,
        direction="higher_is_better",
    )
    assert label == "inconclusive"


def test_higher_is_better_negative_extreme():
    # Very negative CI on higher_is_better = clearly harmful -> highly likely negative.
    label = map_confidence(
        ci_lower_95=-10.0, ci_upper_95=-5.0,
        ci_lower_90=-9.5, ci_upper_90=-5.5,
        direction="higher_is_better",
    )
    assert label == "highly likely negative"


def test_lower_is_better_positive_extreme():
    # Positive lift on a lower_is_better metric = harmful -> "highly likely negative".
    label = map_confidence(
        ci_lower_95=5.0, ci_upper_95=10.0,
        ci_lower_90=5.5, ci_upper_90=9.5,
        direction="lower_is_better",
    )
    assert label == "highly likely negative"
