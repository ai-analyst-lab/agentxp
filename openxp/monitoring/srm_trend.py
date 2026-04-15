"""
SRM (Sample Ratio Mismatch) trend analysis across time windows.

During an experiment, SRM can develop mid-flight — e.g., a bad deploy starts
dropping treatment-side events on day 3. A single aggregate ``srm_check`` may
still pass because early clean days dilute the signal. ``srm_trend`` bins
the data by time window and runs ``srm_check`` per window to expose drift
over time and report the first violation.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from openxp.stats.srm import srm_check


def _window_alias(window: str) -> str:
    """Translate convenience aliases to pandas offset aliases."""
    mapping = {
        "1d": "1D",
        "1D": "1D",
        "day": "1D",
        "daily": "1D",
        "1h": "1h",
        "hour": "1h",
        "hourly": "1h",
        "1w": "7D",
        "week": "7D",
    }
    return mapping.get(window, window)


def srm_trend(
    df: pd.DataFrame,
    treatment_col: str,
    timestamp_col: str,
    window: str = "1d",
    threshold: float = 0.0005,
    expected_ratios: list[float] | None = None,
) -> dict:
    """Bin data into time windows, run SRM per window, summarize trend.

    Args:
        df: DataFrame with at least ``treatment_col`` and ``timestamp_col``.
        treatment_col: Column holding the variant assignment.
        timestamp_col: Datetime (or parseable) column used to bin.
        window: Pandas offset alias or convenience alias (``"1d"``,
            ``"1h"``, ``"1w"``). Default ``"1d"``.
        threshold: SRM p-value threshold passed through to ``srm_check``.
            Default ``0.0005`` — matches the ``run_monitor`` orchestrator
            default, which is stricter than a single-look SRM check because
            the trend view performs many per-window looks and needs a
            tighter per-window bound to keep family-wise error in check.
        expected_ratios: Optional expected allocation ratios (defaults to
            equal split inside ``srm_check``).

    Returns:
        dict with:
            - ``test``: ``"srm_trend"``
            - ``window``: canonical window alias used
            - ``n_windows``: int
            - ``per_window``: list of per-window dicts
                (``window_start``, ``n``, ``observed_counts``, ``verdict``, ``p_value``)
            - ``first_violation_timestamp``: ISO string or None
            - ``consecutive_violations``: longest run of non-PASS windows
              ending at the most recent window
            - ``trend_direction``: ``"improving" | "stable" | "worsening"``
            - ``verdict``: ``"PASS" | "WARNING" | "BLOCK"`` (aggregate)
            - ``interpretation``: plain-language summary
    """
    if treatment_col not in df.columns:
        return {
            "test": "srm_trend",
            "error": f"treatment_col {treatment_col!r} not in DataFrame",
            "verdict": "BLOCK",
            "interpretation": (
                f"Cannot run SRM trend — column {treatment_col!r} missing."
            ),
        }
    if timestamp_col not in df.columns:
        return {
            "test": "srm_trend",
            "error": f"timestamp_col {timestamp_col!r} not in DataFrame",
            "verdict": "BLOCK",
            "interpretation": (
                f"Cannot run SRM trend — column {timestamp_col!r} missing."
            ),
        }

    if len(df) == 0:
        return {
            "test": "srm_trend",
            "window": window,
            "n_windows": 0,
            "per_window": [],
            "first_violation_timestamp": None,
            "consecutive_violations": 0,
            "trend_direction": "stable",
            "verdict": "BLOCK",
            "interpretation": "No data supplied to srm_trend.",
        }

    # Coerce timestamps. Copy the slice so we never mutate the caller.
    work = df[[treatment_col, timestamp_col]].copy()
    work[timestamp_col] = pd.to_datetime(work[timestamp_col], errors="coerce")
    work = work.dropna(subset=[timestamp_col])
    if len(work) == 0:
        return {
            "test": "srm_trend",
            "error": "All timestamps failed to parse.",
            "verdict": "BLOCK",
            "interpretation": (
                f"Column {timestamp_col!r} could not be parsed as datetime."
            ),
        }

    freq = _window_alias(window)
    # Stable order for variant counts across windows.
    variant_order = sorted(work[treatment_col].dropna().unique().tolist())
    work = work.set_index(timestamp_col).sort_index()

    per_window: list[dict[str, Any]] = []
    grouped = work.groupby(pd.Grouper(freq=freq))
    for window_start, chunk in grouped:
        if len(chunk) == 0:
            continue
        counts_series = chunk[treatment_col].value_counts()
        # Always reindex against the global variant order so missing variants
        # register as 0 in downstream SRM checks (that IS the signal).
        counts = [int(counts_series.get(v, 0)) for v in variant_order]
        result = srm_check(
            counts,
            expected_ratios=expected_ratios,
            threshold=threshold,
        )
        per_window.append(
            {
                "window_start": window_start.isoformat(),
                "n": int(sum(counts)),
                "variant_order": variant_order,
                "observed_counts": counts,
                "verdict": result.get("verdict", "BLOCK"),
                "p_value": result.get("p_value"),
            }
        )

    n_windows = len(per_window)
    if n_windows == 0:
        return {
            "test": "srm_trend",
            "window": window,
            "n_windows": 0,
            "per_window": [],
            "first_violation_timestamp": None,
            "consecutive_violations": 0,
            "trend_direction": "stable",
            "verdict": "BLOCK",
            "interpretation": "No populated time windows after binning.",
        }

    # First violation = earliest non-PASS window.
    first_violation_timestamp: str | None = None
    for entry in per_window:
        if entry["verdict"] != "PASS":
            first_violation_timestamp = entry["window_start"]
            break

    # Consecutive violations = longest tail run of non-PASS verdicts.
    consecutive = 0
    for entry in reversed(per_window):
        if entry["verdict"] != "PASS":
            consecutive += 1
        else:
            break

    # Trend direction — split p-values in half, compare means. Missing p-values
    # (from error returns) are coerced to 0 (treated as "bad").
    p_values = [e["p_value"] if e["p_value"] is not None else 0.0 for e in per_window]
    trend_direction = "stable"
    if n_windows >= 2:
        half = max(1, n_windows // 2)
        first_half_mean = sum(p_values[:half]) / half
        second_half_mean = sum(p_values[-half:]) / half
        delta = second_half_mean - first_half_mean
        if delta > 0.05:
            trend_direction = "improving"
        elif delta < -0.05:
            trend_direction = "worsening"

    verdicts = [e["verdict"] for e in per_window]
    if any(v == "BLOCK" for v in verdicts):
        agg_verdict = "BLOCK"
    elif any(v == "WARNING" for v in verdicts):
        agg_verdict = "WARNING"
    else:
        agg_verdict = "PASS"

    if agg_verdict == "PASS":
        interp = (
            f"SRM trend clean across {n_windows} {window} window(s). "
            "No window-level mismatch detected."
        )
    else:
        interp = (
            f"SRM trend verdict: {agg_verdict}. "
            f"First violation at {first_violation_timestamp}, "
            f"{consecutive} consecutive violation(s) through the most recent window. "
            f"Trend direction: {trend_direction}. "
            "Investigate assignment pipeline or deploy history near the first-violation window."
        )

    return {
        "test": "srm_trend",
        "window": window,
        "threshold": threshold,
        "n_windows": n_windows,
        "per_window": per_window,
        "first_violation_timestamp": first_violation_timestamp,
        "consecutive_violations": consecutive,
        "trend_direction": trend_direction,
        "verdict": agg_verdict,
        "interpretation": interp,
    }
