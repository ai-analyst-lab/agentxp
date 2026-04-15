"""
Sample accumulation check.

Compare the current enrolled sample size against the planned total, project
a completion date from the observed daily traffic, and return a traffic-light
verdict. GREEN if on pace, YELLOW if running slow (>20% behind), RED if the
experiment is stalled (no traffic, or >50% behind with no runway left).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def _iso_date(dt: datetime) -> str:
    return dt.date().isoformat()


def sample_accumulation(
    current_n: int,
    required_n: int,
    daily_traffic: float,
    days_elapsed: float,
    planned_duration_days: float | None = None,
    now: datetime | None = None,
) -> dict:
    """Evaluate sample pacing vs plan.

    Args:
        current_n: Total users enrolled so far (both arms combined).
        required_n: Planned total sample size at end of experiment.
        daily_traffic: Observed mean daily enrollment rate.
        days_elapsed: Days since the experiment started.
        planned_duration_days: Planned total run length; if given, used as
            the pacing denominator (otherwise inferred from required_n /
            daily_traffic when possible).
        now: Reference "today" (UTC). Defaults to ``datetime.now(UTC)``.

    Returns:
        dict with:
            - ``test``: ``"sample_accumulation"``
            - ``current_n``, ``required_n``, ``daily_traffic``, ``days_elapsed``
            - ``fraction_complete``: current_n / required_n
            - ``days_remaining``: int (ceiling on remaining days at current
              daily rate; inf if stalled)
            - ``projected_completion``: ISO date string or None
            - ``on_pace``: bool
            - ``verdict``: ``"PASS" | "WARNING" | "BLOCK"`` (internal) —
              surfaced to user as GREEN / YELLOW / RED
            - ``traffic_light``: ``"GREEN" | "YELLOW" | "RED"``
            - ``interpretation``: plain-language summary
    """
    if now is None:
        now = datetime.now(timezone.utc)

    if required_n <= 0:
        return {
            "test": "sample_accumulation",
            "error": "required_n must be positive.",
            "verdict": "BLOCK",
            "traffic_light": "RED",
            "interpretation": "Invalid required_n — cannot evaluate pacing.",
        }

    fraction_complete = float(current_n) / float(required_n)
    remaining_needed = max(0, required_n - current_n)

    if daily_traffic <= 0:
        days_remaining: float = float("inf")
        projected_completion = None
        stalled = current_n < required_n
    else:
        days_remaining = remaining_needed / float(daily_traffic)
        projected_completion = _iso_date(now + timedelta(days=days_remaining))
        stalled = False

    # Expected fraction complete = min(1, days_elapsed / planned duration).
    if planned_duration_days is None:
        if daily_traffic > 0:
            planned_duration_days = required_n / float(daily_traffic)
        else:
            planned_duration_days = float("inf")

    if planned_duration_days > 0 and planned_duration_days != float("inf"):
        expected_fraction = min(1.0, days_elapsed / planned_duration_days)
    else:
        expected_fraction = 0.0

    pace_ratio = (
        fraction_complete / expected_fraction if expected_fraction > 0 else 1.0
    )

    if stalled:
        verdict = "BLOCK"
        light = "RED"
        on_pace = False
        note = (
            "Experiment is stalled: no daily traffic observed and sample "
            "size is still below plan. Check the assignment pipeline."
        )
    elif fraction_complete >= 1.0:
        verdict = "PASS"
        light = "GREEN"
        on_pace = True
        note = (
            f"Sample complete: {current_n:,} of {required_n:,} ({fraction_complete:.0%}). "
            "Ready to move to analysis."
        )
    elif pace_ratio >= 0.8:
        verdict = "PASS"
        light = "GREEN"
        on_pace = True
        note = (
            f"On pace: {fraction_complete:.0%} enrolled vs expected "
            f"{expected_fraction:.0%}. Projected completion {projected_completion}."
        )
    elif pace_ratio >= 0.5:
        verdict = "WARNING"
        light = "YELLOW"
        on_pace = False
        note = (
            f"Running slow: {fraction_complete:.0%} enrolled vs expected "
            f"{expected_fraction:.0%} ({pace_ratio:.0%} of pace). "
            f"Projected completion {projected_completion}. Consider increasing "
            "allocation or extending the runway."
        )
    else:
        verdict = "BLOCK"
        light = "RED"
        on_pace = False
        note = (
            f"Severely behind: {fraction_complete:.0%} enrolled vs expected "
            f"{expected_fraction:.0%} ({pace_ratio:.0%} of pace). "
            f"Projected completion {projected_completion}. Recalculate power "
            "or abort and redesign."
        )

    return {
        "test": "sample_accumulation",
        "current_n": int(current_n),
        "required_n": int(required_n),
        "daily_traffic": float(daily_traffic),
        "days_elapsed": float(days_elapsed),
        "fraction_complete": float(fraction_complete),
        "expected_fraction": float(expected_fraction),
        "pace_ratio": float(pace_ratio),
        "days_remaining": (
            float("inf") if days_remaining == float("inf") else float(days_remaining)
        ),
        "projected_completion": projected_completion,
        "on_pace": bool(on_pace),
        "verdict": verdict,
        "traffic_light": light,
        "interpretation": note,
    }
