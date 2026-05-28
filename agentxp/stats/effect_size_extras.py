"""
Additional effect size measures for proportion metrics.

``cohens_d`` in ``effect_size.py`` covers continuous metrics. Cohen's h is
the proportion analogue — the arcsine-transformed difference, which is
approximately normally distributed and uses the same small/medium/large
thresholds as Cohen's d.
"""

import math


def cohens_h(p_control, p_treatment):
    """Cohen's h — standardized effect size for two proportions.

    Formula:
        h = 2·arcsin(√p_treatment) - 2·arcsin(√p_control)

    The arcsine transform stabilizes variance so that differences in h are
    comparable across baselines (a 1% → 2% change and a 50% → 51% change
    are very different in h terms).

    Magnitude thresholds (matching Cohen's conventions):
        |h| < 0.2  → Negligible
        |h| < 0.5  → Small
        |h| < 0.8  → Medium
        |h| >= 0.8 → Large

    Args:
        p_control: control proportion in [0, 1].
        p_treatment: treatment proportion in [0, 1].

    Returns:
        dict with: h, magnitude, abs_h, interpretation.
    """
    if not 0 <= p_control <= 1:
        raise ValueError(f"p_control must be in [0, 1] (got {p_control}).")
    if not 0 <= p_treatment <= 1:
        raise ValueError(f"p_treatment must be in [0, 1] (got {p_treatment}).")

    phi_c = 2 * math.asin(math.sqrt(p_control))
    phi_t = 2 * math.asin(math.sqrt(p_treatment))
    h = phi_t - phi_c
    abs_h = abs(h)

    if abs_h < 0.2:
        magnitude = "Negligible"
    elif abs_h < 0.5:
        magnitude = "Small"
    elif abs_h < 0.8:
        magnitude = "Medium"
    else:
        magnitude = "Large"

    direction = "higher" if h > 0 else "lower" if h < 0 else "equal"
    interp = (
        f"Cohen's h = {h:+.3f} ({magnitude} effect). "
        f"Treatment ({p_treatment:.4f}) is {direction} than control ({p_control:.4f})."
    )

    return {
        "h": float(h),
        "abs_h": float(abs_h),
        "magnitude": magnitude,
        "p_control": float(p_control),
        "p_treatment": float(p_treatment),
        "interpretation": interp,
    }
