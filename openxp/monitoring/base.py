"""
Shared dataclass for the monitoring module.

MonitorReport aggregates the three monitoring checks (SRM trend, guardrail
health, sample accumulation) into a single traffic-light report with
recommendations. Matches the plain-dict/interpretation style used elsewhere
in OpenXP: the dataclass provides structure, but ``to_dict()`` returns a
serializable payload compatible with ``ExperimentStore.save_analysis``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# Mapping between internal check verdicts (PASS/WARNING/BLOCK, matching
# srm_check / ab_tests style) and the user-facing traffic light.
_VERDICT_TO_LIGHT: dict[str, str] = {
    "PASS": "GREEN",
    "WARNING": "YELLOW",
    "BLOCK": "RED",
}

# Severity ordering for "worst wins" aggregation.
_LIGHT_RANK: dict[str, int] = {"GREEN": 0, "YELLOW": 1, "RED": 2}


def verdict_to_light(verdict: str) -> str:
    """Map an internal check verdict to a user-facing traffic light."""
    return _VERDICT_TO_LIGHT.get(verdict, "RED")


def worst_light(lights: list[str]) -> str:
    """Return the worst (highest severity) traffic light in the list."""
    if not lights:
        return "GREEN"
    return max(lights, key=lambda v: _LIGHT_RANK.get(v, 2))


@dataclass
class MonitorReport:
    """Aggregated monitoring report for a running experiment.

    Attributes:
        status: Overall traffic light (GREEN / YELLOW / RED). Worst-of-three
            aggregation across the individual checks.
        checks: Dict with keys ``srm_trend``, ``guardrail_health``,
            ``sample_accumulation``. Each value is the raw dict returned by
            the corresponding check function.
        recommendations: List of plain-language action items ordered by
            severity (RED first).
        timestamp: ISO-8601 UTC timestamp when the report was produced.
        interpretation: One-paragraph human summary of overall status.
        experiment_id: Experiment id if this report was produced via
            ``run_monitor`` with an id.
    """

    status: str = "GREEN"
    checks: dict[str, Any] = field(default_factory=dict)
    recommendations: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=_iso_now)
    interpretation: str = ""
    experiment_id: str | None = None
    persistence_error: str | None = None

    def to_dict(self) -> dict:
        return {
            "report_type": "monitor",
            "status": self.status,
            "checks": self.checks,
            "recommendations": list(self.recommendations),
            "timestamp": self.timestamp,
            "interpretation": self.interpretation,
            "experiment_id": self.experiment_id,
            "persistence_error": self.persistence_error,
        }
