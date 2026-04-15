"""
OpenXP — Open-source agentic experimentation platform.

Statsig gives you a dashboard. OpenXP gives you a colleague who knows statistics.

Production-grade statistical functions for A/B testing: hypothesis tests,
power analysis, SRM detection, effect sizes, and multiple comparison corrections.
All backed by auditable Python — no LLM improvisation.

Usage:
    from openxp.stats import (
        # A/B testing
        welch_test, proportion_test, ratio_metric_test, winsorize,
        # Power analysis
        power_proportion, power_mean, detectable_effect, duration_estimate,
        power_sensitivity_table,
        # SRM detection
        srm_check, srm_diagnose,
        # Effect sizes
        cohens_d, relative_lift,
        # Multiple comparisons
        adjust_pvalues,
    )

    # Run a basic A/B test on conversion rates
    result = proportion_test(c_success=350, c_n=1000, t_success=385, t_n=1000)
    print(result["interpretation"])

    # Check for SRM before analyzing
    srm = srm_check(observed_counts=[4800, 5200], expected_ratios=[0.5, 0.5])
    if srm["verdict"] == "BLOCK":
        print("HALT: SRM detected —", srm["interpretation"])
"""

__version__ = "0.1.0"
