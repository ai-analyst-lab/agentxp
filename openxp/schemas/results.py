"""
Result type documentation for OpenXP stats functions.

All stats functions return plain dicts (not dataclasses) for maximum
portability and serialization ease. This module documents the expected
shapes for reference and optional validation.
"""

# Every stats function returns a dict with these common keys:
# - interpretation: str — plain-language summary of the result
# - error: str (only present if the function failed)

# TestResult keys (from welch_test, proportion_test, ratio_metric_test):
TEST_RESULT_KEYS = [
    "test",              # str: test name ("welch_t_test", "proportion_z_test", "ratio_delta_method")
    "p_value",           # float: p-value
    "significant",       # bool: p_value < alpha
    "ci_lower",          # float: lower bound of confidence interval
    "ci_upper",          # float: upper bound of confidence interval
    "n_control",         # int: sample size of control group
    "n_treatment",       # int: sample size of treatment group
    "alpha",             # float: significance threshold
    "interpretation",    # str: plain-language summary
]

# PowerResult keys (from power_proportion, power_mean):
POWER_RESULT_KEYS = [
    "sample_size_per_group",  # int: required n per variant
    "total_sample_size",      # int: total n (both groups)
    "alpha",                  # float: significance level
    "power",                  # float: statistical power
    "interpretation",         # str: plain-language summary
]

# SRMResult keys (from srm_check):
SRM_RESULT_KEYS = [
    "test",              # str: "srm_chi_squared"
    "chi2_stat",         # float: chi-squared test statistic
    "p_value",           # float: p-value
    "verdict",           # str: "PASS" | "WARNING" | "BLOCK"
    "observed_counts",   # list[int]: observed per-variant counts
    "expected_counts",   # list[int]: expected per-variant counts
    "observed_ratios",   # list[float]: observed allocation ratios
    "expected_ratios",   # list[float]: expected allocation ratios
    "total",             # int: total sample size
    "threshold",         # float: p-value threshold for verdicts
    "interpretation",    # str: plain-language summary
]

# EffectSizeResult keys (from cohens_d):
EFFECT_SIZE_RESULT_KEYS = [
    "d",                 # float: Cohen's d value
    "magnitude",         # str: "Negligible" | "Small" | "Medium" | "Large"
    "interpretation",    # str: plain-language summary
]

# DurationResult keys (from duration_estimate):
DURATION_RESULT_KEYS = [
    "days",              # int: estimated experiment duration in days
    "weeks",             # float: duration in weeks
    "daily_enrollment",  # float: daily enrollment rate
    "n_required",        # int: total sample needed
    "viable",            # str: "VIABLE" | "MARGINAL" | "NOT_VIABLE"
    "interpretation",    # str: plain-language summary
]
