"""
AgentXP statistics library.

Production-grade statistical functions for A/B testing and experiment analysis.
Every function returns a dict with results and a plain-language interpretation.
"""

# A/B testing
from agentxp.stats.ab_tests import (
    welch_test,
    proportion_test,
    ratio_metric_test,
    winsorize,
)

# Power analysis
from agentxp.stats.power import (
    power_proportion,
    power_mean,
    detectable_effect,
    duration_estimate,
    power_sensitivity_table,
)

# SRM detection
from agentxp.stats.srm import (
    srm_check,
    srm_diagnose,
)

# Effect sizes
from agentxp.stats.effect_size import (
    cohens_d,
    relative_lift,
)

# Multiple comparisons
from agentxp.stats.corrections import (
    adjust_pvalues,
)

# CUPED variance reduction
from agentxp.stats.cuped import (
    cuped_adjust,
    cuped_welch_test,
    variance_reduction,
)

# Bayesian A/B testing
from agentxp.stats.bayesian import (
    beta_binomial_test,
    normal_normal_test,
    expected_loss,
    probability_to_beat,
)

# Sequential testing
from agentxp.stats.sequential import (
    msprt_test,
    always_valid_ci,
    group_sequential_boundaries,
    sequential_proportion_test,
)

# Ratio power analysis
from agentxp.stats.ratio_power import power_ratio

# Fisher's exact test (small-sample fallback)
from agentxp.stats.fishers import fishers_exact_test

# Guardrail (non-inferiority) testing and denominator SRM
from agentxp.stats.guardrails import guardrail_test, denominator_srm

# Additional effect sizes
from agentxp.stats.effect_size_extras import cohens_h

# Experiment extension estimation
from agentxp.stats.extension import extension_estimate

# Data preparation
from agentxp.stats.prep import prepare_experiment_data

# Tracing flag (D.9 audit-trail contract)
from agentxp.stats._trace import set_trace, is_trace_enabled

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
    # CUPED variance reduction
    "cuped_adjust",
    "cuped_welch_test",
    "variance_reduction",
    # Bayesian A/B testing
    "beta_binomial_test",
    "normal_normal_test",
    "expected_loss",
    "probability_to_beat",
    # Sequential testing
    "msprt_test",
    "always_valid_ci",
    "group_sequential_boundaries",
    "sequential_proportion_test",
    # Ratio power
    "power_ratio",
    # Small-sample proportion fallback
    "fishers_exact_test",
    # Guardrails
    "guardrail_test",
    "denominator_srm",
    # Additional effect sizes
    "cohens_h",
    # Extension estimation
    "extension_estimate",
    # Data preparation
    "prepare_experiment_data",
    # Tracing
    "set_trace",
    "is_trace_enabled",
]
