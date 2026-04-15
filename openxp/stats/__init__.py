"""
OpenXP statistics library.

Production-grade statistical functions for A/B testing and experiment analysis.
Every function returns a dict with results and a plain-language interpretation.
"""

# A/B testing
from openxp.stats.ab_tests import (
    welch_test,
    proportion_test,
    ratio_metric_test,
    winsorize,
)

# Power analysis
from openxp.stats.power import (
    power_proportion,
    power_mean,
    detectable_effect,
    duration_estimate,
    power_sensitivity_table,
)

# SRM detection
from openxp.stats.srm import (
    srm_check,
    srm_diagnose,
)

# Effect sizes
from openxp.stats.effect_size import (
    cohens_d,
    relative_lift,
)

# Multiple comparisons
from openxp.stats.corrections import (
    adjust_pvalues,
)

__all__ = [
    # A/B testing
    "welch_test",
    "proportion_test",
    "ratio_metric_test",
    "winsorize",
    # Power analysis
    "power_proportion",
    "power_mean",
    "detectable_effect",
    "duration_estimate",
    "power_sensitivity_table",
    # SRM detection
    "srm_check",
    "srm_diagnose",
    # Effect sizes
    "cohens_d",
    "relative_lift",
    # Multiple comparisons
    "adjust_pvalues",
]
