"""
AgentXP — Open-source agentic experimentation platform.

Statsig gives you a dashboard. AgentXP gives you a colleague who knows statistics.

Production-grade statistical functions for A/B testing: hypothesis tests,
power analysis, SRM detection, effect sizes, and multiple comparison corrections.
All backed by auditable Python — no LLM improvisation.

Usage:
    from agentxp.stats import (
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

from agentxp.data import load_data, discover_schema

__version__ = "0.1.0"


# Sweep stale /tmp/agentxp_dispatches/ and /tmp/agentxp_bundles/ files
# on package import. The benchmark surfaced two leak surfaces:
#   - dispatches/ was swept on bridge.py import but NOT when a tool
#     imported only workflows or orchestrator.tools (the sweep never
#     fired)
#   - bundles/ was never swept by anything at all
# Best-effort; silently ignores missing dirs / permission errors so
# this can never block import.
try:
    from agentxp.orchestrator.bridge import sweep_all_tmp_dirs as _sweep_all_tmp_dirs

    _sweep_all_tmp_dirs()
except Exception:  # noqa: BLE001 — never block agentxp import on a sweep failure
    pass


__all__ = ["load_data", "discover_schema"]
