"""Confidence label mapping for AgentXP v0.1.

Pure function mapping primary-metric 90/95% CI bounds to one of the 7
ConfidenceLabel values defined in OPENXP_V01_PLAN §1.8.10. Decision rule
follows §23 (confidence framing): both CIs excluding 0 on benefit side =>
"highly likely"; 95% straddles but 90% excludes => "very likely"; both
straddle 0 with non-centered center => "leaning"; both straddle with
near-zero center => "inconclusive". Direction flips the benefit side for
"lower_is_better" and uses absolute magnitude for "neither".
"""

from __future__ import annotations

from typing import Literal

ConfidenceLabel = Literal[
    "highly likely positive",
    "very likely positive",
    "leaning positive",
    "inconclusive",
    "leaning negative",
    "very likely negative",
    "highly likely negative",
]

Direction = Literal["higher_is_better", "lower_is_better", "neither"]

# Threshold (as fraction of half-width of 90% CI) within which the CI center
# is considered "effectively centered on no-effect" => inconclusive. Per §23:
# ±5% of the CI half-width.
INCONCLUSIVE_CENTER_FRACTION: float = 0.05

# Allowed direction values (validated at call time).
_VALID_DIRECTIONS = ("higher_is_better", "lower_is_better", "neither")


def _classify_oriented(
    lo95: float, hi95: float, lo90: float, hi90: float
) -> ConfidenceLabel:
    """Classify CIs assuming `positive lift = benefit` (higher_is_better frame).

    Pure helper. All sign-flipping for lower_is_better happens in the caller.
    """
    center90 = (lo90 + hi90) / 2.0
    half_width90 = (hi90 - lo90) / 2.0
    # "near zero" => center within ±5% of the 90% CI half-width of 0.
    near_zero_band = INCONCLUSIVE_CENTER_FRACTION * abs(half_width90)

    # 1. Both 95% and 90% CIs entirely above 0 => highly likely positive.
    if lo95 > 0:
        return "highly likely positive"
    # 2. 95% straddles 0 (lo95 <= 0) but 90% excludes on the positive side.
    if lo90 > 0:
        return "very likely positive"

    # 1'. Both 95% and 90% CIs entirely below 0 => highly likely negative.
    if hi95 < 0:
        return "highly likely negative"
    # 2'. 95% straddles 0 but 90% entirely below 0.
    if hi90 < 0:
        return "very likely negative"

    # 3/4. Both 90% and 95% CIs straddle 0. Use center to pick a leaning label
    # or call it inconclusive if the center is effectively at 0.
    if abs(center90) <= near_zero_band:
        return "inconclusive"
    if center90 > 0:
        return "leaning positive"
    return "leaning negative"


def map_confidence(
    ci_lower_95: float,
    ci_upper_95: float,
    ci_lower_90: float,
    ci_upper_90: float,
    direction: Direction,
) -> ConfidenceLabel:
    """Map a primary metric's 90/95% CI bounds to a 7-value confidence label.

    Pure function. Direction orients which side of 0 counts as "benefit":

    - "higher_is_better": positive lift = benefit (canonical frame).
    - "lower_is_better": negative lift = benefit; the function internally
      flips the CI signs, runs the canonical classifier, then swaps
      positive/negative in the returned label.
    - "neither": only |center| matters; uses absolute magnitude so the
      output uses "positive"-side labels regardless of sign of lift.

    Decision rule (per §23, canonical frame):
        - both CIs exclude 0 on benefit side       -> "highly likely positive"
        - 95% straddles 0, 90% excludes on benefit -> "very likely positive"
        - both CIs straddle 0, center positive     -> "leaning positive"
        - both CIs straddle 0, center near 0       -> "inconclusive"
        - mirror for the negative side.
    """
    if direction not in _VALID_DIRECTIONS:
        raise ValueError(
            f"direction must be one of {_VALID_DIRECTIONS}, got {direction!r}"
        )

    # Normalize bounds (defensive: accept either ordering).
    lo95, hi95 = (ci_lower_95, ci_upper_95)
    lo90, hi90 = (ci_lower_90, ci_upper_90)
    if lo95 > hi95:
        lo95, hi95 = hi95, lo95
    if lo90 > hi90:
        lo90, hi90 = hi90, lo90

    if direction == "higher_is_better":
        return _classify_oriented(lo95, hi95, lo90, hi90)

    if direction == "lower_is_better":
        # Flip signs so negative lift (benefit on a lower_is_better metric)
        # becomes "positive" in the canonical frame. The canonical label is
        # already oriented correctly relative to benefit, so no second flip.
        return _classify_oriented(-hi95, -lo95, -hi90, -lo90)

    # direction == "neither": classify using |center| and treat any large
    # magnitude as a positive-side label (direction-agnostic).
    center90 = (lo90 + hi90) / 2.0
    half_width90 = (hi90 - lo90) / 2.0
    near_zero_band = INCONCLUSIVE_CENTER_FRACTION * abs(half_width90)

    # If 0 is excluded from both CIs (regardless of side), highly likely.
    if lo95 > 0 or hi95 < 0:
        return "highly likely positive"
    if lo90 > 0 or hi90 < 0:
        return "very likely positive"
    if abs(center90) <= near_zero_band:
        return "inconclusive"
    return "leaning positive"
