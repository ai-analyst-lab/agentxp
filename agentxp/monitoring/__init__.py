"""
Live monitoring module for running experiments.

Exports:
    - MonitorReport: aggregated traffic-light report dataclass.
    - run_monitor: orchestrator combining the three checks below.
    - srm_trend: SRM check binned by time window.
    - guardrail_health: per-metric non-inferiority check.
    - sample_accumulation: current-n vs plan pacing check.
"""

from agentxp.monitoring.base import MonitorReport
from agentxp.monitoring.guardrail_health import guardrail_health
from agentxp.monitoring.report import run_monitor
from agentxp.monitoring.sample_accumulation import sample_accumulation
from agentxp.monitoring.srm_trend import srm_trend

__all__ = [
    "MonitorReport",
    "run_monitor",
    "srm_trend",
    "guardrail_health",
    "sample_accumulation",
]
